"""Monitor de Tempo Monotônico e Proteção contra Manipulação de Relógio."""

from __future__ import annotations

import time
from datetime import datetime, timezone


class MonotonicClockGuardian:
    """Impede que a alteração manual do relógio do Windows estenda o prazo de validade offline."""

    def __init__(self, last_known_utc_timestamp: float = 0.0) -> None:
        self._initial_monotonic = time.monotonic()
        self._initial_wall = time.time()
        self._max_observed_timestamp = max(last_known_utc_timestamp, self._initial_wall)

    @property
    def max_observed_timestamp(self) -> float:
        return self._max_observed_timestamp

    def record_server_timestamp(self, server_iso: str) -> None:
        """Sincroniza com a marca d'água de tempo assinada pelo servidor."""
        try:
            dt = datetime.fromisoformat(server_iso.replace("Z", "+00:00"))
            ts = dt.timestamp()
            if ts > self._max_observed_timestamp:
                self._max_observed_timestamp = ts
        except Exception:
            pass

    def check_validity(self, issued_at_iso: str, offline_until_iso: str) -> tuple[bool, str]:
        """Avalia se a autorização offline ainda é válida, imune a recuos de relógio."""
        try:
            issued_dt = datetime.fromisoformat(issued_at_iso.replace("Z", "+00:00"))
            offline_dt = datetime.fromisoformat(offline_until_iso.replace("Z", "+00:00"))
        except Exception as e:
            return False, f"Formato de data de autorização corrompido: {e}"

        issued_ts = issued_dt.timestamp()
        offline_until_ts = offline_dt.timestamp()

        now_wall = time.time()
        now_monotonic_offset = time.monotonic() - self._initial_monotonic
        projected_time = self._initial_wall + now_monotonic_offset

        # Detecta recuo proposital do relógio do Windows
        if now_wall < (self._max_observed_timestamp - 300):  # tolerância de 5 min para drift
            return False, "Violação detectada: o relógio do sistema foi atrasado para manipular a licença."

        # Atualiza a marca d'água máxima
        current_effective_ts = max(now_wall, projected_time, self._max_observed_timestamp)
        self._max_observed_timestamp = current_effective_ts

        # Verifica se o tempo efetivo passou da tolerância offline
        if current_effective_ts > offline_until_ts:
            return False, "Período de tolerância offline (48h) expirado. Conecte à internet para renovar a autorização."

        return True, "OK"
