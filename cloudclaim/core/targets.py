from __future__ import annotations

from typing import Any


def has_supported_targets(targets: list[Any], supported_services: set[str]) -> bool:
    return any(getattr(target, "service", "") in supported_services for target in targets)
