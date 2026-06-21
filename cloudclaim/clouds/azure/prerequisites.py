from __future__ import annotations

from typing import Any

from .client import az_json, require_az

def normalize_azure_location(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def app_service_plans(location: str) -> list[dict[str, Any]]:
    data = require_az(*az_json(["appservice", "plan", "list"], timeout=60), action="list App Service plans")
    if isinstance(data, dict):
        plans = data.get("value", [])
    else:
        plans = []

    wanted_location = normalize_azure_location(location)
    candidates = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        plan_location = normalize_azure_location(str(plan.get("location", "")))
        if plan_location != wanted_location:
            continue
        if plan.get("reserved") is True:
            continue
        if not plan.get("id"):
            continue
        candidates.append(plan)
    return sorted(candidates, key=lambda item: (str(item.get("resourceGroup", "")), str(item.get("name", ""))))
