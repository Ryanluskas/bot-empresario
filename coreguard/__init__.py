"""CoreGuard Business — SDK Universal de Licenciamento e Proteção de Automações."""

from .client import CoreGuard
from .exceptions import (
    ActivationRequiredError,
    CoreGuardError,
    DeviceBlockedError,
    DeviceLimitExceededError,
    InvalidActivationKeyError,
    LicenseError,
    LicenseExpiredError,
    LicenseRevokedError,
    LicenseSuspendedError,
    NetworkUnavailableError,
    TamperingDetectedError,
)

__version__ = "1.0.0"

__all__ = [
    "CoreGuard",
    "CoreGuardError",
    "LicenseError",
    "ActivationRequiredError",
    "InvalidActivationKeyError",
    "LicenseSuspendedError",
    "LicenseRevokedError",
    "LicenseExpiredError",
    "DeviceLimitExceededError",
    "DeviceBlockedError",
    "TamperingDetectedError",
    "NetworkUnavailableError",
]
