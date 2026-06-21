from __future__ import annotations

import json
from typing import Any

from cloudclaim.core.output import compact_message, emit, log_line, paint, tag, tag_join


def bool_availability(item: dict[str, Any]) -> bool:
    return item.get("registration_available") is True


def check_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": bool_availability(item),
        "hostname": item.get("azure_hostname", ""),
        "location": item.get("registration_checked_location", ""),
        "message": item.get("registration_message", ""),
        "name": item.get("registration_checked_name", ""),
        "service": item.get("azure_service", ""),
        "status": item.get("registration_status", ""),
    }


def claim_payload(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    status = item.get("status", "")
    checked = item.get("registration_status") not in {"", None, "unsupported"} or item.get("registration_available") in {True, False}
    return {
        "available": bool_availability(item),
        "availability_status": item.get("registration_status", ""),
        "checked": checked,
        "claim_attempted": status in {"claimed", "claim_failed"},
        "claimed": status == "claimed",
        "failure_reason": item.get("failure_reason", ""),
        "hint": item.get("hint", ""),
        "hostname": item.get("azure_hostname", ""),
        "location": item.get("registration_checked_location", ""),
        "message": item.get("message") or item.get("registration_message", ""),
        "name": item.get("registration_checked_name", ""),
        "resource_group": item.get("claim_resource_group") or result.get("resource_group", ""),
        "service": item.get("azure_service", ""),
        "status": status,
    }


def format_check_line(payload: dict[str, Any], *, color: bool = False) -> str:
    if payload["status"] == "unsupported":
        status = "unsupported"
    else:
        status = "available" if payload["available"] else "not-available"
    fields = [status, "azure", payload["service"]]
    return f"{payload['hostname']} {tag_join(*fields, color=color)}"


def format_check_summary(payloads: list[dict[str, Any]]) -> str:
    available_count = sum(1 for payload in payloads if payload["available"])
    return f"{available_count}/{len(payloads)} available"


def claim_status(payload: dict[str, Any]) -> str:
    if payload["claimed"]:
        return "claimed"
    if payload["claim_attempted"]:
        return "failed"
    if payload["status"] == "duplicate":
        return "duplicate"
    if payload["status"] == "skipped_service":
        return "skipped"
    if payload["status"] in {"unsupported", "unsupported_claim"}:
        return "unsupported"
    if not payload["available"]:
        return "not-available"
    return "not-claimed"


def format_claim_line(payload: dict[str, Any], *, color: bool = False) -> str:
    fields = [claim_status(payload), "azure", payload["service"]]
    if (payload["claim_attempted"] or payload["claimed"]) and payload["resource_group"]:
        fields.append(f"rg:{payload['resource_group']}")
    if payload["claim_attempted"] and not payload["claimed"]:
        fields.append("claim:failed")
        if payload["failure_reason"]:
            fields.append(payload["failure_reason"])
        if payload["location"]:
            fields.append(f"region:{payload['location']}")

    line = f"{payload['hostname']} {tag_join(*fields, color=color)}"
    if payload["claim_attempted"] and not payload["claimed"] and payload["message"]:
        line = f"{line} {paint(compact_message(payload['message']), 'yellow', color)}"
    if payload["claim_attempted"] and not payload["claimed"] and payload["hint"]:
        line = f"{line} {tag('hint', color=color)} {paint(compact_message(payload['hint']), 'cyan', color)}"
    if payload["status"] == "unsupported_claim" and payload["message"]:
        line = f"{line} {paint(compact_message(payload['message']), 'yellow', color)}"
    return line


def cleanup_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("cleanup_started") is None:
        return None
    return {
        "cleanup_started": bool(result.get("cleanup_started")),
        "cleanup_command": result.get("cleanup_command", ""),
        "cleanup_error": result.get("cleanup_error", ""),
        "resource_group": result.get("resource_group", ""),
    }


def format_cleanup_line(payload: dict[str, Any], *, color: bool = False) -> str:
    if payload["cleanup_started"]:
        return log_line("INF", f"cleanup started: {payload['resource_group']}", color=color)
    return log_line("WRN", f"cleanup failed: {payload['resource_group']} {tag(payload['cleanup_error'], color=color)}", color=color)


def print_check_results(results: list[dict[str, Any]], *, json_output: bool = False, color: bool = False) -> None:
    payloads = [check_payload(item) for item in results]
    if json_output:
        for payload in payloads:
            print(json.dumps(payload, sort_keys=True))
        return

    emit(log_line("INF", f"azure check: {format_check_summary(payloads)}", color=color))
    for payload in payloads:
        emit(format_check_line(payload, color=color))


def print_claim_result(result: dict[str, Any], *, json_output: bool = False, color: bool = False) -> None:
    payloads = [claim_payload(item, result) for item in result.get("results", [])]
    cleanup = cleanup_payload(result)

    if json_output:
        for payload in payloads:
            print(json.dumps(payload, sort_keys=True))
        if cleanup:
            print(json.dumps(cleanup, sort_keys=True))
        return

    claimed_count = sum(1 for payload in payloads if payload["claimed"])
    attempted_count = sum(1 for payload in payloads if payload["claim_attempted"])
    emit(log_line("INF", f"azure claim: {claimed_count}/{len(payloads)} claimed, {attempted_count}/{len(payloads)} attempted", color=color))
    for payload in payloads:
        emit(format_claim_line(payload, color=color))

    if cleanup:
        emit(format_cleanup_line(cleanup, color=color))
