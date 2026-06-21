"""Cloud provider implementations for CloudClaim."""

from .azure import PROVIDER as AZURE_PROVIDER
from .aws import PROVIDER as AWS_PROVIDER


PROVIDERS = [AZURE_PROVIDER, AWS_PROVIDER]
PROVIDERS_BY_NAME = {provider.name: provider for provider in PROVIDERS}
