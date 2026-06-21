from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from secrets import token_hex
from typing import Any

from .availability import check_target
from .client import aws_json, require_aws
from .models import AwsClaimOptions, AwsTarget, ClaimHandler
from .services import target_key


CLAIMABLE_SERVICES = {"elastic_beanstalk"}


def compact_env_name(name: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in name.lower()).strip("-")
    stem = stem[:24].strip("-") or "target"
    return f"cc-{stem}-{token_hex(4)}"[:40].strip("-")


def message_from_response(data: dict[str, Any]) -> str:
    return str(data.get("stderr") or data.get("error") or data.get("message") or data)


def classify_claim_error(message: str) -> tuple[str, str]:
    normalized = message.lower()
    if "not available" in normalized or "already exists" in normalized:
        return "not_available", ""
    if "quota" in normalized or "limitexceeded" in normalized or "current limit" in normalized:
        return "quota", "AWS quota blocked proof resource creation. Use an account/region with Elastic Beanstalk capacity."
    if "accessdenied" in normalized or "not authorized" in normalized or "is not authorized" in normalized:
        return "permission", "AWS credentials do not have enough Elastic Beanstalk permissions for proof resource creation."
    return "", ""


def ensure_application(name: str, region: str, profile: str | None) -> None:
    ok, data = aws_json(
        [
            "elasticbeanstalk",
            "create-application",
            "--application-name",
            name,
            "--description",
            "CloudClaim proof application",
        ],
        region=region,
        profile=profile,
        timeout=60,
    )
    if ok:
        return

    message = message_from_response(data).lower()
    if "already exists" in message:
        return
    require_aws(ok, data, "create Elastic Beanstalk application")


def select_solution_stack(region: str, profile: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit

    ok, data = aws_json(["elasticbeanstalk", "list-available-solution-stacks"], region=region, profile=profile, timeout=60)
    require_aws(ok, data, "list Elastic Beanstalk solution stacks")
    stacks = [str(stack) for stack in data.get("SolutionStacks", []) if stack]
    if not stacks:
        raise RuntimeError("list Elastic Beanstalk solution stacks returned no stacks")

    preferences = (
        ("Amazon Linux 2023", "running Python"),
        ("Amazon Linux", "running Python"),
        ("running Python",),
        ("Amazon Linux 2023", "running Node.js"),
        ("running Node.js",),
    )
    for terms in preferences:
        for stack in stacks:
            if all(term in stack for term in terms):
                return stack

    for stack in stacks:
        if "Windows" not in stack:
            return stack
    return stacks[0]


def claim_elastic_beanstalk(target: AwsTarget, options: AwsClaimOptions) -> dict[str, Any]:
    ensure_application(options.application_name, target.region, options.profile)
    solution_stack = select_solution_stack(target.region, options.profile, options.solution_stack_name)
    environment_name = compact_env_name(target.name)
    ok, data = aws_json(
        [
            "elasticbeanstalk",
            "create-environment",
            "--application-name",
            options.application_name,
            "--environment-name",
            environment_name,
            "--cname-prefix",
            target.name,
            "--solution-stack-name",
            solution_stack,
            "--tier",
            "Name=WebServer,Type=Standard",
            "--option-settings",
            "Namespace=aws:elasticbeanstalk:environment,OptionName=EnvironmentType,Value=SingleInstance",
            "Namespace=aws:autoscaling:launchconfiguration,OptionName=InstanceType,Value=t3.micro",
            "--tags",
            "Key=CreatedBy,Value=CloudClaim",
            f"Key=CloudClaimTarget,Value={target.hostname}",
        ],
        region=target.region,
        profile=options.profile,
        timeout=180,
    )
    require_aws(ok, data, "create Elastic Beanstalk environment")
    return {
        "service": target.service,
        "application_name": options.application_name,
        "environment_name": environment_name,
        "name": target.name,
        "region": target.region,
        "solution_stack": solution_stack,
        "cname": data.get("CNAME", ""),
        "environment_id": data.get("EnvironmentId", ""),
        "result": data,
    }


CLAIM_HANDLERS: dict[str, ClaimHandler] = {
    "elastic_beanstalk": ClaimHandler(
        "elastic_beanstalk",
        "Create Elastic Beanstalk environment with matching CNAME prefix",
        claim_elastic_beanstalk,
    ),
}


def terminate_environment(environment_name: str, region: str, profile: str | None) -> tuple[bool, str]:
    ok, data = aws_json(
        ["elasticbeanstalk", "terminate-environment", "--environment-name", environment_name, "--terminate-resources"],
        region=region,
        profile=profile,
        timeout=120,
    )
    if ok:
        return True, ""
    return False, message_from_response(data)


def claim_targets(
    targets: list[AwsTarget],
    options: AwsClaimOptions,
    selected_services: set[str] | None,
    cleanup: bool,
    on_result: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    on_cleanup: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": "claim",
        "profile": options.profile or "",
        "application_name": options.application_name,
        "cleanup_requested": cleanup,
        "selected_services": sorted(selected_services) if selected_services else sorted(CLAIMABLE_SERVICES),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "results": [],
    }
    seen: set[tuple[str, str, str]] = set()

    try:
        for target in targets:
            entry = check_target(target, options.profile)
            key = target_key(target)
            if target.service == "unsupported":
                entry.update({"status": "unsupported"})
            elif key in seen:
                entry.update({"status": "duplicate", "message": "same service/name/region already processed"})
            elif selected_services and target.service not in selected_services:
                entry.update({"status": "skipped_service", "message": "service not selected"})
            elif target.service not in CLAIM_HANDLERS:
                entry.update({"status": "unsupported_claim", "message": "no claim handler for this AWS service"})
            elif entry.get("registration_status") != "available":
                entry.update({"status": "not_claimed", "message": "AWS availability check did not return available"})
            else:
                seen.add(key)
                handler = CLAIM_HANDLERS[target.service]
                try:
                    created = handler.create(target, options)
                    entry.update({"status": "claimed", "created": created})
                except Exception as exc:
                    reason, hint = classify_claim_error(str(exc))
                    if reason == "not_available":
                        entry.update(
                            {
                                "status": "not_claimed",
                                "registration_available": False,
                                "registration_status": "not_available",
                                "message": "AWS reported the name is not available",
                            }
                        )
                    else:
                        entry.update({"status": "claim_failed", "message": str(exc), "failure_reason": reason, "hint": hint})

            result["results"].append(entry)
            if on_result:
                on_result(entry, result)

        result["finished_at_utc"] = datetime.now(UTC).isoformat()
        return result
    finally:
        if cleanup:
            cleanup_results = []
            for entry in result.get("results", []):
                created = entry.get("created") if isinstance(entry, dict) else None
                if not isinstance(created, dict) or not created.get("environment_name"):
                    continue
                ok, message = terminate_environment(str(created["environment_name"]), str(created.get("region") or ""), options.profile)
                cleanup_results.append(
                    {
                        "environment_name": created["environment_name"],
                        "region": created.get("region", ""),
                        "cleanup_started": ok,
                        "cleanup_error": message,
                    }
                )

            if cleanup_results:
                result["cleanup_results"] = cleanup_results
                result["cleanup_started"] = all(item["cleanup_started"] for item in cleanup_results)
                if on_cleanup:
                    on_cleanup(result)
