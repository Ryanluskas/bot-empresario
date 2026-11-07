"""Cache Local Criptografado e Protegido para Licenças do CoreGuard."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional


class LicenseCache:
    """Gerencia o armazenamento local seguro do token de autorização e carimbos de tempo."""

    def __init__(self, product_id: str, custom_dir: Path | str | None = None, fingerprint: str = "") -> None:
        self.product_id = product_id
        self.fingerprint = fingerprint or "default_coreguard_fingerprint"

        if custom_dir:
            self.dir = Path(custom_dir)
        else:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            self.dir = Path(base) / ".coreguard"

        self.dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.dir / f".cg_lic_{product_id}.dat"

    def _get_obfuscation_key(self) -> bytes:
        return hashlib.sha256(f"cg_obf::{self.product_id}::{self.fingerprint}".encode("utf-8")).digest()

    def _xor_crypt(self, data: bytes) -> bytes:
        key = self._get_obfuscation_key()
        key_len = len(key)
        return bytes(b ^ key[i % key_len] for i, b in enumerate(data))

    def save(self, payload: dict[str, Any]) -> None:
        try:
            raw_json = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            encrypted = self._xor_crypt(raw_json)
            b64_data = base64.b64encode(encrypted).decode("ascii")
            self.file_path.write_text(b64_data, encoding="utf-8")
        except Exception:
            pass

    def load(self) -> Optional[dict[str, Any]]:
        if not self.file_path.exists():
            return None
        try:
            b64_data = self.file_path.read_text(encoding="utf-8").strip()
            encrypted = base64.b64decode(b64_data)
            decrypted = self._xor_crypt(encrypted)
            return json.loads(decrypted.decode("utf-8"))
        except Exception:
            return None

    def clear(self) -> None:
        try:
            if self.file_path.exists():
                self.file_path.unlink()
        except Exception:
            pass
