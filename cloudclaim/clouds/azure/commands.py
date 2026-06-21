from __future__ import annotations

import argparse
import json
from pathlib import Path
from secrets import token_hex
from typing import Any

from cloudclaim.core.output import compact_message, emit, log_line, print_banner, should_color, tag_join
from cloudclaim.core.targets import has_supported_targets

from .availability import AVAILABILITY_HANDLERS, check_targets
from .claims import CLAIM_HANDLERS, CLAIMABLE_SERVICES, claim_targets
from .client import precheck
from .inputs import load_targets
from .output import (
    check_payload,
    claim_payload,
    cleanup_payload,
    format_check_line,
    format_check_summary,
    format_claim_line,
    format_cleanup_line,
)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_services(payload: dict[str, dict[str, Any]], *, json_output: bool = False, color: bool = False) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    check_count = sum(1 for item in payload.values() if item["availability"])
    claim_count = sum(1 for item in payload.values() if item["claim"])
    emit(log_line("INF", f"azure services: {check_count} check handlers, {claim_count} claim handlers", color=color))
    for service, info in payload.items():
        capabilities = []
        if info["availability"]:
            capabilities.append("check")
        if info["claim"]:
            capabilities.append("claim")
        emit(f"{service} {tag_join(','.join(capabilities) if capabilities else 'none', color=color)} {info['description']}")


def precheck_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "account": result.get("account", ""),
        "ok": bool(result.get("ok")),
        "message": result.get("message", ""),
        "provider": "azure",
        "subscription_id": result.get("subscription_id", ""),
        "subscription_name": result.get("subscription_name", ""),
        "tenant_id": result.get("tenant_id", ""),
    }


def format_precheck_line(payload: dict[str, Any], *, color: bool = False) -> str:
    if payload["ok"]:
        detail = payload["subscription_name"] or payload["subscription_id"] or "authenticated"
        return log_line("INF", f"azure precheck: ok {tag_join(detail, color=color)}", color=color)
    return log_line("ERR", f"azure precheck: failed {compact_message(payload['message'])}", color=color)


def run_precheck_once(*, json_output: bool, color: bool, silent_success: bool = False) -> bool:
    payload = precheck_payload(precheck())
    if payload["ok"] and silent_success:
        return True
    if json_output:
        emit(json.dumps(payload, sort_keys=True))
    else:
        emit(format_precheck_line(payload, color=color))
    return payload["ok"]


def selected_services_from_arg(value: str | None) -> set[str] | None:
    if not value:
        return None

    selected = {item.strip() for item in value.split(",") if item.strip()}
    unknown = sorted(selected - CLAIMABLE_SERVICES)
    if unknown:
        raise SystemExit(f"Unsupported claim services: {', '.join(unknown)}")
    return selected


def add_common_args(parser: argparse.ArgumentParser, *, defaults: bool = True, include_resource_group: bool = True) -> None:
    location_kwargs: dict[str, Any] = {"default": "auto"} if defaults else {"default": argparse.SUPPRESS}
    resource_group_kwargs: dict[str, Any] = {} if defaults else {"default": argparse.SUPPRESS}
    parser.add_argument("--location", help="Fallback Azure region when hostname does not encode one", **location_kwargs)
    if include_resource_group:
        parser.add_argument("--resource-group", help="Resource group for claim resources. Auto-generated if omitted.", **resource_group_kwargs)


def add_color_args(parser: argparse.ArgumentParser) -> None:
    color = parser.add_mutually_exclusive_group()
    color.add_argument("--color", action="store_true", help="Force color output")
    color.add_argument("--no-color", action="store_true", help="Disable color output")


def add_command_parsers(parser: argparse.ArgumentParser) -> None:
    add_common_args(parser)
    add_color_args(parser)
    subcommands = parser.add_subparsers(dest="command")

    services = subcommands.add_parser("services", help="List supported Azure service handlers")
    add_color_args(services)
    services.add_argument("--json", action="store_true", help="Print handler metadata as JSON")
    services.set_defaults(func=run_services)

    precheck_parser = subcommands.add_parser("precheck", help="Check Azure CLI and credentials")
    add_color_args(precheck_parser)
    precheck_parser.add_argument("--json", action="store_true", help="Print precheck result as JSON")
    precheck_parser.set_defaults(func=run_precheck)

    check = subcommands.add_parser("check", help="Classify Azure hostnames and check claimability")
    add_color_args(check)
    add_common_args(check, defaults=False, include_resource_group=False)
    check.add_argument("inputs", nargs="+", help="Azure hostnames or .txt input files")
    check.add_argument("--json", action="store_true", help="Print compact JSON lines")
    check.add_argument("--out", type=Path, help="Optional JSON output path")
    check.set_defaults(func=run_check)

    claim = subcommands.add_parser("claim", help="Claim supported available Azure hostnames")
    add_color_args(claim)
    add_common_args(claim, defaults=False)
    claim.add_argument("inputs", nargs="+", help="Azure hostnames or .txt input files")
    claim.add_argument("--json", action="store_true", help="Print compact JSON lines")
    claim.add_argument("--out", type=Path, help="Optional JSON output path")
    claim.add_argument("--services", help="Comma-separated claim service handlers to run")
    claim.add_argument("--cleanup", action="store_true", help="Delete the resource group after claiming")
    claim.set_defaults(func=run_claim)


def build_parser(*, prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Azure dangling-hostname claimability validator")
    add_command_parsers(parser)
    return parser


def add_provider_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subcommands.add_parser("azure", help="Validate Azure dangling-hostname claimability")
    add_command_parsers(parser)


def run_services(args: argparse.Namespace) -> int:
    services = sorted(CLAIMABLE_SERVICES)
    payload = {
        service: {
            "availability": service in AVAILABILITY_HANDLERS,
            "claim": True,
            "description": CLAIM_HANDLERS[service].description,
        }
        for service in services
    }
    color = should_color(color_mode(args))
    if not args.json:
        print_banner(color=color)
    print_services(payload, json_output=args.json, color=color)
    return 0


def run_precheck(args: argparse.Namespace) -> int:
    color = should_color(color_mode(args))
    if not args.json:
        print_banner(color=color)
    return 0 if run_precheck_once(json_output=args.json, color=color) else 1


def run_check(args: argparse.Namespace) -> int:
    targets = load_targets(args.inputs, args.location)
    color = should_color(color_mode(args))
    if not args.json:
        print_banner(color=color)
        if has_supported_targets(targets, CLAIMABLE_SERVICES) and not run_precheck_once(json_output=False, color=color):
            return 1
        emit(log_line("INF", f"azure check: {len(targets)} target{'s' if len(targets) != 1 else ''}", color=color))
    elif has_supported_targets(targets, CLAIMABLE_SERVICES) and not run_precheck_once(json_output=True, color=color, silent_success=True):
        return 1

    def on_result(item: dict[str, Any]) -> None:
        payload = check_payload(item)
        if args.json:
            emit(json.dumps(payload, sort_keys=True))
        else:
            emit(format_check_line(payload, color=color))

    results = check_targets(targets, on_result=on_result)
    if not args.json:
        payloads = [check_payload(item) for item in results]
        emit(log_line("INF", f"azure check: {format_check_summary(payloads)}", color=color))
    if args.out:
        write_json(args.out, results)
    return 0


def run_claim(args: argparse.Namespace) -> int:
    targets = load_targets(args.inputs, args.location)
    selected_services = selected_services_from_arg(args.services)
    resource_group_prefix = getattr(args, "resource_group_prefix", "rg-cloudclaim-azure")
    resource_group = args.resource_group or f"{resource_group_prefix}-{token_hex(4)}"
    color = should_color(color_mode(args))
    if not args.json:
        print_banner(color=color)
        if has_supported_targets(targets, selected_services or CLAIMABLE_SERVICES) and not run_precheck_once(json_output=False, color=color):
            return 1
        emit(log_line("INF", f"azure claim: {len(targets)} target{'s' if len(targets) != 1 else ''}", color=color))
    elif has_supported_targets(targets, selected_services or CLAIMABLE_SERVICES) and not run_precheck_once(json_output=True, color=color, silent_success=True):
        return 1

    def on_result(item: dict[str, Any], current_result: dict[str, Any]) -> None:
        payload = claim_payload(item, current_result)
        if args.json:
            emit(json.dumps(payload, sort_keys=True))
        else:
            emit(format_claim_line(payload, color=color))

    def on_cleanup(current_result: dict[str, Any]) -> None:
        payload = cleanup_payload(current_result)
        if not payload:
            return
        if args.json:
            emit(json.dumps(payload, sort_keys=True))
        else:
            emit(format_cleanup_line(payload, color=color))

    result = claim_targets(
        targets,
        resource_group=resource_group,
        fallback_location=args.location,
        selected_services=selected_services,
        cleanup=args.cleanup,
        on_result=on_result,
        on_cleanup=on_cleanup,
    )
    if not args.json:
        payloads = [claim_payload(item, result) for item in result.get("results", [])]
        claimed_count = sum(1 for payload in payloads if payload["claimed"])
        attempted_count = sum(1 for payload in payloads if payload["claim_attempted"])
        emit(log_line("INF", f"azure claim: {claimed_count}/{len(payloads)} claimed, {attempted_count}/{len(payloads)} attempted", color=color))
    if args.out:
        write_json(args.out, result)
    return 0


def dispatch(args: argparse.Namespace) -> int:
    if hasattr(args, "func"):
        return args.func(args)
    return 2


def color_mode(args: argparse.Namespace) -> str:
    if getattr(args, "color", False):
        return "always"
    if getattr(args, "no_color", False):
        return "never"
    return "auto"
