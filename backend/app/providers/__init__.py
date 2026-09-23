"""Supplier data providers (Mouser, Digi-Key, TME, Farnell).

All network access goes through `safety.fetch_json`, which enforces a per-minute
rate limit, a persisted daily quota, a disk cache and a circuit breaker — the
lessons from getting the Celestrak IP blocked. Providers are only ever called
from an explicit user action (the "Look up" button), never in bulk or on a timer.
"""
from __future__ import annotations

from .base import Provider, ProviderBlocked, ProviderError, ProviderResult
from .digikey import DigiKeyProvider
from .farnell import FarnellProvider
from .mouser import MouserProvider
from .tme import TMEProvider

_REGISTRY: dict[str, Provider] = {
    p.name: p for p in [MouserProvider(), DigiKeyProvider(), TMEProvider(), FarnellProvider()]
}


def all_providers() -> list[Provider]:
    return list(_REGISTRY.values())


def get_provider(name: str) -> Provider | None:
    return _REGISTRY.get(name)


__all__ = [
    "Provider",
    "ProviderResult",
    "ProviderError",
    "ProviderBlocked",
    "all_providers",
    "get_provider",
]
