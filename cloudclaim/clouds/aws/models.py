from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AwsTarget:
    service: str
    hostname: str
    name: str
    region: str
    source_host: str = ""
    source: str = ""


@dataclass(frozen=True)
class AwsClaimOptions:
    profile: str | None = None
    application_name: str = "cloudclaim-eb"
    solution_stack_name: str | None = None


@dataclass(frozen=True)
class AvailabilityHandler:
    service: str
    description: str
    check: Callable[[AwsTarget, str | None], dict[str, Any]]


@dataclass(frozen=True)
class ClaimHandler:
    service: str
    description: str
    create: Callable[[AwsTarget, AwsClaimOptions], dict[str, Any]]
