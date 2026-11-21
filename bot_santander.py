"""
RPA - Parceiro Santander | Simulação de Crédito Consignado
"""

import os
import re
import time
import random
import logging
import threading
import queue as _queue_mod
from urllib.parse import urlsplit

import pandas as pd
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
ARQUIVO_ENTRADA = "clientes.csv"
ARQUIVO_SAIDA   = "resultado_filtrado.xlsx"
URL_FORMULARIO  = "https://www.parceirosantander.com.br/spa-base/logged-area/recommendation/"
URL_LANDING     = "https://www.parceirosantander.com.br/spa-base/landing-page"
_PORTAL = urlsplit(URL_FORMULARIO)
_HOSTS_SANTANDER = {_PORTAL.hostname, "login.santander.com.br"}
_ORIENTACAO_LOGIN = (
    "No Brave, clique em Acessar o Portal e conclua o login, inclusive o código de verificação se solicitado. "
    "Depois, abra a área de recomendação se ela não aparecer automaticamente."
)
PERFIL_DIR      = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
    r"BraveSoftware\Brave-Browser\User Data",
)


def _achar_brave() -> str:
    """Brave muda de lugar conforme a instalação (máquina/usuário)."""
    candidatos = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    return candidatos[0]


BRAVE_EXE       = _achar_brave()
TIMEOUT         = 25_000

# Intervalo de processamento entre lotes
BURST_MIN    = 8
BURST_MAX    = 12
DESCANSO_MIN = 45    # segundos
DESCANSO_MAX = 70    # segundos

# ---------------------------------------------------------------------------
# CANAIS GUI (usados pela interface gráfica; no modo terminal ficam ociosos)
# ---------------------------------------------------------------------------
_stop_event   = threading.Event()   # GUI seta para parar o bot
_status_queue = _queue_mod.Queue()  # Bot envia progresso/status para a GUI

logging.basicConfig(
    filename="bot_log.txt",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _pausa(a=0.4, b=0.9):
    time.sleep(random.uniform(a, b))


# ---------------------------------------------------------------------------
# VALIDAÇÃO E NORMALIZAÇÃO DE DADOS (TELEFONE / NOME)
# ---------------------------------------------------------------------------
VALID_DDDS = {
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28",
    "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49",
    "51", "53", "54", "55",
    "61", "62", "63", "64", "65", "66", "67", "68", "69",
    "71", "73", "74", "75", "77", "79",
    "81", "82", "83", "84", "85", "86", "87", "88", "89",
    "91", "92", "93", "94", "95", "96", "97", "98", "99",
}


def normalizar_telefone(valor, ddd_fallback: str = "") -> str:
    """
    Normaliza e valida número de telefone brasileiro para preenchimento.

    Regras de conformidade:
    - Preserva os dígitos originais.
    - Remove formatações existentes (espaços, traços, parênteses).
    - Identifica e remove DDI 55 (ex: 5562999999999 -> 62999999999).
    - Remove zeros de operadora/tronco à esquerda (ex: 062999999999 -> 62999999999).
    - Valida o DDD contra a tabela oficial da Anatel (nunca aceita '00').
    - Distingue e preserva telefones de 10 dígitos (fixo/móvel antigo) e 11 dígitos (celular).
    - Se o número tiver 8 ou 9 dígitos e houver ddd_fallback válido, junta ambos.
    - NUNCA gera zeros indevidos ("00") e nunca completa artificialmente.
    - Retorna apenas a string de dígitos (10 ou 11) ou None se inválido.
    """
    if valor is None:
        return None

    s = str(valor).strip()
    if not s or s.lower() in ("nan", "none", "null", "undefined"):
        return None

    if s.endswith(".0"):
        s = s[:-2]

    digits = re.sub(r"\D", "", s)
    if not digits:
        return None

    # Se começa com 00 (ex: 0055...), remove prefixo internacional
    if digits.startswith("00") and len(digits) > 12:
        digits = digits[2:]

    # Remove zeros de tronco à esquerda se houver DDD válido em seguida
    while digits.startswith("0") and len(digits) > 11:
        digits = digits[1:]

    # Trata DDI 55
    if digits.startswith("55") and len(digits) in (12, 13):
        pos_ddi = digits[2:]
        ddd_candidato = pos_ddi[:2]
        if ddd_candidato in VALID_DDDS:
            digits = pos_ddi

    if len(digits) == 12 and digits.startswith("0"):
        digits = digits[1:]

    # Se tem 8 ou 9 dígitos (sem DDD), tenta ddd_fallback se fornecido e válido
    if len(digits) in (8, 9) and ddd_fallback:
        ddd_clean = re.sub(r"\D", "", str(ddd_fallback).strip())[:2]
        if ddd_clean in VALID_DDDS:
            digits = ddd_clean + digits

    # Validação de tamanho (10 dígitos para fixo / 11 dígitos para celular)
    if len(digits) not in (10, 11):
        return None

    # Validação de DDD (rejeita 00 e qualquer DDD inexistente no Brasil)
    ddd = digits[:2]
    if ddd not in VALID_DDDS:
        return None

    return digits


def formatar_telefone_visual(digits: str) -> str:
    """Retorna o telefone formatado visualmente para exibição/logs."""
    if not digits:
        return ""
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    elif len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return digits


def extrair_nome_linha(linha) -> str:
    """Extrai o nome do cliente verificando variações comuns de colunas."""
    for col in ["NOME", "NOME DO SERVIDOR", "NOME CLIENTE", "NOME_CLIENTE", "CLIENTE", "RAZAO SOCIAL", "RAZAO_SOCIAL"]:
        if col in linha.index:
            v = linha.get(col)
            if v is not None and not pd.isna(v):
                s = str(v).strip()
                if s and s.lower() != "nan":
                    return s
    for col in linha.index:
        if "NOME" in str(col).upper():
            v = linha.get(col)
            if v is not None and not pd.isna(v):
                s = str(v).strip()
                if s and s.lower() != "nan":
                    return s
    return "Lead"


def extrair_telefone_linha(linha) -> str:
    """
    Localiza e normaliza o telefone do cliente na linha.
    Suporta:
    1. Coluna única (CELULAR, TELEFONE, CONTATO, WHATSAPP, TEL, FONE, NUMERO, etc.).
    2. Colunas separadas de DDD e FONE (incluindo sufixos DDD.1, FONE.1, etc.).
    3. Qualquer coluna de telefone/celular genérica.
    Retorna apenas a string de 10 ou 11 dígitos normalizada e validada, ou None se inválido.
    """
    colunas_prioritarias = [
        "CELULAR", "TELEFONE", "CONTATO", "WHATSAPP", "TEL", "FONE",
        "NUMERO", "DDD + CELULAR", "TELEFONE CELULAR", "CEL", "CELULAR1", "TELEFONE1"
    ]
    ddd_base = str(linha.get("DDD", "")).strip()

    # 1. Procura nas colunas prioritárias de número único
    for col in colunas_prioritarias:
        if col in linha.index:
            v = linha.get(col)
            norm = normalizar_telefone(v, ddd_fallback=ddd_base)
            if norm:
                return norm

    # 2. Procura em pares DDD + FONE (com prioridade para WhatsApp se houver)
    candidato = None
    for i in range(8):
        sfx = "" if i == 0 else f".{i}"
        d = str(linha.get(f"DDD{sfx}", "")).strip()
        f = str(linha.get(f"FONE{sfx}", "")).strip()
        w = str(linha.get(f"POSSUI-WHATSAPP{sfx}", "0")).strip()
        if d and f and d.lower() != "nan" and f.lower() != "nan":
            comb = normalizar_telefone(f, ddd_fallback=d)
            if comb:
                if w == "1" and len(comb) == 11:
                    return comb
                if candidato is None:
                    candidato = comb

    if candidato:
        return candidato

    # 3. Busca genérica em qualquer coluna cujo cabeçalho lembre telefone/celular
    for col in linha.index:
        c_upper = str(col).upper()
        if any(term in c_upper for term in ["CELULAR", "TELEFONE", "FONE", "CONTATO", "WHATSAPP"]) and "DDD" not in c_upper:
            norm = normalizar_telefone(linha.get(col), ddd_fallback=ddd_base)
            if norm:
                return norm

    return None


def _digitar(locator, texto: str):
    """Digita com velocidade de digitador rápido — gera eventos de teclado reais."""
    try:
        locator.click()
        locator.fill("")
        locator.press("Control+a")
        locator.press("Backspace")
        locator.type(texto, delay=random.randint(38, 72))
    except Exception:
        locator.fill(texto)


# ---------------------------------------------------------------------------
# SESSÃO / URL
# ---------------------------------------------------------------------------
class AcessoSantanderNegado(RuntimeError):
    pass


def _verificar_acesso_santander(ctx):
    """Interrompe o fluxo se o Santander exibir uma página de acesso negado."""
    textos_negado = {"access denied", "acesso negado"}
    for aba in ctx.pages:
        if urlsplit(aba.url).hostname not in _HOSTS_SANTANDER:
            continue
        try:
            if aba.title().strip().casefold() not in textos_negado:
                cabecalhos = aba.locator("h1").all_text_contents()
                if not any(t.strip().casefold() in textos_negado for t in cabecalhos):
                    continue
        except PlaywrightError:
            continue  # A aba pode ter sido fechada ou redirecionada.

        mensagem = "O Santander negou o acesso. Se o erro persistir no login manual, contate o suporte do portal."
        try:
            corpo = aba.locator("body").text_content(timeout=1000) or ""
        except PlaywrightError:
            corpo = ""
        referencia = re.search(r"\bReference\s+#([a-z0-9]+(?:\.[a-z0-9]+)+)\b", corpo, re.IGNORECASE)
        if referencia:
            mensagem += f" Referência do Santander #{referencia[1]}."
        raise AcessoSantanderNegado(mensagem)


def _url_real(page) -> str:
    """URL real via JS — captura pushState do Angular SPA."""
    try:
        return page.evaluate("window.location.href")
    except Exception:
        return page.url


def sessao_expirada(page) -> bool:
    url = _url_real(page).lower()
    return "landing-page" in url or "/login" in url or "logout" in url


def _encontrar_pagina_formulario(ctx):
    """Varre todas as abas e retorna a primeira com o formulário."""
    for p in ctx.pages:
        try:
            url = urlsplit(_url_real(p))
            if (
                (url.scheme, url.netloc) == (_PORTAL.scheme, _PORTAL.netloc)
                and url.path.rstrip("/") == _PORTAL.path.rstrip("/")
            ):
                return p
        except Exception:
            continue
    return None


def _aguardar_formulario_autenticado(ctx, timeout=None):
    prazo = None if timeout is None else time.monotonic() + timeout
    while not _stop_event.is_set() and ctx.pages:
        _verificar_acesso_santander(ctx)
        formulario = _encontrar_pagina_formulario(ctx)
        if formulario is not None:
            return formulario
        if prazo is not None and time.monotonic() >= prazo:
            return None
        _stop_event.wait(1)
    return None


def _achar_pagina_login(ctx):
    """Retorna a aba de login (openid-connect / keycloak / /login)."""
    for p in ctx.pages:
        try:
            url = urlsplit(p.url)
            if url.scheme == "https" and url.hostname in _HOSTS_SANTANDER and any(
                k in url.path.lower() for k in ("openid", "/login", "corp/protocol", "keycloak", "/auth")
            ):
                return p
        except Exception:
            pass
    return None


def _abrir_portal(page):
    try:
        page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
    except PlaywrightTimeoutError:
        # A página pode completar o carregamento enquanto o bot aguarda o login.
        pass


def aguardar_relogin(page):
    """Aguarda o operador recuperar a sessão pelo portal."""
    ctx = page.context
    _verificar_acesso_santander(ctx)
    if _stop_event.is_set():
        return None

    encontrada = _encontrar_pagina_formulario(ctx)
    if encontrada is not None:
        return encontrada

    _status_queue.put({"type": "sessao_expirada"})
    print(f"Sessão expirada. {_ORIENTACAO_LOGIN}", flush=True)
    if _achar_pagina_login(ctx) is None and not urlsplit(page.url).path.endswith("/landing-page"):
        _abrir_portal(page)

    encontrada = _aguardar_formulario_autenticado(ctx, timeout=7200)
    if encontrada is not None:
        _status_queue.put({"type": "login_ok"})
    return encontrada


# ---------------------------------------------------------------------------
# DADOS
# ---------------------------------------------------------------------------
def salvar_excel(df: pd.DataFrame, caminho: str, tentativas: int = 5, espera: float = 3.0) -> bool:
    """Salva o DataFrame em xlsx com retries. Não derruba o bot se o arquivo
    estiver aberto no Excel (comum causar OSError/[Errno 22] nesse caso).

    Grava primeiro num arquivo temporário e só troca pelo definitivo com
    os.replace (atômico no Windows) — assim uma queda/crash no meio da
    gravação nunca deixa o xlsx principal corrompido pela metade."""
    _raiz, _ext = os.path.splitext(caminho)
    tmp = f"{_raiz}.tmp{_ext}"
    for tentativa in range(1, tentativas + 1):
        try:
            df.to_excel(tmp, index=False)
            os.replace(tmp, caminho)
            return True
        except (PermissionError, OSError) as e:
            logger.warning(f"Falha ao salvar '{caminho}' (tentativa {tentativa}/{tentativas}): {e}")
            if tentativa < tentativas:
                time.sleep(espera)

    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass

    msg = f"Não consegui salvar '{caminho}' — feche o arquivo se estiver aberto no Excel. Progresso mantido em memória."
    logger.error(msg)
    _status_queue.put({"type": "log", "msg": f"AVISO: {msg}"})
    return False


def carregar_dados() -> pd.DataFrame:
    if os.path.exists(ARQUIVO_SAIDA):
        print(f"Retomando: lendo '{ARQUIVO_SAIDA}' ...")
        df = pd.read_excel(ARQUIVO_SAIDA, dtype=str)
        pendentes = df["Tem_Emprestimo"].isna() | (df["Tem_Emprestimo"].str.strip() == "")
        print(f"  {len(df)} registros | {pendentes.sum()} pendentes.\n")
        return df

    print(f"Lendo '{ARQUIVO_ENTRADA}' ...")
    df = pd.read_csv(ARQUIVO_ENTRADA, sep=None, engine="python", dtype=str, encoding="utf-8-sig")
    df.columns = [c.strip().upper() for c in df.columns]
    coluna_cpf = next((c for c in df.columns if "CPF" in c), None)
    if coluna_cpf is None:
        raise ValueError("Coluna CPF não encontrada: " + str(df.columns.tolist()))
    df.rename(columns={coluna_cpf: "CPF/CNPJ"}, inplace=True)
    df["Tem_Emprestimo"] = ""
    print(f"  {len(df)} registros.\n")
    return df


# ---------------------------------------------------------------------------
# FORMULÁRIO
# ---------------------------------------------------------------------------
def aguardar_formulario(page):
    for tentativa in range(4):
        try:
            # 1. Se já está visível o campo "Nome PF ou Sócio", já estamos no formulário de simulação!
            lbl_nome = page.locator('label').filter(has_text="Nome")
            if lbl_nome.count() > 0 and lbl_nome.first.is_visible():
                return

            # 2. Se estiver na tela inicial do portal com o card "Ver produtos" / "O produto ideal está aqui", clica nele
            card_btn = page.locator(':has-text("Ver produtos")').filter(has_text="Ver produtos").last
            if card_btn.count() > 0 and card_btn.is_visible():
                try:
                    card_btn.click()
                    time.sleep(1.5)
                except Exception:
                    pass
                if page.locator('label').filter(has_text="Nome").count() > 0:
                    return

            page.wait_for_selector('label:has-text("Nome")', timeout=6_000)
            if page.locator('label').filter(has_text="Nome").count() > 0:
                return
        except PlaywrightTimeoutError:
            pass
        except Exception:
            pass
        if tentativa < 3:
            time.sleep(2)
    raise PlaywrightTimeoutError("Formulário não encontrado após tentativas")

def preencher_formulario(page, nome: str, cpf: str, telefone: str):
    aguardar_formulario(page)
    _pausa()
    _digitar(page.get_by_label("Nome PF ou Sócio"), nome)
    _pausa()
    _digitar(page.get_by_label("CPF ou CNPJ"), cpf)
    _pausa()
    _digitar(page.get_by_label("DDD + Celular"), telefone)
    _pausa()
    page.locator('button:has-text("Ver produtos")').click()


# ---------------------------------------------------------------------------
# AUTOMAÇÃO
# ---------------------------------------------------------------------------
def clicar_simular_consignado(page):
    page.wait_for_selector('text=Vitrine de produtos', timeout=TIMEOUT)
    _pausa()

    if page.locator('text=Produto não disponível').count() > 0:
        for t in ["Cancelar", "Não", "Fechar", "Ok"]:
            try:
                b = page.locator(f'button:has-text("{t}")')
                if b.count() > 0 and b.first.is_visible():
                    b.first.click(timeout=2000)
                    time.sleep(1.0)
                    try:
                        sim = page.locator('button:has-text("Sim")')
                        if sim.count() > 0 and sim.first.is_visible():
                            sim.first.click(timeout=2000)
                            time.sleep(0.5)
                    except Exception:
                        pass
                    break
            except Exception:
                pass
        raise Exception("não disponível")

    clicou = False
    try:
        card = page.locator(':has-text("Consignado")').last
        btn = card.locator('button:has-text("Simular")')
        if btn.count() > 0:
            btn.first.click()
            clicou = True
    except Exception:
        pass

    if not clicou:
        page.locator('button:has-text("Simular")').first.click()

    _pausa()

    time.sleep(1)
    for extra in page.context.pages:
        if extra is not page:
            try:
                extra.close()
            except Exception:
                pass

    if "consorcio" in page.url.lower():
        page.go_back()
        raise Exception("consórcio — pulando")


def fechar_modais(page):
    try:
        if page.locator('text=cancelar sua oferta').count() > 0:
            sim = page.locator('button:has-text("Sim")')
            if sim.count() > 0 and sim.first.is_visible():
                sim.first.click(timeout=2000)
                _pausa(0.4, 0.7)
                return
    except Exception:
        pass
    for texto in ["Continuar sem consultar", "Continuar", "Fechar", "Ok", "OK", "Entendi"]:
        try:
            btn = page.locator(f'button:has-text("{texto}")')
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                _pausa(0.4, 0.7)
                return
        except Exception:
            pass


def verificar_refinanciamento(page) -> str:
    page.wait_for_selector('text=Simulação de empréstimo consignado', timeout=TIMEOUT)
    _pausa()
    try:
        page.wait_for_selector('text=Simular Refinanciamento', timeout=2500)
        return "Sim"
    except PlaywrightTimeoutError:
        return "Não"


def _confirmar_cancelamento(page):
    try:
        if page.locator('text=cancelar sua oferta').count() > 0:
            sim = page.locator('button:has-text("Sim")')
            if sim.count() > 0 and sim.first.is_visible():
                sim.first.click(timeout=2000)
                time.sleep(0.5)
    except Exception:
        pass


def _no_formulario(page) -> bool:
    try:
        lbl_nome = page.locator('label').filter(has_text="Nome")
        return lbl_nome.count() > 0 and lbl_nome.first.is_visible()
    except Exception:
        return False

def voltar_ao_formulario(page):
    _verificar_acesso_santander(page.context)
    if sessao_expirada(page):
        return
    _confirmar_cancelamento(page)
    if _no_formulario(page):
        return
    for _ in range(4):
        try:
            page.go_back(wait_until="domcontentloaded", timeout=5000)
        except PlaywrightError:
            break
        _verificar_acesso_santander(page.context)
        if sessao_expirada(page):
            return
        time.sleep(0.8)
        _confirmar_cancelamento(page)
        if _no_formulario(page):
            return
    _verificar_acesso_santander(page.context)
    if sessao_expirada(page):
        return
    if not _no_formulario(page):
        try:
            page.goto(URL_FORMULARIO, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(1.5)
        except Exception:
            pass
        _verificar_acesso_santander(page.context)


def _fechar_abas_extras(ctx, page_principal):
    """Fecha todas as abas que não sejam a página principal nem o login."""
    for p in list(ctx.pages):
        if p is page_principal:
            continue
        try:
            url = p.url.lower()
            # Mantém aba de login aberta (bot precisa dela pra auto-login)
            if any(k in url for k in ["openid", "/login", "corp/protocol", "keycloak", "/auth?"]):
                continue
            p.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LOOP PRINCIPAL
# ---------------------------------------------------------------------------
def processar_clientes(page, df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    processados_no_burst = 0
    proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

    # Prioriza a leva de clientes nunca tentados (após o último já processado)
    # antes de voltar para os poucos "buracos" espalhados no meio do que já foi feito
    # (clientes que ficaram pendentes por sessão expirada/erro em execuções anteriores).
    _col = df["Tem_Emprestimo"]
    _status = _col.astype(str).str.strip()
    _pendente = _col.isna() | (_status == "") | (_status == "Erro")
    _feitos_idx = df.index[~_pendente]
    _ultimo_feito = _feitos_idx.max() if len(_feitos_idx) else -1
    _pend_idx = df.index[_pendente].tolist()
    ordem = [i for i in _pend_idx if i > _ultimo_feito] + [i for i in _pend_idx if i <= _ultimo_feito]

    for idx in ordem:
        linha = df.loc[idx]
        if _stop_event.is_set():
            logger.info("Bot parado pelo usuário.")
            print("\nBot parado.")
            break

        ja_feito = str(df.at[idx, "Tem_Emprestimo"]).strip()
        if ja_feito and ja_feito != "nan" and ja_feito != "Erro":
            continue

        nome    = extrair_nome_linha(linha)
        cpf_raw = str(linha.get("CPF/CNPJ", "")).strip()

        # CPF pode ter 14 dígitos nesta planilha (CPF preenchido com zeros à esquerda)
        _cpf_digits = "".join(ch for ch in cpf_raw if ch.isdigit())
        if len(_cpf_digits) > 11:
            _stripped = _cpf_digits.lstrip("0")
            cpf = _stripped.zfill(11) if len(_stripped) <= 11 else _stripped
        else:
            cpf = _cpf_digits.zfill(11)

        if len(cpf) != 11:
            df.at[idx, "Tem_Emprestimo"] = "CPF Inválido"
            salvar_excel(df, ARQUIVO_SAIDA)
            print(f"[{idx+1}/{total}] CPF inválido, pulando.")
            continue

        telefone = extrair_telefone_linha(linha)
        if not telefone:
            df.at[idx, "Tem_Emprestimo"] = "Telefone Inválido"
            salvar_excel(df, ARQUIVO_SAIDA)
            print(f"[{idx+1}/{total}] Telefone ausente/inválido, pulando.")
            logger.warning(f"[{idx+1}/{total}] {nome} CPF: {cpf} - Telefone inválido")
            continue

        fone_fmt = formatar_telefone_visual(telefone)
        print(f"[{idx+1}/{total}] {nome[:24]:<24} CPF: {cpf} Tel: {fone_fmt} ...", end=" ", flush=True)
        logger.info(f"[{idx+1}/{total}] {nome} CPF: {cpf} Tel: {fone_fmt}")

        _verificar_acesso_santander(page.context)
        if sessao_expirada(page):
            nova = aguardar_relogin(page)
            if nova is None:
                break
            page = nova
            processados_no_burst = 0
            proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

        _fechar_abas_extras(page.context, page)

        # Pausa entre clientes
        time.sleep(random.uniform(4.0, 7.0))

        status = "Erro"
        for tentativa in range(2):
            _verificar_acesso_santander(page.context)
            try:
                preencher_formulario(page, nome, cpf, telefone)
                clicar_simular_consignado(page)
                fechar_modais(page)
                status = verificar_refinanciamento(page)
                _verificar_acesso_santander(page.context)
                print(status)
                logger.info(f"  → {status}")
                break

            except AcessoSantanderNegado:
                raise
            except PlaywrightTimeoutError as e:
                _verificar_acesso_santander(page.context)
                msg = str(e).splitlines()[0][:60]
                logger.warning(f"  TIMEOUT t{tentativa+1} [{idx+1}]: {msg}")
                if tentativa == 0:
                    print("timeout, retry...", end=" ", flush=True)
                    if sessao_expirada(page):
                        nova = aguardar_relogin(page)
                        if nova is None:
                            return df
                        page = nova
                        processados_no_burst = 0
                    else:
                        time.sleep(2)
                else:
                    print("TIMEOUT")
                    status = "Erro"

            except Exception as e:
                _verificar_acesso_santander(page.context)
                msg = str(e)
                logger.warning(f"  ERRO t{tentativa+1} [{idx+1}]: {msg}")
                if "não disponível" in msg.lower() or "consórcio" in msg.lower():
                    print("Não disponível")
                    status = "Não"
                    break
                if tentativa == 0:
                    print("erro, retry...", end=" ", flush=True)
                    if sessao_expirada(page):
                        nova = aguardar_relogin(page)
                        if nova is None:
                            return df
                        page = nova
                        processados_no_burst = 0
                    else:
                        time.sleep(2)
                else:
                    print("ERRO")
                    status = "Erro"

        df.at[idx, "Tem_Emprestimo"] = status
        salvar_excel(df, ARQUIVO_SAIDA)
        df_sim = df[df["Tem_Emprestimo"] == "Sim"]
        if not df_sim.empty:
            salvar_excel(df_sim, "com_refinanciamento.xlsx")

        # Envia progresso para a GUI
        _status_queue.put({
            "type":   "progress",
            "idx":    idx + 1,
            "total":  total,
            "nome":   nome,
            "cpf":    cpf,
            "fone":   fone_fmt,
            "status": status,
            "sim":    int((df["Tem_Emprestimo"] == "Sim").sum()),
            "nao":    int((df["Tem_Emprestimo"] == "Não").sum()),
            "erros":  int(df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido", "Telefone Inválido"]).sum()),
        })

        voltar_ao_formulario(page)
        processados_no_burst += 1

        # Micro-pausa a cada N clientes (break rápido, não prejudica throughput)
        if processados_no_burst >= proximo_descanso:
            duracao = random.uniform(DESCANSO_MIN, DESCANSO_MAX)
            print(f"\n  [micro-pausa {duracao:.0f}s]\n")
            logger.info(f"Micro-pausa {duracao:.0f}s após {processados_no_burst} clientes")
            time.sleep(duracao)
            processados_no_burst = 0
            proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

    return df


# ---------------------------------------------------------------------------
# INICIALIZAÇÃO (interface gráfica e terminal)
# ---------------------------------------------------------------------------
def _executar_no_portal(df):
    _status_queue.put({"type": "log", "msg": "Abrindo Brave..."})
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=PERFIL_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            locale="pt-BR",
            no_viewport=True,
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            _abrir_portal(page)
            _status_queue.put({"type": "aguardando_login"})
            print(_ORIENTACAO_LOGIN, flush=True)

            page = _aguardar_formulario_autenticado(ctx)
            if page is None:
                return None

            _status_queue.put({"type": "rodando"})
            return processar_clientes(page, df)
        finally:
            ctx.close()


def main_gui():
    """Executa o bot em segundo plano e envia o progresso para a interface."""
    df = carregar_dados()

    # Envia contagens iniciais do arquivo já existente
    sim0   = int((df["Tem_Emprestimo"] == "Sim").sum())
    nao0   = int((df["Tem_Emprestimo"] == "Não").sum())
    erros0 = int(df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido"]).sum())
    feitos0 = sim0 + nao0 + erros0
    _status_queue.put({
        "type": "init_stats",
        "total":  len(df),
        "feitos": feitos0,
        "sim":    sim0,
        "nao":    nao0,
        "erros":  erros0,
    })

    df = _executar_no_portal(df)
    if df is None:
        return

    salvar_excel(df, ARQUIVO_SAIDA)
    sim   = (df["Tem_Emprestimo"] == "Sim").sum()
    nao   = (df["Tem_Emprestimo"] == "Não").sum()
    erros = df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido"]).sum()
    _status_queue.put({"type": "log",
                       "msg": f"Concluído! Sim={sim} | Não={nao} | Erros={erros}"})


# ---------------------------------------------------------------------------
# MAIN (terminal)
# ---------------------------------------------------------------------------
def main():
    df = carregar_dados()
    try:
        df = _executar_no_portal(df)
    except AcessoSantanderNegado as e:
        raise SystemExit(str(e)) from None
    if df is None:
        return

    salvar_excel(df, ARQUIVO_SAIDA)
    print(f"\nConcluído! Salvo em '{ARQUIVO_SAIDA}'.")

    df_sim = df[df["Tem_Emprestimo"] == "Sim"].copy()
    if not df_sim.empty:
        salvar_excel(df_sim, "com_refinanciamento.xlsx")
        print(f"Com refinanciamento: {len(df_sim)} clientes.")

    sim   = (df["Tem_Emprestimo"] == "Sim").sum()
    nao   = (df["Tem_Emprestimo"] == "Não").sum()
    erros = df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido"]).sum()
    print(f"\nResumo: Sim={sim} | Não={nao} | Erros={erros}")


if __name__ == "__main__":
    main()
