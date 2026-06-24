from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .catalog import SERVICE_BY_NAME, STORAGE_SERVICES
from .client import az_json, subscription_id
from .models import AvailabilityHandler, AzureTarget


def normalize_availability(ok: bool, data: dict[str, Any], target: AzureTarget, provider: str) -> dict[str, Any]:
    available = data.get("nameAvailable")
    if available is None:
        available = data.get("available")

    message = data.get("message", data.get("error", data.get("stderr", "")))
    normalized_message = str(message).lower()
    if available is None and "not available" in normalized_message:
        available = False

    if not ok or available is None:
        status = "error"
        available_value: bool | str = ""
    else:
        available_value = bool(available)
        status = "available" if available_value else "not_available"

    return {
        "registration_status": status,
        "registration_available": available_value,
        "registration_provider": provider,
        "registration_checked_name": target.name,
        "registration_checked_location": target.location,
        "registration_reason": data.get("reason", ""),
        "registration_message": message,
        "registration_raw": data,
    }


def check_app_service(target: AzureTarget, sub: str) -> dict[str, Any]:
    ok, data = az_json(
        [
            "rest",
            "--method",
            "post",
            "--url",
            f"https://management.azure.com/subscriptions/{sub}/providers/Microsoft.Web/checknameavailability?api-version=2024-04-01",
            "--body",
            json.dumps({"name": target.name, "type": "Microsoft.Web/sites"}),
        ],
        timeout=60,
    )
    return normalize_availability(ok, data, target, "Microsoft.Web/sites")


def check_public_ip_dns_label(target: AzureTarget, sub: str) -> dict[str, Any]:
    ok, data = az_json(
        [
            "rest",
            "--method",
            "get",
            "--url",
            (
                f"https://management.azure.com/subscriptions/{sub}/providers/"
                f"Microsoft.Network/locations/{target.location}/CheckDnsNameAvailability"
                f"?domainNameLabel={target.name}&api-version=2024-05-01"
            ),
        ],
        timeout=60,
    )
    return normalize_availability(ok, data, target, "Microsoft.Network/publicIPAddresses/dnsSettings")


def check_traffic_manager(target: AzureTarget, sub: str) -> dict[str, Any]:
    ok, data = az_json(["network", "traffic-manager", "profile", "check-dns", "--name", target.name], timeout=60)
    return normalize_availability(ok, data, target, "Microsoft.Network/trafficManagerProfiles")


def check_api_management(target: AzureTarget, sub: str) -> dict[str, Any]:
    ok, data = az_json(["apim", "check-name", "--name", target.name], timeout=60)
    return normalize_availability(ok, data, target, "Microsoft.ApiManagement/service")


def check_storage_account(target: AzureTarget, sub: str) -> dict[str, Any]:
    ok, data = az_json(["storage", "account", "check-name", "--name", target.name], timeout=60)
    return normalize_availability(ok, data, target, "Microsoft.Storage/storageAccounts")


AVAILABILITY_HANDLERS: dict[str, AvailabilityHandler] = {
    "app_service": AvailabilityHandler(
        "app_service",
        SERVICE_BY_NAME["app_service"].availability_provider,
        SERVICE_BY_NAME["app_service"].availability_description,
        check_app_service,
    ),
    "public_ip_dns_label": AvailabilityHandler(
        "public_ip_dns_label",
        SERVICE_BY_NAME["public_ip_dns_label"].availability_provider,
        SERVICE_BY_NAME["public_ip_dns_label"].availability_description,
        check_public_ip_dns_label,
    ),
    "traffic_manager": AvailabilityHandler(
        "traffic_manager",
        SERVICE_BY_NAME["traffic_manager"].availability_provider,
        SERVICE_BY_NAME["traffic_manager"].availability_description,
        check_traffic_manager,
    ),
    "api_management": AvailabilityHandler(
        "api_management",
        SERVICE_BY_NAME["api_management"].availability_provider,
        SERVICE_BY_NAME["api_management"].availability_description,
        check_api_management,
    ),
}
for storage_service in STORAGE_SERVICES:
    spec = SERVICE_BY_NAME[storage_service]
    AVAILABILITY_HANDLERS[storage_service] = AvailabilityHandler(
        storage_service,
        spec.availability_provider,
        spec.availability_description,
        check_storage_account,
    )


def check_target(target: AzureTarget, sub: str) -> dict[str, Any]:
    base = {
        "azure_service": target.service,
        "azure_hostname": target.azure_hostname,
        "source_host": target.source_host,
        "source": target.source,
        "registration_checked_name": target.name,
        "registration_checked_location": target.location,
    }
    handler = AVAILABILITY_HANDLERS.get(target.service)
    if not handler:
        base.update(
            {
                "registration_status": "unsupported",
                "registration_available": "",
                "registration_provider": "",
                "registration_message": "No availability handler for this Azure service",
            }
        )
        return base

    spec = SERVICE_BY_NAME.get(target.service)
    if not spec or not spec.claim_description:
        base.update(
            {
                "registration_status": "unsupported",
                "registration_available": "",
                "registration_provider": handler.provider,
                "registration_message": "No claim handler for this Azure service",
            }
        )
        return base

    base.update(handler.check(target, sub))
    return base


def check_targets(
    targets: list[AzureTarget],
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    sub = ""
    results = []
    for target in targets:
        if target.service == "unsupported":
            result = check_target(target, sub)
            results.append(result)
            if on_result:
                on_result(result)
            continue

        if not sub:
            sub = subscription_id()
        result = check_target(target, sub)
        results.append(result)
        if on_result:
            on_result(result)
    return results
