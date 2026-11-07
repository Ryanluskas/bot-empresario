"""
Multi-Brave Engine & Safe Concurrency Architecture — Bot Empresário
Gerencia múltiplas instâncias isoladas do Brave Browser, distribuição inteligente
de clientes com identificador único (request_id), auto-tiling de janelas no Windows,
e controle transacional de resultados.
"""

import os
import sys
import time
import uuid
import math
import ctypes
from ctypes import wintypes
import logging
import threading
import random
import pandas as pd
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import security_config

logger = logging.getLogger("multi_brave")

# ---------------------------------------------------------------------------
# DIRETÓRIOS E CONFIGURAÇÕES
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROFILES_BASE = os.path.join(DATA_DIR, "profiles")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "logs", "screenshots")

os.makedirs(PROFILES_BASE, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. GERENCIAMENTO DE RECURSOS DA MÁQUINA (RAM & CPU)
# ---------------------------------------------------------------------------
class SystemResources:
    """Verifica memória RAM e CPU no Windows para determinar limites seguros."""

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    @classmethod
    def get_info(cls) -> dict:
        total_ram_gb = 8.0
        free_ram_gb = 2.0
        try:
            stat = cls.MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(cls.MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_ram_gb = round(stat.ullTotalPhys / (1024 ** 3), 2)
                free_ram_gb = round(stat.ullAvailPhys / (1024 ** 3), 2)
        except Exception as e:
            logger.warning(f"Não foi possível obter memória via Win32: {e}")

        cpu_cores = os.cpu_count() or 4

        # Cada instância do Brave com Angular SPA consome ~0.5 a 0.7 GB de RAM
        # Recomendamos 1 a 2 workers por padrão em máquinas com até 8GB RAM
        if free_ram_gb < 1.0:
            rec = 1
        elif free_ram_gb < 2.0:
            rec = min(2, cpu_cores)
        else:
            rec = min(math.floor(free_ram_gb / 0.7), cpu_cores, 4)

        return {
            "total_ram_gb": total_ram_gb,
            "free_ram_gb": free_ram_gb,
            "cpu_cores": cpu_cores,
            "recommended_workers": max(1, rec),
        }

    @classmethod
    def check_capacity(cls, requested: int) -> str | None:
        info = cls.get_info()
        rec = info["recommended_workers"]
        if requested > rec:
            return (
                f"Atenção: {requested} Braves solicitados. "
                f"Sua máquina possui {info['free_ram_gb']} GB de RAM livre. "
                f"A capacidade recomendada para estabilidade é de {rec} instâncias."
            )
        return None


# ---------------------------------------------------------------------------
# 2. ORGANIZADOR VISUAL DE JANELAS (AUTO-TILING NO WINDOWS)
# ---------------------------------------------------------------------------
class WindowManager:
    """Calcula posições e dimensões automáticas para janelas na área visível."""

    SPI_GETWORKAREA = 0x0030
    SWP_NOZORDER = 0x0004
    SWP_SHOWWINDOW = 0x0040

    @classmethod
    def get_work_area(cls) -> tuple[int, int, int, int]:
        """Retorna (x, y, largura, altura) da área de trabalho excluindo a barra de tarefas."""
        try:
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(cls.SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                x = rect.left
                y = rect.top
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                return x, y, w, h
        except Exception as e:
            logger.warning(f"Falha ao ler SPI_GETWORKAREA: {e}")

        # Fallback para 1920x1040
        return 0, 0, 1920, 1040

    @classmethod
    def calculate_geometry(cls, worker_index: int, total_workers: int) -> dict:
        """Calcula x, y, width, height para a janela de um worker específico."""
        base_x, base_y, work_w, work_h = cls.get_work_area()

        if total_workers <= 1:
            return {
                "x": base_x,
                "y": base_y,
                "width": work_w,
                "height": work_h,
            }

        if total_workers == 2:
            w = work_w // 2
            return {
                "x": base_x + (worker_index * w),
                "y": base_y,
                "width": w,
                "height": work_h,
            }

        if total_workers == 3:
            # Layout de 3 colunas lado a lado
            col_w = work_w // 3
            return {
                "x": base_x + (worker_index * col_w),
                "y": base_y,
                "width": col_w if worker_index < 2 else (work_w - 2 * col_w),
                "height": work_h,
            }

        if total_workers == 4:
            # Grade 2x2
            w = work_w // 2
            h = work_h // 2
            col = worker_index % 2
            row = worker_index // 2
            return {
                "x": base_x + (col * w),
                "y": base_y + (row * h),
                "width": w,
                "height": h,
            }

        # Para mais de 4: Grade dinâmica
        cols = math.ceil(math.sqrt(total_workers))
        rows = math.ceil(total_workers / cols)
        w = work_w // cols
        h = work_h // rows
        col = worker_index % cols
        row = worker_index // cols
        return {
            "x": base_x + (col * w),
            "y": base_y + (row * h),
            "width": w,
            "height": h,
        }

    @classmethod
    def find_and_tile_window(cls, title_keyword: str, rect: dict):
        """Encontra janela pelo título e aplica SetWindowPos no Windows."""
        try:
            user32 = ctypes.windll.user32
            found_hwnd = None

            def _enum_cb(hwnd, lparam):
                nonlocal found_hwnd
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        if title_keyword.lower() in buff.value.lower():
                            found_hwnd = hwnd
                            return False
                return True

            cb_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(cb_type(_enum_cb), 0)

            if found_hwnd:
                user32.SetWindowPos(
                    found_hwnd, 0,
                    rect["x"], rect["y"], rect["width"], rect["height"],
                    cls.SWP_NOZORDER | cls.SWP_SHOWWINDOW
                )
        except Exception as e:
            logger.debug(f"Não foi possível aplicar SetWindowPos: {e}")


# ---------------------------------------------------------------------------
# 3. FILA CENTRALIZADA E DISTRIBUIÇÃO INTELIGENTE DE CLIENTES
# ---------------------------------------------------------------------------
class ClientQueueManager:
    """
    Gerencia a distribuição equilibrada de clientes, isolamento de requisição
    e tolerância a falhas.
    """

    def __init__(self, df: pd.DataFrame, num_workers: int):
        self._lock = threading.Lock()
        self.df = df
        self.total = len(df)
        self.num_workers = max(1, num_workers)

        # Mapeamento do estado de cada cliente
        # status: 'PENDENTE' | 'EM_PROCESSAMENTO' | 'CONCLUIDO' | 'ERRO' | 'PULADO'
        self.clients = []
        for idx in range(self.total):
            status_atual = str(df.at[idx, "Tem_Emprestimo"]).strip()
            ja_concluido = status_atual in ["Sim", "Não"]

            self.clients.append({
                "idx": idx,
                "client_id": f"CLI-{idx:05d}",
                "nome": str(df.at[idx, "NOME"] if "NOME" in df.columns else "Lead").strip() or "Lead",
                "cpf_raw": str(df.at[idx, "CPF/CNPJ"]).strip(),
                "ddd": str(df.at[idx, "DDD"] if "DDD" in df.columns else "").strip(),
                "fone": str(df.at[idx, "FONE"] if "FONE" in df.columns else "").strip(),
                "status_negocio": status_atual,
                "estado_fila": "CONCLUIDO" if ja_concluido else "PENDENTE",
                "worker_id": None,
                "request_id": None,
                "tentativas": 0,
                "inicio_ts": None,
            })

        self._redistribuir_particoes()

    def _redistribuir_particoes(self):
        """Distribui clientes pendentes entre os workers disponíveis de forma proporcional."""
        with self._lock:
            pendentes = [c for c in self.clients if c["estado_fila"] == "PENDENTE"]
            n_pend = len(pendentes)
            if n_pend == 0:
                return

            base_cota = n_pend // self.num_workers
            resto = n_pend % self.num_workers

            offset = 0
            for w in range(1, self.num_workers + 1):
                cota = base_cota + (1 if w <= resto else 0)
                lote = pendentes[offset: offset + cota]
                for c in lote:
                    c["worker_id"] = w
                offset += cota

            logger.info(
                f"Distribuição realizada: {n_pend} pendentes entre {self.num_workers} workers."
            )

    def set_worker_count(self, new_count: int):
        """Ajusta quantidade de workers e redistribui clientes pendentes."""
        with self._lock:
            self.num_workers = max(1, new_count)
        self._redistribuir_particoes()

    def get_assigned_count(self, worker_id: int) -> int:
        """Retorna quantos clientes pendentes ou em processamento pertencem a este worker."""
        with self._lock:
            return sum(
                1 for c in self.clients
                if c["worker_id"] == worker_id and c["estado_fila"] in ["PENDENTE", "EM_PROCESSAMENTO"]
            )

    def claim_next(self, worker_id: int) -> dict | None:
        """
        Aloca o próximo cliente pendente para o worker_id de forma atômica.
        Gera um request_id exclusivo para rastreabilidade transacional.
        """
        with self._lock:
            # 1. Procura na cota deste worker
            alvo = None
            for c in self.clients:
                if c["worker_id"] == worker_id and c["estado_fila"] == "PENDENTE":
                    alvo = c
                    break

            # 2. Se a cota deste worker acabou, auxilia pegando de outro worker que tenha excesso
            if alvo is None:
                for c in self.clients:
                    if c["estado_fila"] == "PENDENTE":
                        alvo = c
                        alvo["worker_id"] = worker_id
                        break

            if alvo is None:
                return None

            alvo["estado_fila"] = "EM_PROCESSAMENTO"
            alvo["inicio_ts"] = time.time()
            alvo["tentativas"] += 1
            alvo["request_id"] = f"REQ-W{worker_id:02d}-{alvo['client_id']}-{uuid.uuid4().hex[:6]}"

            return dict(alvo)

    def mark_completed(self, request_id: str, status_negocio: str) -> bool:
        """Marca o cliente como concluído garantindo integridade do request_id."""
        with self._lock:
            for c in self.clients:
                if c["request_id"] == request_id:
                    c["estado_fila"] = "CONCLUIDO"
                    c["status_negocio"] = status_negocio
                    self.df.at[c["idx"], "Tem_Emprestimo"] = status_negocio
                    return True
        return False

    def mark_failed(self, request_id: str, motivo: str) -> bool:
        """Registra falha. Se exceder limite de tentativas, marca como ERRO."""
        with self._lock:
            for c in self.clients:
                if c["request_id"] == request_id:
                    if c["tentativas"] >= 2:
                        c["estado_fila"] = "ERRO"
                        c["status_negocio"] = "Erro"
                        self.df.at[c["idx"], "Tem_Emprestimo"] = "Erro"
                    else:
                        # Devolve para pendente para retry seguro
                        c["estado_fila"] = "PENDENTE"
                    return True
        return False

    def release_worker_clients(self, worker_id: int):
        """Se um worker for encerrado/cair, libera seus clientes pendentes para os outros."""
        with self._lock:
            for c in self.clients:
                if c["worker_id"] == worker_id:
                    if c["estado_fila"] == "PENDENTE":
                        c["worker_id"] = None
                    elif c["estado_fila"] == "EM_PROCESSAMENTO":
                        # Timeout de verificação
                        c["estado_fila"] = "PENDENTE"
                        c["worker_id"] = None
        self._redistribuir_particoes()

    def get_summary(self) -> dict:
        with self._lock:
            pendentes = sum(1 for c in self.clients if c["estado_fila"] == "PENDENTE")
            processando = sum(1 for c in self.clients if c["estado_fila"] == "EM_PROCESSAMENTO")
            concluidos = sum(1 for c in self.clients if c["estado_fila"] == "CONCLUIDO")
            erros = sum(1 for c in self.clients if c["estado_fila"] == "ERRO")
            sim = sum(1 for c in self.clients if c["status_negocio"] == "Sim")
            nao = sum(1 for c in self.clients if c["status_negocio"] == "Não")
            return {
                "total": self.total,
                "pendentes": pendentes,
                "processando": processando,
                "concluidos": concluidos,
                "erros": erros,
                "sim": sim,
                "nao": nao,
            }


# ---------------------------------------------------------------------------
# 4. COLETOR DE RESULTADOS E PERSISTÊNCIA ATÔMICA
# ---------------------------------------------------------------------------
class ResultCollector:
    """Centraliza a gravação do Excel sob Lock para evitar concorrência de I/O."""

    def __init__(self, caminho_saida: str, caminho_sim: str):
        self._lock = threading.Lock()
        self.caminho_saida = caminho_saida
        self.caminho_sim = caminho_sim
        self._pendentes_salvar = 0

    def salvar(self, df: pd.DataFrame, forcar: bool = False):
        with self._lock:
            self._pendentes_salvar += 1
            if not forcar and self._pendentes_salvar < 5:
                return

            self._pendentes_salvar = 0
            self._salvar_atomico(df, self.caminho_saida)
            df_sim = df[df["Tem_Emprestimo"] == "Sim"]
            if not df_sim.empty:
                self._salvar_atomico(df_sim, self.caminho_sim)

    @staticmethod
    def _salvar_atomico(df: pd.DataFrame, caminho: str):
        raiz, ext = os.path.splitext(caminho)
        tmp = f"{raiz}.tmp_{uuid.uuid4().hex[:6]}{ext}"
        try:
            df.to_excel(tmp, index=False)
            os.replace(tmp, caminho)
        except Exception as e:
            logger.warning(f"Falha ao salvar '{caminho}': {e}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 5. WORKER THREAD INDEPENDENTE (BRAVE INSTANCE)
# ---------------------------------------------------------------------------
class BraveWorker(threading.Thread):
    """
    Controla uma instância individual e isolada do Brave Browser via Playwright Sync.
    Possui perfil próprio, página própria e fila própria.
    """

    def __init__(
        self,
        worker_id: int,
        total_workers: int,
        queue_mgr: ClientQueueManager,
        collector: ResultCollector,
        status_queue,
        stop_event: threading.Event,
        brave_exe: str,
        stealth_js: str,
    ):
        super().__init__(name=f"WorkerBrave-{worker_id:02d}", daemon=True)
        self.worker_id = worker_id
        self.total_workers = total_workers
        self.queue_mgr = queue_mgr
        self.collector = collector
        self.status_queue = status_queue
        self.stop_event = stop_event
        self.brave_exe = brave_exe
        self.stealth_js = stealth_js

        # Perfil isolado
        self.profile_dir = os.path.join(PROFILES_BASE, f"worker_{worker_id:02d}")
        os.makedirs(self.profile_dir, exist_ok=True)

        # Estado individual para a GUI
        self.status = "Iniciando"
        self.cliente_atual = "—"
        self.etapa_atual = "Aguardando"
        self.processados = 0
        self.erros = 0
        self.start_time = time.time()
        self._pw = None
        self._ctx = None
        self._page = None

    def _notificar_estado(self):
        """Envia estado detalhado deste worker para a GUI."""
        elapsed_sec = int(time.time() - self.start_time)
        mins = elapsed_sec // 60
        secs = elapsed_sec % 60
        tempo_txt = f"{mins:02d}:{secs:02d}"

        self.status_queue.put({
            "type": "worker_status",
            "worker_id": self.worker_id,
            "status": self.status,
            "cliente": self.cliente_atual,
            "etapa": self.etapa_atual,
            "processados": self.processados,
            "erros": self.erros,
            "tempo": tempo_txt,
        })

    def run(self):
        logger.info(f"[Worker {self.worker_id}] Iniciando thread...")
        self.status = "Iniciando"
        self._notificar_estado()

        # Staggering na inicialização: evita pico de CPU/RAM ao abrir vários navegadores
        delay_inicio = (self.worker_id - 1) * 3.5
        if delay_inicio > 0:
            time.sleep(delay_inicio)

        try:
            with sync_playwright() as pw:
                self._pw = pw
                geom = WindowManager.calculate_geometry(self.worker_id - 1, self.total_workers)

                logger.info(
                    f"[Worker {self.worker_id}] Geometria da janela: "
                    f"x={geom['x']}, y={geom['y']}, w={geom['width']}, h={geom['height']}"
                )

                self._ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    executable_path=self.brave_exe,
                    headless=False,
                    ignore_default_args=["--enable-automation"],
                    args=[
                        "--no-first-run",
                        "--lang=pt-BR",
                        "--disable-blink-features=AutomationControlled",
                        f"--window-position={geom['x']},{geom['y']}",
                        f"--window-size={geom['width']},{geom['height']}",
                    ],
                    viewport={"width": 1280, "height": 800},
                    locale="pt-BR",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/136.0.0.0 Safari/537.36 Brave/136"
                    ),
                )

                self._ctx.add_init_script(self.stealth_js)
                self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

                # Tenta ajustar a janela milimetricamente via Win32 após spawn
                WindowManager.find_and_tile_window(f"worker_{self.worker_id:02d}", geom)

                # Realiza autenticação inicial
                self.status = "Autenticando"
                self.etapa_atual = "Login Santander"
                self._notificar_estado()

                self._fazer_login()

                # Loop de simulações do Worker
                self.status = "Executando"
                self._notificar_estado()

                self._loop_simulacoes()

        except Exception as e:
            logger.error(f"[Worker {self.worker_id}] Falha crítica: {e}", exc_info=True)
            self.status = "Falha"
            self.etapa_atual = str(e)[:30]
            self.erros += 1
            self._notificar_estado()
        finally:
            self._limpar_e_fechar()

    def _fazer_login(self):
        """Executa navegação e auto-login no portal Santander."""
        url_landing = "https://www.parceirosantander.com.br/spa-base/landing-page"
        try:
            self._page.goto(url_landing, wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            pass

        cpf, senha = security_config.load_credentials()

        # Importa lógica de login de bot_santander de forma segura
        import bot_santander as core_bot
        tentativas = 0
        while not self.stop_event.is_set() and tentativas < 30:
            form_page = core_bot._encontrar_pagina_formulario(self._ctx)
            if form_page is not None:
                self._page = form_page
                logger.info(f"[Worker {self.worker_id}] Formulário detectado!")
                return

            # Tenta auto-login
            core_bot.tentar_login_automatico(self._page)
            time.sleep(2)
            tentativas += 1

    def _loop_simulacoes(self):
        """Consome clientes da fila central atribuídos a este worker."""
        import bot_santander as core_bot

        processados_no_burst = 0
        proximo_descanso = random.randint(core_bot.BURST_MIN, core_bot.BURST_MAX)

        while not self.stop_event.is_set():
            cliente = self.queue_mgr.claim_next(self.worker_id)
            if cliente is None:
                logger.info(f"[Worker {self.worker_id}] Não há mais clientes pendentes.")
                self.status = "Concluído"
                self.etapa_atual = "Fila vazia"
                self.cliente_atual = "—"
                self._notificar_estado()
                break

            idx = cliente["idx"]
            req_id = cliente["request_id"]
            nome = cliente["nome"]
            cpf_raw = cliente["cpf_raw"]
            ddd = cliente["ddd"]
            fone = cliente["fone"]

            # Sanitização e Validação Estrita de Dados
            cpf_digits = "".join(ch for ch in cpf_raw if ch.isdigit())
            cpf = cpf_digits.lstrip("0").zfill(11) if len(cpf_digits) > 11 else cpf_digits.zfill(11)
            telefone = security_config.sanitize_phone(ddd, fone)

            cpf_mascarado = security_config.mask_cpf(cpf)
            self.cliente_atual = f"{nome[:20]} ({cpf_mascarado})"
            self.etapa_atual = "Validando dados"
            self._notificar_estado()

            if len(cpf) != 11:
                logger.warning(f"[{req_id}] CPF inválido ({cpf_mascarado}), registrando.")
                self.queue_mgr.mark_completed(req_id, "CPF Inválido")
                self.erros += 1
                self.processados += 1
                self._notificar_estado()
                continue

            # Inicia ciclo de simulação com verificação de etapas
            status_resultado = "Erro"
            try:
                self.etapa_atual = "Preenchendo"
                self._notificar_estado()

                # Limpeza prévia do formulário
                core_bot.aguardar_formulario(self._page)
                time.sleep(random.uniform(1.2, 2.0))

                # Preenchimento robusto
                core_bot._pausa()
                core_bot._mover_mouse(self._page)
                core_bot._digitar(self._page.get_by_label("Nome PF ou Sócio"), nome)
                core_bot._pausa()
                core_bot._mover_mouse(self._page)
                core_bot._digitar(self._page.get_by_label("CPF ou CNPJ"), cpf)
                core_bot._pausa()
                core_bot._mover_mouse(self._page)
                core_bot._digitar(self._page.get_by_label("DDD + Celular"), telefone)
                core_bot._pausa()
                self._page.locator('button:has-text("Ver produtos")').click()

                self.etapa_atual = "Vitrine de produtos"
                self._notificar_estado()
                core_bot.clicar_simular_consignado(self._page)
                core_bot.fechar_modais(self._page)

                self.etapa_atual = "Lendo resultado"
                self._notificar_estado()
                status_resultado = core_bot.verificar_refinanciamento(self._page)

                # Registra sucesso
                self.queue_mgr.mark_completed(req_id, status_resultado)
                self.processados += 1

                # Salva no coletor central
                self.collector.salvar(self.queue_mgr.df)

            except Exception as e:
                logger.warning(f"[{req_id}] Falha na simulação: {e}")
                self.erros += 1
                self.processados += 1

                # Captura de screenshot em falha para auditoria
                try:
                    shot_path = os.path.join(SCREENSHOTS_DIR, f"falha_{req_id}.png")
                    self._page.screenshot(path=shot_path)
                except Exception:
                    pass

                self.queue_mgr.mark_failed(req_id, str(e))

            # Notifica GUI com o progresso geral
            sumario = self.queue_mgr.get_summary()
            self.status_queue.put({
                "type": "progress",
                "idx": sumario["concluidos"] + sumario["erros"],
                "total": sumario["total"],
                "nome": nome,
                "cpf": cpf,
                "status": status_resultado,
                "sim": sumario["sim"],
                "nao": sumario["nao"],
                "erros": sumario["erros"],
                "worker_id": self.worker_id,
            })

            # Retorno seguro ao formulário
            self.etapa_atual = "Retornando ao form"
            self._notificar_estado()
            core_bot.voltar_ao_formulario(self._page)

            processados_no_burst += 1
            if processados_no_burst >= proximo_descanso:
                duracao = random.uniform(core_bot.DESCANSO_MIN, core_bot.DESCANSO_MAX)
                self.status = "Micro-pausa"
                self.etapa_atual = f"Descanso {int(duracao)}s"
                self._notificar_estado()
                time.sleep(duracao)
                processados_no_burst = 0
                proximo_descanso = random.randint(core_bot.BURST_MIN, core_bot.BURST_MAX)
                self.status = "Executando"

        self.status = "Encerrado"
        self.etapa_atual = "Finalizado"
        self._notificar_estado()

    def _limpar_e_fechar(self):
        """Encerramento limpo e seguro dos recursos do Playwright."""
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:
            pass
        self.queue_mgr.release_worker_clients(self.worker_id)
        self.status = "Parado"
        self._notificar_estado()


# ---------------------------------------------------------------------------
# 6. ORQUESTRADOR MULTI-BRAVE (COORDENADOR GERAL)
# ---------------------------------------------------------------------------
class MultiBraveCoordinator:
    """Orquestra a criação, balanceamento, redimensionamento e parada dos workers."""

    def __init__(self, df: pd.DataFrame, caminho_saida: str, status_queue, stop_event: threading.Event):
        self.df = df
        self.caminho_saida = caminho_saida
        self.caminho_sim = "com_refinanciamento.xlsx"
        self.status_queue = status_queue
        self.stop_event = stop_event
        self.num_workers = 1

        self.queue_mgr = ClientQueueManager(df, self.num_workers)
        self.collector = ResultCollector(self.caminho_saida, self.caminho_sim)
        self.workers: list[BraveWorker] = []
        self._lock = threading.Lock()

    def start(self, num_workers: int):
        with self._lock:
            self.num_workers = max(1, num_workers)
            self.queue_mgr.set_worker_count(self.num_workers)

            import bot_santander as core_bot
            brave_exe = core_bot.BRAVE_EXE
            stealth_js = core_bot.STEALTH_JS

            logger.info(f"Iniciando coordenador com {self.num_workers} Brave(s)...")

            for w_id in range(1, self.num_workers + 1):
                w = BraveWorker(
                    worker_id=w_id,
                    total_workers=self.num_workers,
                    queue_mgr=self.queue_mgr,
                    collector=self.collector,
                    status_queue=self.status_queue,
                    stop_event=self.stop_event,
                    brave_exe=brave_exe,
                    stealth_js=stealth_js,
                )
                self.workers.append(w)
                w.start()

    def set_worker_count(self, new_count: int):
        """Aumenta ou diminui dinamicamente o número de workers em execução."""
        with self._lock:
            new_count = max(1, new_count)
            if new_count == self.num_workers:
                return

            logger.info(f"Redimensionando pool de workers de {self.num_workers} para {new_count}...")
            self.num_workers = new_count
            self.queue_mgr.set_worker_count(new_count)

            # Se aumentou: inicializa novos workers de forma controlada
            if new_count > len(self.workers):
                import bot_santander as core_bot
                for w_id in range(len(self.workers) + 1, new_count + 1):
                    w = BraveWorker(
                        worker_id=w_id,
                        total_workers=new_count,
                        queue_mgr=self.queue_mgr,
                        collector=self.collector,
                        status_queue=self.status_queue,
                        stop_event=self.stop_event,
                        brave_exe=core_bot.BRAVE_EXE,
                        stealth_js=core_bot.STEALTH_JS,
                    )
                    self.workers.append(w)
                    w.start()

            # Se diminuiu: sinaliza workers excedentes para encerrarem após o cliente atual
            elif new_count < len(self.workers):
                excedentes = self.workers[new_count:]
                for w in excedentes:
                    w.stop_event.set()

            # Reorganiza visualmente na tela
            self.reorganize_windows()

    def reorganize_windows(self):
        """Reorganiza todas as janelas do Brave ativas na tela."""
        for i, w in enumerate(self.workers):
            if w.is_alive():
                geom = WindowManager.calculate_geometry(i, len(self.workers))
                WindowManager.find_and_tile_window(f"worker_{w.worker_id:02d}", geom)

    def wait_all(self):
        """Aguarda a conclusão de todos os workers e salva o resultado final."""
        for w in self.workers:
            w.join()
        self.collector.salvar(self.queue_mgr.df, forcar=True)
        logger.info("Todos os workers concluídos com sucesso.")
