from __future__ import annotations

from urllib.parse import urlsplit

from .catalog import SERVICE_SPECS
from .models import AzureTarget


def normalize_hostname(value: str) -> str:
    value = value.strip().strip(".")
    if "://" in value:
        value = urlsplit(value).hostname or value
    return value.lower().strip(".")


def derive_name_and_location(service: str, hostname: str, fallback_location: str) -> tuple[str, str]:
    labels = hostname.split(".")
    first = labels[0]

    if service == "public_ip_dns_label" and len(labels) >= 2:
        return labels[0], labels[1]
    if service == "app_service":
        return first, fallback_location
    return first, fallback_location


def classify_hostname(
    hostname: str,
    fallback_location: str,
    source_host: str = "",
    source: str = "",
) -> AzureTarget | None:
    host = normalize_hostname(hostname)
    if not host or host == "*" or host.startswith("*.") or "privatelink.invalid" in host:
        return None

    for spec in SERVICE_SPECS:
        if spec.pattern.match(host):
            name, location = derive_name_and_location(spec.name, host, fallback_location)
            return AzureTarget(
                service=spec.name,
                azure_hostname=host,
                name=name,
                location=location,
                source_host=source_host,
                source=source,
            )
    return None


def target_key(target: AzureTarget) -> tuple[str, str, str]:
    return target.service, target.name, target.location
