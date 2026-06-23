from __future__ import annotations

import json
from typing import Any

from cloudclaim.core.output import compact_message, emit, log_line, paint, tag, tag_join


def bool_availability(item: dict[str, Any]) -> bool:
    return item.get("registration_available") is True


def normalized_parent_note(payload: dict[str, Any]) -> str:
    input_hostname = payload.get("input_hostname", "")
    hostname = payload.get("hostname", "")
    service = payload.get("service", "")
    if service == "elastic_beanstalk" and input_hostname and input_hostname != hostname:
        return f"child:{input_hostname}"
    return ""


def check_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "available": bool_availability(item),
        "hostname": item.get("aws_hostname", ""),
        "input_hostname": item.get("source_host", ""),
        "message": item.get("registration_message", ""),
        "name": item.get("registration_checked_name", ""),
        "region": item.get("registration_checked_region", ""),
        "service": item.get("aws_service", ""),
        "status": item.get("registration_status", ""),
    }
    payload["note"] = normalized_parent_note(payload)
    return payload


def claim_payload(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    status = item.get("status", "")
    created = item.get("created") if isinstance(item.get("created"), dict) else {}
    checked = item.get("registration_status") not in {"", None, "unsupported"} or item.get("registration_available") in {True, False}
    payload = {
        "application_name": result.get("application_name", ""),
        "available": bool_availability(item),
        "availability_status": item.get("registration_status", ""),
        "checked": checked,
        "claim_attempted": status in {"claimed", "claim_failed"},
        "claimed": status == "claimed",
        "environment_name": created.get("environment_name", ""),
        "failure_reason": item.get("failure_reason", ""),
        "hint": item.get("hint", ""),
        "hostname": item.get("aws_hostname", ""),
        "input_hostname": item.get("source_host", ""),
        "message": item.get("message") or item.get("registration_message", ""),
        "name": item.get("registration_checked_name", ""),
        "region": item.get("registration_checked_region", ""),
        "service": item.get("aws_service", ""),
        "status": status,
    }
    payload["note"] = normalized_parent_note(payload)
    return payload


def format_check_line(payload: dict[str, Any], *, color: bool = False) -> str:
    if payload["status"] == "unsupported":
        status = "unsupported"
    elif payload["status"] == "error":
        status = "failed"
    else:
        status = "available" if payload["available"] else "not-available"
    line = f"{payload['hostname']} {tag_join(status, 'aws', payload['service'], color=color)}"
    if payload["status"] == "error" and payload["message"]:
        line = f"{line} {paint(compact_message(payload['message']), 'yellow', color)}"
    if payload["note"]:
        line = f"{line} {tag(payload['note'], color=color)}"
    return line


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
    fields = [claim_status(payload), "aws", payload["service"]]
    if payload["claimed"] and payload["environment_name"]:
        fields.append(f"env:{payload['environment_name']}")
    if payload["claim_attempted"] and not payload["claimed"]:
        fields.append("claim:failed")
        if payload["failure_reason"]:
            fields.append(payload["failure_reason"])
        if payload["region"]:
            fields.append(f"region:{payload['region']}")

    line = f"{payload['hostname']} {tag_join(*fields, color=color)}"
    if payload["claim_attempted"] and not payload["claimed"] and payload["message"]:
        line = f"{line} {paint(compact_message(payload['message']), 'yellow', color)}"
    if payload["claim_attempted"] and not payload["claimed"] and payload["hint"]:
        line = f"{line} {tag('hint', color=color)} {paint(compact_message(payload['hint']), 'cyan', color)}"
    if payload["status"] == "unsupported_claim" and payload["message"]:
        line = f"{line} {paint(compact_message(payload['message']), 'yellow', color)}"
    if payload["note"]:
        line = f"{line} {tag(payload['note'], color=color)}"
    return line


def cleanup_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result.get("cleanup_results", []))


def format_cleanup_line(payload: dict[str, Any], *, color: bool = False) -> str:
    if payload.get("cleanup_started"):
        return log_line("INF", f"cleanup started: {payload.get('environment_name', '')}", color=color)
    return log_line(
        "WRN",
        f"cleanup failed: {payload.get('environment_name', '')} {tag(payload.get('cleanup_error', ''), color=color)}",
        color=color,
    )


def print_check_results(results: list[dict[str, Any]], *, json_output: bool = False, color: bool = False) -> None:
    payloads = [check_payload(item) for item in results]
    if json_output:
        for payload in payloads:
            print(json.dumps(payload, sort_keys=True))
        return

    emit(log_line("INF", f"aws check: {format_check_summary(payloads)}", color=color))
    for payload in payloads:
        emit(format_check_line(payload, color=color))


def print_claim_result(result: dict[str, Any], *, json_output: bool = False, color: bool = False) -> None:
    payloads = [claim_payload(item, result) for item in result.get("results", [])]
    cleanups = cleanup_payloads(result)

    if json_output:
        for payload in payloads:
            print(json.dumps(payload, sort_keys=True))
        for cleanup in cleanups:
            print(json.dumps(cleanup, sort_keys=True))
        return

    claimed_count = sum(1 for payload in payloads if payload["claimed"])
    attempted_count = sum(1 for payload in payloads if payload["claim_attempted"])
    emit(log_line("INF", f"aws claim: {claimed_count}/{len(payloads)} claimed, {attempted_count}/{len(payloads)} attempted", color=color))
    for payload in payloads:
        emit(format_claim_line(payload, color=color))
    for cleanup in cleanups:
        emit(format_cleanup_line(cleanup, color=color))
