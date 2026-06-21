from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AzureTarget:
    service: str
    azure_hostname: str
    name: str
    location: str
    source_host: str = ""
    source: str = ""


@dataclass(frozen=True)
class AvailabilityHandler:
    service: str
    provider: str
    description: str
    check: Callable[[AzureTarget, str], dict[str, Any]]


@dataclass(frozen=True)
class ClaimHandler:
    service: str
    description: str
    create: Callable[[AzureTarget, str, str], dict[str, Any]]
    requires_resource_group: bool = True
