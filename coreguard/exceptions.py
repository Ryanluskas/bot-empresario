"""Hierarquia de Exceções do CoreGuard SDK."""

from __future__ import annotations


class CoreGuardError(Exception):
    """Exceção base do CoreGuard."""
    pass


class LicenseError(CoreGuardError):
    """Exceção base para problemas de licença."""
    pass


class ActivationRequiredError(LicenseError):
    """Software ainda não ativado neste computador."""
    pass


class InvalidActivationKeyError(LicenseError):
    """Chave de ativação inválida ou inexistente."""
    pass


class LicenseSuspendedError(LicenseError):
    """Licença temporariamente suspensa pelo administrador."""
    pass


class LicenseRevokedError(LicenseError):
    """Licença revogada permanentemente."""
    pass


class LicenseExpiredError(LicenseError):
    """Licença com período de validade expirado ou tolerância offline excedida."""
    pass


class DeviceLimitExceededError(LicenseError):
    """Limite de computadores autorizados excedido para esta licença."""
    pass


class DeviceBlockedError(LicenseError):
    """Este computador foi bloqueado pelo administrador."""
    pass


class TamperingDetectedError(CoreGuardError):
    """Tentativa de violação ou manipulação detectada (assinatura inválida ou relógio alterado)."""
    pass


class NetworkUnavailableError(CoreGuardError):
    """Servidor CoreGuard inacessível e nenhum cache offline válido encontrado."""
    pass
