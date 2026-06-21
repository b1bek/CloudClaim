from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .availability import check_target
from .catalog import SERVICE_BY_NAME, STORAGE_SERVICES
from .client import az_json, create_resource_group, delete_resource_group, require_az, subscription_id
from .models import AzureTarget, ClaimHandler
from .prerequisites import app_service_plans
from .services import target_key


AUTO_LOCATION = "auto"
AUTO_LOCATIONS = (
    "eastus",
    "eastus2",
    "westus2",
    "westus3",
    "centralus",
    "southcentralus",
    "northcentralus",
    "westus",
    "canadacentral",
    "westeurope",
    "northeurope",
    "uksouth",
    "francecentral",
    "germanywestcentral",
    "swedencentral",
    "australiaeast",
    "southeastasia",
    "eastasia",
    "japaneast",
    "koreacentral",
    "centralindia",
    "brazilsouth",
)
def is_auto_location(location: str) -> bool:
    return not location or location.lower() == AUTO_LOCATION


def location_candidates(location: str) -> list[str]:
    if not is_auto_location(location):
        return [location]
    return list(AUTO_LOCATIONS)


def default_location(location: str) -> str:
    return location_candidates(location)[0]


def classify_claim_error(message: str) -> tuple[str, str]:
    normalized = message.lower()
    if "quota" in normalized or "current limit" in normalized:
        return "quota", "Azure quota blocked proof resource creation. Use a region/subscription with App Service quota, or pass --location to force a known-good region."
    if "not available" in normalized:
        return "not_available", ""
    return "", ""


def can_retry_location(location: str, message: str) -> bool:
    reason, _ = classify_claim_error(message)
    return is_auto_location(location) and reason == "quota"


def create_webapp_in_plan(target: AzureTarget, resource_group: str, plan: str) -> dict[str, Any]:
    return require_az(
        *az_json(["webapp", "create", "-g", resource_group, "-p", plan, "-n", target.name[:60]], timeout=300),
        action="create App Service app",
    )


def claim_app_service_existing_plan(target: AzureTarget, resource_group: str) -> dict[str, Any] | None:
    errors = []
    for plan in app_service_plans(target.location):
        plan_id = str(plan.get("id", ""))
        plan_name = str(plan.get("name", ""))
        plan_resource_group = str(plan.get("resourceGroup", ""))
        if not plan_id:
            continue
        try:
            data = create_webapp_in_plan(target, resource_group, plan_id)
            return {
                "service": target.service,
                "name": target.name[:60],
                "location": target.location,
                "plan": plan_name or plan_id,
                "plan_id": plan_id,
                "plan_resource_group": plan_resource_group,
                "reused_plan": True,
                "result": data,
            }
        except Exception as exc:
            errors.append(f"{plan_name or plan_id}: {exc}")

    if errors:
        raise RuntimeError("create App Service app in existing plan failed: " + " | ".join(errors))
    return None


def claim_public_ip_dns_label(target: AzureTarget, resource_group: str, fallback_location: str) -> dict[str, Any]:
    location = default_location(target.location)
    data = require_az(
        *az_json(
            [
                "network",
                "public-ip",
                "create",
                "-g",
                resource_group,
                "-n",
                target.name[:63],
                "-l",
                location,
                "--sku",
                "Standard",
                "--allocation-method",
                "Static",
                "--dns-name",
                target.name[:63],
            ],
            timeout=180,
        ),
        action="create Public IP DNS label",
    )
    return {"service": target.service, "name": target.name[:63], "location": location, "result": data}


def claim_app_service(target: AzureTarget, resource_group: str, fallback_location: str) -> dict[str, Any]:
    errors = []
    for location in location_candidates(target.location):
        regional_target = replace(target, location=location)
        plan_name = f"{regional_target.name[:32]}-plan"
        try:
            require_az(
                *az_json(
                    ["appservice", "plan", "create", "-g", resource_group, "-n", plan_name, "-l", regional_target.location, "--sku", "F1"],
                    timeout=240,
                ),
                action="create App Service plan",
            )
            data = create_webapp_in_plan(regional_target, resource_group, plan_name)
            return {"service": regional_target.service, "name": regional_target.name[:60], "location": regional_target.location, "plan": plan_name, "result": data}
        except Exception as exc:
            message = str(exc)
            reason, _ = classify_claim_error(message)
            if reason == "quota":
                reused = claim_app_service_existing_plan(regional_target, resource_group)
                if reused:
                    return reused
            errors.append(f"{location}: {message}")
            if not can_retry_location(target.location, message):
                raise

    raise RuntimeError("App Service claim failed in automatic locations: " + " | ".join(errors))


def claim_storage_account(target: AzureTarget, resource_group: str, fallback_location: str) -> dict[str, Any]:
    location = default_location(target.location)
    data = require_az(
        *az_json(
            [
                "storage",
                "account",
                "create",
                "-g",
                resource_group,
                "-n",
                target.name[:24],
                "-l",
                location,
                "--sku",
                "Standard_LRS",
                "--kind",
                "StorageV2",
                "--allow-blob-public-access",
                "true",
            ],
            timeout=240,
        ),
        action="create Storage account",
    )
    return {"service": target.service, "name": target.name[:24], "location": location, "result": data}


CLAIM_HANDLERS: dict[str, ClaimHandler] = {
    "app_service": ClaimHandler("app_service", SERVICE_BY_NAME["app_service"].claim_description, claim_app_service),
    "public_ip_dns_label": ClaimHandler("public_ip_dns_label", SERVICE_BY_NAME["public_ip_dns_label"].claim_description, claim_public_ip_dns_label),
}
for storage_service in STORAGE_SERVICES:
    CLAIM_HANDLERS[storage_service] = ClaimHandler(storage_service, SERVICE_BY_NAME[storage_service].claim_description, claim_storage_account)

CLAIMABLE_SERVICES = set(CLAIM_HANDLERS)


def claim_targets(
    targets: list[AzureTarget],
    resource_group: str,
    fallback_location: str,
    selected_services: set[str] | None,
    cleanup: bool,
    on_result: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    on_cleanup: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    sub = ""
    result: dict[str, Any] = {
        "mode": "claim",
        "resource_group": resource_group,
        "fallback_location": fallback_location,
        "cleanup_requested": cleanup,
        "selected_services": sorted(selected_services) if selected_services else sorted(CLAIMABLE_SERVICES),
        "cleanup_command": f"az group delete -n {resource_group} --yes --no-wait",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "results": [],
    }
    seen: set[tuple[str, str, str]] = set()
    rg_created = False

    try:
        for target in targets:
            if target.service == "unsupported":
                entry = check_target(target, sub)
                entry.update({"status": "unsupported"})
                result["results"].append(entry)
                if on_result:
                    on_result(entry, result)
                continue

            if not sub:
                sub = subscription_id()
            entry = check_target(target, sub)
            key = target_key(target)
            if key in seen:
                entry.update({"status": "duplicate", "message": "same service/name/location already processed"})
            elif selected_services and target.service not in selected_services:
                entry.update({"status": "skipped_service", "message": "service not selected"})
            elif target.service not in CLAIM_HANDLERS:
                entry.update({"status": "unsupported_claim", "message": "no claim handler for this Azure service"})
            elif entry.get("registration_status") != "available":
                entry.update({"status": "not_claimed", "message": "Azure availability check did not return available"})
            else:
                seen.add(key)
                handler = CLAIM_HANDLERS[target.service]
                if handler.requires_resource_group and not rg_created:
                    create_resource_group(resource_group, default_location(fallback_location))
                    rg_created = True
                try:
                    if handler.requires_resource_group:
                        entry["claim_resource_group"] = resource_group
                    created = handler.create(target, resource_group, fallback_location)
                    if isinstance(created, dict) and created.get("resource_group"):
                        entry["claim_resource_group"] = created["resource_group"]
                    entry.update({"status": "claimed", "created": created})
                except Exception as exc:
                    reason, hint = classify_claim_error(str(exc))
                    if reason == "not_available":
                        entry.update({"status": "not_claimed", "registration_available": False, "registration_status": "not_available", "message": "Azure reported the name is not available"})
                    else:
                        entry.update({"status": "claim_failed", "message": str(exc), "failure_reason": reason, "hint": hint})
            result["results"].append(entry)
            if on_result:
                on_result(entry, result)

        result["finished_at_utc"] = datetime.now(UTC).isoformat()
        return result
    finally:
        if rg_created and cleanup:
            ok, message = delete_resource_group(resource_group)
            result["cleanup_started"] = ok
            if not ok:
                result["cleanup_error"] = message
            if on_cleanup:
                on_cleanup(result)
