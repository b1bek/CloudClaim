from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import AwsTarget

AWS_REGION_RE = r"[a-z]{2}(?:-gov)?-[a-z]+-\d"
ELASTIC_BEANSTALK_RE = re.compile(
    rf"^(?P<name>[a-z0-9][a-z0-9-]{{2,61}}[a-z0-9])\.(?P<region>{AWS_REGION_RE})\.elasticbeanstalk\.com$",
    re.I,
)
ELASTIC_BEANSTALK_DESCENDANT_RE = re.compile(
    rf"^(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?P<name>[a-z0-9][a-z0-9-]{{2,61}}[a-z0-9])\.(?P<region>{AWS_REGION_RE})\.elasticbeanstalk\.com$",
    re.I,
)


def normalize_hostname(value: str) -> str:
    value = value.strip().strip(".")
    if "://" in value:
        value = urlsplit(value).hostname or value
    return value.lower().strip(".")


def classify_hostname(hostname: str, source_host: str = "", source: str = "") -> AwsTarget | None:
    host = normalize_hostname(hostname)
    if not host or host == "*" or host.startswith("*."):
        return None

    elastic_beanstalk = ELASTIC_BEANSTALK_RE.match(host) or ELASTIC_BEANSTALK_DESCENDANT_RE.match(host)
    if elastic_beanstalk:
        name = elastic_beanstalk.group("name")
        region = elastic_beanstalk.group("region")
        claim_hostname = f"{name}.{region}.elasticbeanstalk.com"
        return AwsTarget(
            service="elastic_beanstalk",
            hostname=claim_hostname,
            name=name,
            region=region,
            source_host=source_host or (host if host != claim_hostname else ""),
            source=source,
        )

    return None


def target_key(target: AwsTarget) -> tuple[str, str, str]:
    return target.service, target.name, target.region
