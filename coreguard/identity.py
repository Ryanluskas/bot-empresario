"""Mecanismo de Identidade Criptográfica e Fingerprint de Dispositivo."""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import subprocess
import uuid
from pathlib import Path


class DeviceIdentity:
    """Extrai uma impressão digital estável e multicamada do hardware e sistema."""

    @staticmethod
    def get_machine_guid() -> str:
        """Lê o MachineGuid único do Windows no Registro."""
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            ) as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                if val:
                    return str(val).strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def get_bios_uuid() -> str:
        """Obtém o UUID de placa-mãe/BIOS via WMI no Windows."""
        try:
            cmd = "powershell -NoProfile -Command \"(Get-CimInstance Win32_ComputerSystemProduct).UUID\""
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=True)
            out = res.stdout.strip()
            if out and len(out) > 10 and "error" not in out.lower():
                return out
        except Exception:
            pass
        return ""

    @staticmethod
    def get_disk_serial() -> str:
        """Obtém o serial de volume do disco principal (C:)."""
        try:
            vol_serial = ctypes.c_ulong()
            max_comp_len = ctypes.c_ulong()
            file_sys_flags = ctypes.c_ulong()
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p("C:\\"),
                None,
                0,
                ctypes.byref(vol_serial),
                ctypes.byref(max_comp_len),
                ctypes.byref(file_sys_flags),
                None,
                0
            )
            if vol_serial.value:
                return hex(vol_serial.value)[2:].upper()
        except Exception:
            pass
        return ""

    @classmethod
    def get_device_fingerprint(cls, app_data_dir: Path | None = None) -> str:
        """Gera o identificador SHA-256 combinado e seguro da máquina."""
        guid = cls.get_machine_guid()
        bios = cls.get_bios_uuid()
        disk = cls.get_disk_serial()
        node = platform.node().strip().lower()
        processor = platform.processor().strip()

        # Cria ou recupera uma chave de instalação local persistente
        inst_seed = ""
        if app_data_dir:
            try:
                app_data_dir.mkdir(parents=True, exist_ok=True)
                seed_file = app_data_dir / ".inst_identity"
                if seed_file.exists():
                    inst_seed = seed_file.read_text(encoding="utf-8").strip()
                else:
                    inst_seed = uuid.uuid4().hex
                    seed_file.write_text(inst_seed, encoding="utf-8")
            except Exception:
                pass

        raw_components = f"{guid}::{bios}::{disk}::{node}::{processor}::{inst_seed}"
        return hashlib.sha256(raw_components.encode("utf-8")).hexdigest()

    @staticmethod
    def get_device_name() -> str:
        return platform.node() or "Desconhecido"

    @staticmethod
    def get_os_info() -> str:
        return f"{platform.system()} {platform.release()} ({platform.version()})"
