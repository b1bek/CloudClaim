from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .client import aws_json
from .models import AvailabilityHandler, AwsTarget
from .services import normalize_hostname


def normalize_availability(ok: bool, data: dict[str, Any], target: AwsTarget) -> dict[str, Any]:
    available = data.get("Available")
    fqdn = normalize_hostname(str(data.get("FullyQualifiedCNAME", "") or ""))
    message = data.get("message", data.get("error", data.get("stderr", "")))

    if ok and available is True and fqdn and fqdn != target.hostname:
        available = False
        message = f"Elastic Beanstalk would reserve {fqdn}, not {target.hostname}"

    if not ok or available is None:
        status = "error"
        available_value: bool | str = ""
    else:
        available_value = bool(available)
        status = "available" if available_value else "not_available"

    return {
        "registration_status": status,
        "registration_available": available_value,
        "registration_provider": "elasticbeanstalk:CheckDNSAvailability",
        "registration_checked_name": target.name,
        "registration_checked_region": target.region,
        "registration_fqdn": fqdn,
        "registration_message": message,
        "registration_raw": data,
    }


def check_elastic_beanstalk(target: AwsTarget, profile: str | None) -> dict[str, Any]:
    ok, data = aws_json(
        ["elasticbeanstalk", "check-dns-availability", "--cname-prefix", target.name],
        region=target.region,
        profile=profile,
        timeout=60,
    )
    return normalize_availability(ok, data, target)


AVAILABILITY_HANDLERS: dict[str, AvailabilityHandler] = {
    "elastic_beanstalk": AvailabilityHandler(
        "elastic_beanstalk",
        "Elastic Beanstalk CNAME prefix",
        check_elastic_beanstalk,
    ),
}


def check_target(target: AwsTarget, profile: str | None) -> dict[str, Any]:
    base = {
        "aws_service": target.service,
        "aws_hostname": target.hostname,
        "source_host": target.source_host,
        "source": target.source,
        "registration_checked_name": target.name,
        "registration_checked_region": target.region,
    }
    handler = AVAILABILITY_HANDLERS.get(target.service)
    if not handler:
        base.update(
            {
                "registration_status": "unsupported",
                "registration_available": "",
                "registration_provider": "",
                "registration_message": "No claimable AWS handler for this hostname type",
            }
        )
        return base

    base.update(handler.check(target, profile))
    return base


def check_targets(
    targets: list[AwsTarget],
    profile: str | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    results = []
    for target in targets:
        result = check_target(target, profile)
        results.append(result)
        if on_result:
            on_result(result)
    return results
