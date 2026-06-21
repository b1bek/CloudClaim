"""Azure provider for CloudClaim."""

from cloudclaim.core.providers import Provider

from .commands import add_provider_parser, dispatch


PROVIDER = Provider(
    name="azure",
    resource_group_prefix="rg-cloudclaim-azure",
    add_parser=add_provider_parser,
    dispatch=dispatch,
)
