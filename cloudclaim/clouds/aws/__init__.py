"""AWS provider for CloudClaim."""

from cloudclaim.core.providers import Provider

from .commands import add_provider_parser, dispatch


PROVIDER = Provider("aws", "cloudclaim-aws", add_provider_parser, dispatch)
