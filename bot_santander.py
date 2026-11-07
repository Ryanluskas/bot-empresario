"""
RPA - Parceiro Santander | Simulação de Crédito Consignado
"""

import os
import time
import random
import logging
import pandas as pd

import threading
import queue as _queue_mod

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import security_config

try:
    from playwright_stealth import stealth_sync
    _STEALTH_LIB = True
except ImportError:
    _STEALTH_LIB = False

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
ARQUIVO_ENTRADA = "clientes.csv"
ARQUIVO_SAIDA   = "resultado_filtrado.xlsx"
URL_FORMULARIO  = "https://www.parceirosantander.com.br/spa-base/logged-area/recommendation/"
URL_LANDING     = "https://www.parceirosantander.com.br/spa-base/landing-page"
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
CPF_ACESSO, SENHA_ACESSO = security_config.load_credentials()
# Credenciais isoladas via security_config (sem segredos em texto puro)

# Pausa rápida a cada N clientes (simula humano virando a página, não dorme)
BURST_MIN    = 8
BURST_MAX    = 12
DESCANSO_MIN = 45    # segundos
DESCANSO_MAX = 70    # segundos

# JS de stealth injetado em cada nova página — esconde todos os sinais de automação
STEALTH_JS = """
// Webdriver flag
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Chrome APIs completas (Brave expõe window.chrome mas pode estar incompleto via CDP)
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};
const _rt = window.chrome.runtime;
if (!_rt.connect)       _rt.connect       = function(){return {onDisconnect:{addListener:function(){}},postMessage:function(){}}};
if (!_rt.sendMessage)   _rt.sendMessage   = function(){};
if (!_rt.getManifest)   _rt.getManifest   = function(){return {}};
if (!_rt.onConnect)     _rt.onConnect     = {addListener:function(){}};
if (!_rt.onMessage)     _rt.onMessage     = {addListener:function(){}};
if (!window.chrome.loadTimes) window.chrome.loadTimes = function(){return null};
if (!window.chrome.csi) window.chrome.csi = function(){return {startE:Date.now(),onloadT:Date.now(),pageT:1,tran:15}};
if (!window.chrome.app) window.chrome.app = {isInstalled:false,getDetails:function(){return null},getIsInstalled:function(){return false}};

// Remove rastros do CDP (Chromium DevTools Protocol)
try { ['cdc_adoQpoasnfa76pfcZLmcfl_Array','cdc_adoQpoasnfa76pfcZLmcfl_Promise',
       'cdc_adoQpoasnfa76pfcZLmcfl_Symbol','__playwright','__pw_manual','__webdriver_script_fn',
       'domAutomation','domAutomationController','_phantom','callPhantom',
       '_selenium','__driver_evaluate','__webdriver_evaluate','__selenium_evaluate',
       '__fxdriver_evaluate','__driver_unwrapped','__webdriver_unwrapped',
       '__selenium_unwrapped','__fxdriver_unwrapped'].forEach(k=>{try{delete window[k]}catch(e){}});
} catch(e) {}

// Permissions API (Brave normalmente ok, mas cobre o caso de CDP resetar)
try {
    const _origPQ = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.__proto__.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission, onchange: null})
            : _origPQ(p);
} catch(e) {}

// Navigator properties realistas
const _def = (obj, prop, val) => {
    try { Object.defineProperty(obj, prop, {get: ()=>val, configurable:true}); } catch(e) {}
};
_def(navigator, 'languages',         ['pt-BR','pt','en-US','en']);
_def(navigator, 'hardwareConcurrency', 8);
_def(navigator, 'platform',           'Win32');
_def(navigator, 'deviceMemory',       8);
_def(navigator, 'maxTouchPoints',     0);
_def(navigator, 'vendor',            'Google Inc.');
_def(navigator, 'appVersion',        '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Brave/136');

// Plugins não-vazios (browser real tem plugins)
try {
    const pdf = {type:'application/pdf',description:'Portable Document Format',suffixes:'pdf'};
    const plug = {name:'Chrome PDF Plugin',description:'Portable Document Format',filename:'internal-pdf-viewer',length:1,0:pdf,item:i=>plug[i],namedItem:()=>null};
    pdf.enabledPlugin = plug;
    Object.defineProperty(navigator, 'plugins', {get:()=>{
        const a = [plug]; a.item=i=>a[i]; a.namedItem=n=>a.find(p=>p.name===n)||null; a.refresh=()=>{};
        return a;
    }, configurable:true});
} catch(e) {}
"""

# ---------------------------------------------------------------------------
# CANAIS GUI (usados pela interface gráfica; no modo terminal ficam ociosos)
# ---------------------------------------------------------------------------
_stop_event   = threading.Event()   # GUI seta para parar o bot
_start_event  = threading.Event()   # GUI seta quando login estiver pronto
_otp_queue    = _queue_mod.Queue()  # GUI envia o código OTP aqui
_status_queue = _queue_mod.Queue()  # Bot envia progresso/status para a GUI

# Keepalive de sessão
_ultimo_keepalive = 0.0

logging.basicConfig(
    filename="bot_log.txt",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# STEALTH
# ---------------------------------------------------------------------------
def _aplicar_stealth(page):
    """Aplica playwright-stealth + JS extra em uma página."""
    try:
        if _STEALTH_LIB:
            stealth_sync(page)
    except Exception:
        pass
    try:
        page.add_init_script(STEALTH_JS)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _pausa(a=0.4, b=0.9):
    time.sleep(random.uniform(a, b))


def _mover_mouse(page):
    """Move o mouse para posição aleatória — gera dados de movimento para o Akamai."""
    try:
        page.mouse.move(
            random.randint(180, 1050),
            random.randint(120, 660),
        )
    except Exception:
        pass


def _keepalive(page):
    """Faz uma requisição silenciosa para manter a sessão viva (a cada 4 min)."""
    global _ultimo_keepalive
    agora = time.time()
    if agora - _ultimo_keepalive > 90:
        try:
            page.evaluate("fetch(window.location.href, {method:'HEAD'}).catch(()=>{})")
        except Exception:
            pass
        _ultimo_keepalive = agora


def _digitar(locator, texto: str):
    """Digita com velocidade de digitador rápido — gera eventos de teclado reais."""
    try:
        locator.click()
        locator.fill("")
        locator.type(texto, delay=random.randint(38, 72))
    except Exception:
        locator.fill(texto)


# ---------------------------------------------------------------------------
# SESSÃO / URL
# ---------------------------------------------------------------------------
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
            url = _url_real(p).lower()
            if "recommendation" in url and "landing" not in url and "login" not in url and "logout" not in url:
                return p
        except Exception:
            continue
    return None


def _achar_pagina_login(ctx):
    """Retorna a aba de login (openid-connect / keycloak / /login)."""
    for p in ctx.pages:
        try:
            url = p.url.lower()
            if any(k in url for k in ["openid", "/login", "corp/protocol", "keycloak", "/auth?"]):
                return p
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# AUTO-LOGIN
# ---------------------------------------------------------------------------
def _preencher_input_angular(page, seletores: list, valor: str) -> bool:
    """Preenche input Angular via fill + disparo de eventos nativos como fallback."""
    for sel in seletores:
        try:
            loc = page.locator(sel).first
            loc.click(force=True, timeout=2000)
            time.sleep(0.2)
            loc.fill(valor, force=True)
            page.evaluate(f"""
                const el = document.querySelector('{sel}');
                if (el) {{
                    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    s.call(el, {repr(valor)});
                    el.dispatchEvent(new Event('input',  {{bubbles:true}}));
                    el.dispatchEvent(new Event('change', {{bubbles:true}}));
                    el.dispatchEvent(new Event('blur',   {{bubbles:true}}));
                }}
            """)
            return True
        except Exception:
            pass
    return False


def _clicar_acessar_portal(page) -> bool:
    """Clica no botão Acessar o Portal. Retorna True se clicou."""
    for sel in [
        'button:has-text("Acessar o Portal")',
        'a:has-text("Acessar o Portal")',
        ':has-text("Acessar o Portal")',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click()
                return True
        except Exception:
            pass
    return False


def tentar_login_automatico(page) -> bool:
    """
    Tenta login automático em duas fases:
    1. SSO silencioso — se Keycloak ainda tem sessão válida, reconecta em 2-3s sem preencher nada
    2. Preenchimento CPF+senha — se SSO não funcionar
    """
    ctx = page.context

    # --- Fase 1: SSO silencioso ---
    # Clica "Acessar o Portal" e aguarda 8s para SSO redirecionar automaticamente
    try:
        for t in ["Continuar", "Fechar", "Ok", "Entendi", "Aceitar"]:
            try:
                b = page.locator(f'button:has-text("{t}")')
                if b.count() > 0 and b.first.is_visible(timeout=200):
                    b.first.click()
            except Exception:
                pass

        _clicar_acessar_portal(page)

        for _ in range(16):   # aguarda até 8s por SSO
            time.sleep(0.5)
            if _encontrar_pagina_formulario(ctx) is not None:
                logger.info("Auto-login: SSO silencioso OK")
                print("  Auto-login: SSO OK!\n", flush=True)
                return True

        logger.info("Auto-login: SSO não funcionou, tentando CPF+senha")
    except Exception as e:
        logger.warning(f"Auto-login fase SSO: {e}")

    # --- Fase 2: preenche CPF + senha na aba de login ---
    try:
        lp = _achar_pagina_login(ctx)
        if lp is None:
            lp = page

        logger.info(f"Auto-login: preenchendo form em {lp.url[:80]}")
        _aplicar_stealth(lp)

        try:
            lp.wait_for_selector('input', timeout=8000)
        except Exception:
            return False
        time.sleep(0.8)

        try:
            lp.keyboard.press("Escape")
            time.sleep(0.2)
        except Exception:
            pass

        # --- Preenche CPF via Shadow DOM (campo id="inputUser") ---
        cpf_ok = False

        # Tenta direto pelo id (fora do shadow root ou shadow open)
        for sel in ['input#inputUser', 'input[id="inputUser"]', 'input[type="text"]']:
            try:
                loc = lp.locator(sel).first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    time.sleep(0.15)
                    loc.fill(CPF_ACESSO)
                    cpf_ok = True
                    break
            except Exception:
                pass

        # Fallback: injeta via JS percorrendo todos os shadow roots da página
        if not cpf_ok:
            try:
                result = lp.evaluate(f"""
                    (function() {{
                        function findInShadow(root, id) {{
                            const el = root.querySelector && root.querySelector('#' + id);
                            if (el) return el;
                            const all = root.querySelectorAll && root.querySelectorAll('*');
                            if (!all) return null;
                            for (const node of all) {{
                                if (node.shadowRoot) {{
                                    const found = findInShadow(node.shadowRoot, id);
                                    if (found) return found;
                                }}
                            }}
                            return null;
                        }}
                        const el = findInShadow(document, 'inputUser');
                        if (!el) return false;
                        el.focus();
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, {repr(CPF_ACESSO)});
                        el.dispatchEvent(new Event('input',  {{bubbles:true}}));
                        el.dispatchEvent(new Event('change', {{bubbles:true}}));
                        el.dispatchEvent(new Event('blur',   {{bubbles:true}}));
                        return true;
                    }})()
                """)
                cpf_ok = bool(result)
            except Exception:
                pass

        if not cpf_ok:
            logger.warning("Auto-login: campo CPF não encontrado")
            return False

        time.sleep(0.5)

        # --- Preenche Senha ---
        senha_ok = False
        for sel in ['input[type="password"]', 'input[id*="senha"]',
                    'input[name*="senha"]', 'input[formcontrolname*="senha"]',
                    'input[formcontrolname*="password"]']:
            try:
                loc = lp.locator(sel).first
                if loc.is_visible(timeout=2000):
                    loc.click(force=True)
                    time.sleep(0.15)
                    loc.fill(SENHA_ACESSO)
                    senha_ok = True
                    break
            except Exception:
                pass

        if not senha_ok:
            # Fallback shadow DOM para senha
            try:
                result = lp.evaluate(f"""
                    (function() {{
                        function findInShadow(root, type) {{
                            const el = root.querySelector && root.querySelector('input[type="' + type + '"]');
                            if (el) return el;
                            const all = root.querySelectorAll && root.querySelectorAll('*');
                            if (!all) return null;
                            for (const node of all) {{
                                if (node.shadowRoot) {{
                                    const found = findInShadow(node.shadowRoot, type);
                                    if (found) return found;
                                }}
                            }}
                            return null;
                        }}
                        const el = findInShadow(document, 'password');
                        if (!el) return false;
                        el.focus();
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(el, {repr(SENHA_ACESSO)});
                        el.dispatchEvent(new Event('input',  {{bubbles:true}}));
                        el.dispatchEvent(new Event('change', {{bubbles:true}}));
                        el.dispatchEvent(new Event('blur',   {{bubbles:true}}));
                        return true;
                    }})()
                """)
                senha_ok = bool(result)
            except Exception:
                pass

        if not senha_ok:
            logger.warning("Auto-login: campo senha não encontrado")
            return False

        time.sleep(0.5)

        for sel in ['button[type="submit"]', 'button:has-text("Entrar")',
                    'button:has-text("Acessar")', 'button:has-text("Login")',
                    'input[type="submit"]']:
            try:
                b = lp.locator(sel).first
                if b.is_visible(timeout=800):
                    b.click()
                    break
            except Exception:
                pass

        print("  Auto-login: aguardando resposta...", flush=True)
        otp_avisado = False
        for seg in range(90):
            time.sleep(1)
            if _encontrar_pagina_formulario(ctx) is not None:
                logger.info("Auto-login: CPF+senha OK")
                print("  Auto-login: OK!\n", flush=True)
                _status_queue.put({"type": "login_ok"})
                return True

            # Detecta tela de OTP
            if not otp_avisado:
                try:
                    for p2 in ctx.pages:
                        if p2.locator('input[maxlength="1"]').count() >= 4:
                            otp_avisado = True
                            _status_queue.put({"type": "otp_needed"})
                            print("\n  CÓDIGO OTP necessário — digite na interface ou no Brave!\n")
                            try:
                                import winsound
                                for _ in range(3):
                                    winsound.Beep(1000, 400)
                                    time.sleep(0.15)
                            except Exception:
                                pass
                            break
                except Exception:
                    pass

            # Tenta pegar OTP da fila (enviado pela GUI)
            try:
                otp_code = _otp_queue.get_nowait()
                for p2 in ctx.pages:
                    try:
                        inputs1 = p2.locator('input[maxlength="1"]')
                        inputs6 = p2.locator('input[maxlength="6"]')
                        if inputs1.count() >= 4:
                            for i, ch in enumerate(otp_code[:inputs1.count()]):
                                inputs1.nth(i).fill(ch)
                        elif inputs6.count() > 0:
                            inputs6.first.fill(otp_code)
                        # Tenta submeter
                        for sel in ['button[type="submit"]', 'button:has-text("Confirmar")',
                                    'button:has-text("Verificar")', 'button:has-text("Entrar")']:
                            b = p2.locator(sel).first
                            if b.is_visible(timeout=500):
                                b.click()
                                break
                        break
                    except Exception:
                        pass
            except _queue_mod.Empty:
                pass

            if seg % 20 == 19:
                print(f"  Aguardando login... ({90-seg-1}s)", flush=True)

        return False

    except Exception as e:
        logger.warning(f"Auto-login fase CPF: {e}")
        return False


def aguardar_relogin(page):
    """Tenta auto-login; se falhar aguarda login manual."""
    ctx = page.context

    found = _encontrar_pagina_formulario(ctx)
    if found is not None:
        return found

    logger.warning(f"Sessão expirada. URL: {_url_real(page)}")
    _status_queue.put({"type": "sessao_expirada"})
    print(f"\n{'='*50}")
    print("  SESSÃO EXPIRADA — tentando login automático...")
    print(f"{'='*50}\n")

    try:
        if "landing" not in _url_real(page).lower():
            page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(2)
    except Exception:
        pass

    if tentar_login_automatico(page):
        found = _encontrar_pagina_formulario(ctx)
        if found is not None:
            return found

    print(f"\n{'='*50}")
    print("  Auto-login falhou. Faça login manualmente no Brave.")
    print(f"{'='*50}\n")

    for segundo in range(7200):
        if segundo % 5 == 0:
            found = _encontrar_pagina_formulario(ctx)
            if found is not None:
                print("  Formulário detectado! Continuando...\n")
                logger.info("Sessão recuperada manualmente.")
                return found

        if segundo > 0 and segundo % 300 == 0:
            try:
                page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
                time.sleep(2)
                if tentar_login_automatico(page):
                    found = _encontrar_pagina_formulario(ctx)
                    if found is not None:
                        return found
            except Exception:
                pass

        time.sleep(1)

    return None


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
        # 1. Verifica se já está no formulário (label Nome aparece)
        try:
            if page.locator('label').filter(has_text="Nome").count() > 0:
                return
        except Exception:
            pass

        # 2. Verifica se está na tela inicial logada com o botão/link "Ver produtos" e sem o formulário
        try:
            ver_produtos = page.locator('text="Ver produtos"')
            if ver_produtos.count() > 0 and ver_produtos.first.is_visible(timeout=2000):
                ver_produtos.first.click()
                time.sleep(1.5)
                if page.locator('label').filter(has_text="Nome").count() > 0:
                    return
        except Exception:
            pass

        # 3. Se não achou nenhum de imediato, aguarda o form carregar
        try:
            page.wait_for_selector('label:has-text("Nome")', timeout=8000)
            return
        except PlaywrightTimeoutError:
            pass
            
        time.sleep(2)
        
    raise PlaywrightTimeoutError("Formulário não encontrado após 3 tentativas")


def preencher_formulario(page, nome: str, cpf: str, telefone: str):
    aguardar_formulario(page)
    _pausa()
    _mover_mouse(page)
    _digitar(page.get_by_label("Nome PF ou Sócio"), nome)
    _pausa()
    _mover_mouse(page)
    _digitar(page.get_by_label("CPF ou CNPJ"), cpf)
    _pausa()
    _mover_mouse(page)
    _digitar(page.get_by_label("DDD + Celular"), telefone)
    _pausa()
    page.locator('button:has-text("Ver produtos")').click()


# ---------------------------------------------------------------------------
# AUTOMAÇÃO
# ---------------------------------------------------------------------------
def clicar_simular_consignado(page):
    page.wait_for_selector('text=Vitrine de produtos', timeout=TIMEOUT)
    _mover_mouse(page)
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
    _mover_mouse(page)
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
        return page.locator('label').filter(has_text="Nome").is_visible()
    except Exception:
        return False


def voltar_ao_formulario(page):
    _confirmar_cancelamento(page)
    if _no_formulario(page):
        return
    for _ in range(4):
        try:
            page.go_back(wait_until="domcontentloaded", timeout=5000)
            
            # Espera inteligente ao invés de sleep fixo de 0.8s
            try:
                page.wait_for_selector('button:has-text("Ver produtos")', timeout=1200)
            except Exception:
                pass
                
            _confirmar_cancelamento(page)
            if _no_formulario(page):
                return
        except Exception:
            break
    if not _no_formulario(page):
        try:
            page.goto(URL_FORMULARIO, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(1.5)
        except Exception:
            pass


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

        nome    = str(linha.get("NOME", "Lead")).strip() or "Lead"
        cpf_raw = str(linha.get("CPF/CNPJ", "")).strip()
        ddd     = str(linha.get("DDD", "")).strip()
        fone    = str(linha.get("FONE", "")).strip()

        # CPF pode ter 14 dígitos nesta planilha (CPF preenchido com zeros à esquerda)
        _cpf_digits = "".join(ch for ch in cpf_raw if ch.isdigit())
        if len(_cpf_digits) > 11:
            _stripped = _cpf_digits.lstrip("0")
            cpf = _stripped.zfill(11) if len(_stripped) <= 11 else _stripped
        else:
            cpf = _cpf_digits.zfill(11)

        # Busca melhor telefone: prioriza celular com WhatsApp em múltiplas colunas
        telefone = None
        for _i in range(8):
            _sfx = "" if _i == 0 else f".{_i}"
            _d = str(linha.get(f"DDD{_sfx}", "")).strip()
            _f = str(linha.get(f"FONE{_sfx}", "")).strip()
            _w = str(linha.get(f"POSSUI-WHATSAPP{_sfx}", "0")).strip()
            if _d and _f and _d != "nan" and _f != "nan":
                _comb = "".join(ch for ch in (_d + _f) if ch.isdigit())
                if len(_comb) == 11 and _comb[2] == "9":
                    if _w == "1":
                        telefone = _comb
                        break
                    if telefone is None:
                        telefone = _comb
        if telefone is None:
            _ddd2 = "".join(ch for ch in ddd if ch.isdigit())[:2].zfill(2)
            telefone = _ddd2 + "999999999"

        if len(cpf) != 11:
            df.at[idx, "Tem_Emprestimo"] = "CPF Inválido"
            salvar_excel(df, ARQUIVO_SAIDA)
            print(f"[{idx+1}/{total}] CPF inválido, pulando.")
            continue

        cpf_mascarado = security_config.mask_cpf(cpf)
        print(f"[{idx+1}/{total}] {nome[:28]:<28} CPF: {cpf_mascarado} ...", end=" ", flush=True)
        logger.info(f"[{idx+1}/{total}] {nome} CPF: {cpf_mascarado}")

        _keepalive(page)
        _fechar_abas_extras(page.context, page)

        if sessao_expirada(page):
            nova = aguardar_relogin(page)
            if nova is None:
                break
            page = nova
            processados_no_burst = 0
            proximo_descanso = random.randint(BURST_MIN, BURST_MAX)

        # Pausa entre clientes (reduzida de 4-7s para 1.5-2.5s, mantendo aleatoriedade)
        time.sleep(random.uniform(1.5, 2.5))

        status = "Erro"
        for tentativa in range(2):
            try:
                preencher_formulario(page, nome, cpf, telefone)
                clicar_simular_consignado(page)
                fechar_modais(page)
                status = verificar_refinanciamento(page)
                print(status)
                logger.info(f"  → {status}")
                break

            except PlaywrightTimeoutError as e:
                msg = str(e).splitlines()[0][:60]
                logger.warning(f"  TIMEOUT t{tentativa+1} [{idx+1}]: {msg}")
                if tentativa == 0:
                    print("timeout, retry...", end=" ", flush=True)
                    if sessao_expirada(page):
                        nova = aguardar_relogin(page)
                        if nova is None:
                            status = "Erro"
                            break
                        page = nova
                        processados_no_burst = 0
                    else:
                        time.sleep(2)
                else:
                    print("TIMEOUT")
                    status = "Erro"

            except Exception as e:
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
                            status = "Erro"
                            break
                        page = nova
                        processados_no_burst = 0
                    else:
                        time.sleep(2)
                else:
                    print("ERRO")
                    status = "Erro"

        # Salva o Excel a cada 10 clientes para evitar o gargalo gigantesco de I/O
        # (gravar um arquivo de 5MB a cada linha custa ~2 a 3 segundos por cliente)
        df.at[idx, "Tem_Emprestimo"] = status
        
        # Só salva o arquivo principal a cada 10 registros para otimizar
        if processados_no_burst % 10 == 0 or idx == ordem[-1]:
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
            "status": status,
            "sim":    int((df["Tem_Emprestimo"] == "Sim").sum()),
            "nao":    int((df["Tem_Emprestimo"] == "Não").sum()),
            "erros":  int(df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido"]).sum()),
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
# MAIN GUI (chamado pela interface gráfica)
# ---------------------------------------------------------------------------
def main_gui(num_workers: int = 1, coordinator_holder: list = None):
    """Versão sem input() — sincroniza com a GUI via _start_event e _status_queue."""
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

    _status_queue.put({"type": "log", "msg": f"Iniciando Bot com {num_workers} Brave(s)..."})

    from multi_brave import MultiBraveCoordinator
    coord = MultiBraveCoordinator(df, ARQUIVO_SAIDA, _status_queue, _stop_event)
    if coordinator_holder is not None:
        coordinator_holder.append(coord)

    _status_queue.put({"type": "rodando"})
    coord.start(num_workers)
    coord.wait_all()

    sim   = (coord.queue_mgr.df["Tem_Emprestimo"] == "Sim").sum()
    nao   = (coord.queue_mgr.df["Tem_Emprestimo"] == "Não").sum()
    erros = coord.queue_mgr.df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido"]).sum()
    _status_queue.put({"type": "log",
                       "msg": f"Concluído! Sim={sim} | Não={nao} | Erros={erros}"})
    _status_queue.put({"type": "stopped"})
    return


def main_gui_legacy():
    """Modo legado com um único contexto persistente no perfil padrão."""
    df = carregar_dados()
    _status_queue.put({"type": "log", "msg": "Abrindo Brave (legado)..."})

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=PERFIL_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--no-first-run", "--lang=pt-BR",
                  "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Brave/136"
            ),
        )
        ctx.add_init_script(STEALTH_JS)
        ctx.on("page", lambda p: _aplicar_stealth(p))

        # Fecha automaticamente qualquer nova aba que não seja login
        def _auto_fechar_aba(nova_aba):
            _aplicar_stealth(nova_aba)
            def _checar():
                time.sleep(1.5)
                try:
                    url = nova_aba.url.lower()
                    if not any(k in url for k in ["openid", "/login", "corp/protocol",
                                                   "keycloak", "/auth?", "recommendation",
                                                   "parceirosantander", "landing"]):
                        nova_aba.close()
                except Exception:
                    pass
            threading.Thread(target=_checar, daemon=True).start()

        ctx.on("page", _auto_fechar_aba)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _aplicar_stealth(page)

        # Vai para landing page (sempre acessível, sem session_code que expira)
        try:
            page.goto(URL_LANDING, wait_until="domcontentloaded", timeout=15_000)
        except Exception:
            pass

        _status_queue.put({"type": "aguardando_login"})

        # Tenta SSO silencioso imediatamente
        if not _stop_event.is_set():
            tentar_login_automatico(page)

        # Aguarda formulário aparecer (auto-detecta a cada 2s)
        while not _stop_event.is_set():
            found = _encontrar_pagina_formulario(ctx)
            if found is not None:
                page = found
                break
            time.sleep(2)

        if _stop_event.is_set():
            ctx.close()
            return

        _status_queue.put({"type": "rodando"})
        df = processar_clientes(page, df)
        ctx.close()

    salvar_excel(df, ARQUIVO_SAIDA)
    sim   = (df["Tem_Emprestimo"] == "Sim").sum()
    nao   = (df["Tem_Emprestimo"] == "Não").sum()
    erros = df["Tem_Emprestimo"].isin(["Erro", "CPF Inválido"]).sum()
    _status_queue.put({"type": "log",
                       "msg": f"Concluído! Sim={sim} | Não={nao} | Erros={erros}"})
    _status_queue.put({"type": "stopped"})


# ---------------------------------------------------------------------------
# MAIN (terminal)
# ---------------------------------------------------------------------------
def main():
    df = carregar_dados()

    print("Abrindo Brave...")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=PERFIL_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=[
                "--no-first-run",
                "--lang=pt-BR",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 Brave/136"
            ),
        )

        ctx.add_init_script(STEALTH_JS)

        # Aplica stealth em toda nova aba que abrir + fecha abas indesejadas
        ctx.on("page", lambda p: _aplicar_stealth(p))

        def _auto_fechar_aba_terminal(nova_aba):
            def _checar():
                time.sleep(1.5)
                try:
                    url = nova_aba.url.lower()
                    if not any(k in url for k in ["openid", "/login", "corp/protocol",
                                                   "keycloak", "/auth?", "recommendation",
                                                   "parceirosantander", "landing"]):
                        nova_aba.close()
                except Exception:
                    pass
            threading.Thread(target=_checar, daemon=True).start()

        ctx.on("page", _auto_fechar_aba_terminal)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _aplicar_stealth(page)
        page.goto(URL_FORMULARIO)

        print("\nFaça o login no Brave se necessário.")
        print("Quando estiver no formulário (Nome/CPF/Celular), pressione ENTER.")
        input()

        encontrada = _encontrar_pagina_formulario(ctx)
        if encontrada:
            page = encontrada

        status_stealth = "OK" if _STEALTH_LIB else "não instalado"
        print(f"Iniciando... (stealth: {status_stealth}, burst: {BURST_MIN}-{BURST_MAX} clientes)\n")
        df = processar_clientes(page, df)
        ctx.close()

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
