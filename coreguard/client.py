"""Cliente SDK Principal do CoreGuard Business."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .cache import LicenseCache
from .clock import MonotonicClockGuardian
from .exceptions import (
    ActivationRequiredError,
    CoreGuardError,
    DeviceBlockedError,
    DeviceLimitExceededError,
    InvalidActivationKeyError,
    LicenseExpiredError,
    LicenseRevokedError,
    LicenseSuspendedError,
    NetworkUnavailableError,
    TamperingDetectedError,
)
from .identity import DeviceIdentity
from .verifier import SignatureVerifier

log = logging.getLogger("coreguard")


class CoreGuard:
    """Interface unificada de licenciamento para automações Python."""

    def __init__(
        self,
        product: str,
        activation_key: str | None = None,
        server_url: str = "http://localhost:8800",
        config_dir: str | Path | None = None,
        auto_background_refresh: bool = True
    ) -> None:
        self.product = product
        self.activation_key = (activation_key or "").strip().upper()
        self.server_url = server_url.rstrip("/")
        self.config_dir = Path(config_dir) if config_dir else None
        self.auto_background_refresh = auto_background_refresh

        # Identidade do Hardware
        self.device_fingerprint = DeviceIdentity.get_device_fingerprint(self.config_dir)
        self.device_name = DeviceIdentity.get_device_name()
        self.os_info = DeviceIdentity.get_os_info()

        # Cache e Guardião do Relógio
        self.cache = LicenseCache(self.product, custom_dir=self.config_dir, fingerprint=self.device_fingerprint)
        cached_data = self.cache.load() or {}
        last_seen = cached_data.get("max_observed_timestamp", 0.0)
        self.clock = MonotonicClockGuardian(last_known_utc_timestamp=last_seen)

        # Thread de renovação em segundo plano
        self._refresher_thread: Optional[threading.Thread] = None
        self._stop_refresher = threading.Event()
        self._lock = threading.Lock()

        # Carrega autorização ativa do cache se existente
        self._cached_auth = cached_data.get("authorization")
        self._cached_signature = cached_data.get("signature")
        self._cached_public_key = cached_data.get("public_key_hex")
        self._check_interval_hours = cached_data.get("check_interval_hours", 6)
        self._server_status = cached_data.get("server_status")

        if not self.activation_key and cached_data.get("activation_key"):
            self.activation_key = cached_data.get("activation_key")

        # Inicia renovação em background se habilitado
        if self.auto_background_refresh:
            self.start_background_refresher()

    # ---------------------------------------------------------------- Ativação
    def activate(self, key: str | None = None) -> bool:
        """Solicita a ativação da licença junto ao servidor CoreGuard."""
        activation_key = (key or self.activation_key or "").strip().upper()
        if not activation_key:
            raise InvalidActivationKeyError("Chave de ativação não informada.")

        payload = {
            "activation_key": activation_key,
            "device_fingerprint": self.device_fingerprint,
            "device_name": self.device_name,
            "os_info": self.os_info,
            "client_version": "1.0.0"
        }

        resp = self._post("/api/v1/license/activate", payload)
        if not resp.get("ok"):
            msg = resp.get("message", "Falha na ativação.")
            raise CoreGuardError(msg)

        auth = resp["authorization"]
        sig = resp["signature"]
        pub_key = resp["public_key_hex"]

        # Validação matemática da assinatura antes de gravar no cache
        if not SignatureVerifier.verify(auth, sig, pub_key):
            raise TamperingDetectedError("Assinatura digital recebida do servidor é inválida.")

        with self._lock:
            self.activation_key = activation_key
            self._cached_auth = auth
            self._cached_signature = sig
            self._cached_public_key = pub_key
            self._check_interval_hours = resp.get("check_interval_hours", 6)

            # Grava no cache encriptado local
            self.clock.record_server_timestamp(auth["issued_at"])
            self.cache.save({
                "activation_key": activation_key,
                "authorization": auth,
                "signature": sig,
                "public_key_hex": pub_key,
                "check_interval_hours": self._check_interval_hours,
                "max_observed_timestamp": self.clock.max_observed_timestamp,
                "last_verified_at": time.time()
            })

        log.info(f"[CoreGuard] Produto '{self.product}' ativado com sucesso para este computador.")
        return True

    # ------------------------------------------------------------- Verificação
    def is_authorized(self) -> bool:
        """Checagem rápida não-bloqueante para laços e botões."""
        try:
            self.require_authorization()
            return True
        except CoreGuardError:
            return False

    def require_authorization(self) -> None:
        """Garante que a licença está válida e assinada. Lança exceção caso contrário."""
        # 0. Checa status remoto revogado/suspenso/expirado
        server_status = getattr(self, "_server_status", None)
        if server_status == "revoked":
            raise LicenseRevokedError("Esta licença foi revogada remotamente pelo administrador.")
        if server_status == "suspended":
            raise LicenseSuspendedError("Esta licença está temporariamente suspensa por pendência comercial.")
        if server_status == "expired":
            raise LicenseExpiredError("Esta licença está expirada.")

        with self._lock:
            auth = self._cached_auth
            sig = self._cached_signature
            pub_key = self._cached_public_key

        if not auth or not sig or not pub_key:
            # Tenta ler do cache novamente
            cached = self.cache.load()
            if cached:
                cached_srv_status = cached.get("server_status")
                if cached_srv_status == "revoked":
                    raise LicenseRevokedError("Esta licença foi revogada remotamente pelo administrador.")
                if cached_srv_status == "suspended":
                    raise LicenseSuspendedError("Esta licença está temporariamente suspensa por pendência comercial.")
                if cached_srv_status == "expired":
                    raise LicenseExpiredError("Esta licença está expirada.")
            if cached and cached.get("authorization"):
                auth = cached.get("authorization")
                sig = cached.get("signature")
                pub_key = cached.get("public_key_hex")
            else:
                raise ActivationRequiredError(
                    f"O produto '{self.product}' requer ativação prévia com Chave de Licença."
                )

        # 1. Validação de Assinatura Digital Ed25519
        if not SignatureVerifier.verify(auth, sig, pub_key):
            raise TamperingDetectedError("Assinatura digital de autorização inválida ou adulterada.")

        # 2. Validação de Vínculo de Hardware (Anti-Clonagem)
        if auth.get("device_fingerprint") != self.device_fingerprint:
            raise TamperingDetectedError("Esta autorização pertence a outro computador e não pode ser copiada.")

        # 3. Validação de Status
        status = auth.get("status", "")
        if status == "revoked":
            raise LicenseRevokedError("Esta licença foi revogada remotamente pelo administrador.")
        if status == "suspended":
            raise LicenseSuspendedError("Esta licença está temporariamente suspensa por pendência comercial.")
        if status == "expired":
            raise LicenseExpiredError("Esta licença está expirada.")

        # 4. Validação de Tolerância Offline e Relógio
        valid, reason = self.clock.check_validity(
            issued_at_iso=auth.get("issued_at", ""),
            offline_until_iso=auth.get("offline_until", "")
        )
        if not valid:
            raise LicenseExpiredError(reason)

    def verify_online(self) -> bool:
        """Verifica a licença com o servidor online e renova a tolerância offline."""
        with self._lock:
            auth = self._cached_auth

        if not auth:
            return False

        payload = {
            "license_id": auth["license_id"],
            "device_fingerprint": self.device_fingerprint,
            "client_version": "1.0.0"
        }

        try:
            resp = self._post("/api/v1/license/verify", payload)
        except NetworkUnavailableError:
            # Servidor indisponível: segue usando o cache offline se ainda dentro das 48h
            return self.is_authorized()

        if not resp.get("ok"):
            status = resp.get("status", "revoked")
            with self._lock:
                self._server_status = status
                if resp.get("authorization") and resp.get("signature") and resp.get("public_key_hex"):
                    self._cached_auth = resp["authorization"]
                    self._cached_signature = resp["signature"]
                    self._cached_public_key = resp["public_key_hex"]
                elif self._cached_auth:
                    self._cached_auth = None
                    self._cached_signature = None
                    self._cached_public_key = None
                self.cache.save({
                    "activation_key": self.activation_key,
                    "authorization": self._cached_auth,
                    "signature": self._cached_signature,
                    "public_key_hex": self._cached_public_key,
                    "server_status": status,
                    "max_observed_timestamp": self.clock.max_observed_timestamp
                })
            return False

        new_auth = resp["authorization"]
        sig = resp["signature"]
        pub_key = resp["public_key_hex"]

        if not SignatureVerifier.verify(new_auth, sig, pub_key):
            raise TamperingDetectedError("Assinatura do servidor violada durante renovação.")

        with self._lock:
            self._cached_auth = new_auth
            self._cached_signature = sig
            self._cached_public_key = pub_key
            self.clock.record_server_timestamp(new_auth["issued_at"])
            self.cache.save({
                "activation_key": self.activation_key,
                "authorization": new_auth,
                "signature": sig,
                "public_key_hex": pub_key,
                "check_interval_hours": resp.get("check_interval_hours", 6),
                "max_observed_timestamp": self.clock.max_observed_timestamp,
                "last_verified_at": time.time()
            })

        return True

    # ------------------------------------------------------------- Background
    def start_background_refresher(self) -> None:
        if self._refresher_thread and self._refresher_thread.is_alive():
            return
        self._stop_refresher.clear()

        def _loop():
            # Aguarda 15 segundos após boot para primeira verificação
            time.sleep(15)
            while not self._stop_refresher.is_set():
                try:
                    self.verify_online()
                except Exception as e:
                    log.debug(f"[CoreGuard] Renovação periódica em segundo plano: {e}")

                # Intervalo de 6 horas (ou configurado)
                interval_secs = max(300, self._check_interval_hours * 3600)
                # Verifica stop a cada 5 segundos
                for _ in range(int(interval_secs // 5)):
                    if self._stop_refresher.is_set():
                        break
                    time.sleep(5)

        self._refresher_thread = threading.Thread(target=_loop, name=f"coreguard-refresher-{self.product}", daemon=True)
        self._refresher_thread.start()

    def stop_background_refresher(self) -> None:
        self._stop_refresher.set()
        if self._refresher_thread:
            self._refresher_thread.join(timeout=2)

    # ------------------------------------------------------------- Status
    @property
    def status_info(self) -> dict[str, Any]:
        with self._lock:
            auth = self._cached_auth
        if not auth:
            return {"authorized": False, "status": "unactivated", "message": "Não ativado"}

        try:
            self.require_authorization()
            return {
                "authorized": True,
                "status": "active",
                "product": self.product,
                "license_id": auth.get("license_id"),
                "offline_until": auth.get("offline_until"),
                "device_fingerprint": self.device_fingerprint
            }
        except CoreGuardError as e:
            return {
                "authorized": False,
                "status": getattr(e, "status", "error"),
                "product": self.product,
                "message": str(e)
            }

    # ------------------------------------------------------------- HTTP interno
    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.server_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "CoreGuard-SDK/1.0"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(err_body).get("detail", err_body)
            except Exception:
                detail = err_body
            if exc.code == 404:
                raise InvalidActivationKeyError(detail)
            if exc.code == 403:
                if "revogada" in detail.lower():
                    raise LicenseRevokedError(detail)
                if "suspensa" in detail.lower():
                    raise LicenseSuspendedError(detail)
                if "bloqueado" in detail.lower():
                    raise DeviceBlockedError(detail)
                raise LicenseExpiredError(detail)
            if exc.code == 409:
                raise DeviceLimitExceededError(detail)
            raise CoreGuardError(f"HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NetworkUnavailableError(f"Servidor CoreGuard inacessível ({exc})")
