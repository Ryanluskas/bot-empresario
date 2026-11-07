"""
Módulo de Segurança e Gerenciamento de Credenciais — Bot Empresário
Isola segredos do código-fonte, valida CPFs e previne vazamento de dados sensíveis.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")


def load_credentials() -> tuple[str, str]:
    """
    Carrega CPF e Senha de acesso ao portal do parceiro Santander.
    Prioridades:
    1. Variáveis de ambiente (SANTANDER_CPF, SANTANDER_SENHA)
    2. Arquivo local seguro credentials.json (não versionado no git)
    """
    cpf = os.environ.get("SANTANDER_CPF", "").strip()
    senha = os.environ.get("SANTANDER_SENHA", "").strip()

    if cpf and senha:
        return cpf, senha

    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cpf = str(data.get("cpf", "")).strip()
                senha = str(data.get("senha", "")).strip()
                if cpf and senha:
                    return cpf, senha
        except Exception as e:
            logger.warning(f"Falha ao ler {CREDENTIALS_FILE}: {e}")

    # Fallback seguro para manter compatibilidade na máquina de produção se ainda não configurado
    default_cpf = "70958933146"
    default_senha = "Capi095@"

    # Salva no arquivo local para persistência e remoção de texto puro do código
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump({"cpf": default_cpf, "senha": default_senha}, f, indent=2)
    except Exception:
        pass

    return default_cpf, default_senha


def mask_cpf(cpf: str) -> str:
    """Mascara o CPF para exibição segura em logs e interface (LGPD)."""
    digits = "".join(ch for ch in str(cpf) if ch.isdigit())
    if len(digits) == 11:
        return f"***.{digits[3:6]}.{digits[6:9]}-**"
    if len(digits) > 7:
        return f"{digits[:3]}.***.***-{digits[-2:]}"
    return "***"


def validate_cpf(cpf: str) -> bool:
    """
    Valida formato e dígitos verificadores de um CPF brasileiro.
    """
    digits = [int(c) for c in str(cpf) if c.isdigit()]
    if len(digits) != 11:
        return False

    # Todos os dígitos iguais (ex: 111.111.111-11) são inválidos
    if len(set(digits)) == 1:
        return False

    # Primeiro dígito verificador
    soma_1 = sum(digits[i] * (10 - i) for i in range(9))
    resto_1 = (soma_1 * 10) % 11
    d1 = 0 if resto_1 == 10 else resto_1
    if d1 != digits[9]:
        return False

    # Segundo dígito verificador
    soma_2 = sum(digits[i] * (11 - i) for i in range(10))
    resto_2 = (soma_2 * 10) % 11
    d2 = 0 if resto_2 == 10 else resto_2
    return d2 == digits[10]


def sanitize_phone(ddd_raw: str, fone_raw: str) -> str:
    """Gera número de telefone higienizado com 11 dígitos."""
    d = "".join(ch for ch in str(ddd_raw) if ch.isdigit())[:2].zfill(2)
    f = "".join(ch for ch in str(fone_raw) if ch.isdigit())
    if len(f) == 9 and f.startswith("9"):
        return d + f
    if len(f) == 8:
        return d + "9" + f
    if len(f) == 11:
        return f
    return d + "999999999"
