from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AzureServiceSpec:
    name: str
    pattern: re.Pattern[str]
    availability_provider: str = ""
    availability_description: str = ""
    claim_description: str = ""
    storage: bool = False


SERVICE_SPECS = (
    AzureServiceSpec(
        "app_service",
        re.compile(r"^[a-z0-9-]+\.azurewebsites\.net$", re.I),
        availability_provider="Microsoft.Web/sites",
        availability_description="App Service app name",
        claim_description="Create F1 App Service plan and app",
    ),
    AzureServiceSpec(
        "public_ip_dns_label",
        re.compile(r"^[a-z0-9-]+\.[a-z0-9-]+\.cloudapp\.azure\.com$", re.I),
        availability_provider="Microsoft.Network/publicIPAddresses/dnsSettings",
        availability_description="Public IP DNS label",
        claim_description="Create Standard Public IP with DNS label",
    ),
    AzureServiceSpec(
        "traffic_manager",
        re.compile(r"^[a-z0-9-]+\.trafficmanager\.net$", re.I),
        availability_provider="Microsoft.Network/trafficManagerProfiles",
        availability_description="Traffic Manager relative DNS name",
        claim_description="Create Traffic Manager profile with matching DNS name",
    ),
    AzureServiceSpec(
        "api_management",
        re.compile(r"^[a-z0-9-]+\.azure-api\.net$", re.I),
        availability_provider="Microsoft.ApiManagement/service",
        availability_description="API Management service name",
        claim_description="Create Consumption API Management service",
    ),
    AzureServiceSpec(
        "blob_storage",
        re.compile(r"^[a-z0-9-]+\.blob\.core\.windows\.net$", re.I),
        availability_provider="Microsoft.Storage/storageAccounts",
        availability_description="Storage account name",
        claim_description="Create matching Storage account",
        storage=True,
    ),
    AzureServiceSpec(
        "static_website_storage",
        re.compile(r"^[a-z0-9-]+\.web\.core\.windows\.net$", re.I),
        availability_provider="Microsoft.Storage/storageAccounts",
        availability_description="Storage account name",
        claim_description="Create matching Storage account",
        storage=True,
    ),
    AzureServiceSpec(
        "file_storage",
        re.compile(r"^[a-z0-9-]+\.file\.core\.windows\.net$", re.I),
        availability_provider="Microsoft.Storage/storageAccounts",
        availability_description="Storage account name",
        claim_description="Create matching Storage account",
        storage=True,
    ),
    AzureServiceSpec(
        "queue_storage",
        re.compile(r"^[a-z0-9-]+\.queue\.core\.windows\.net$", re.I),
        availability_provider="Microsoft.Storage/storageAccounts",
        availability_description="Storage account name",
        claim_description="Create matching Storage account",
        storage=True,
    ),
    AzureServiceSpec(
        "table_storage",
        re.compile(r"^[a-z0-9-]+\.table\.core\.windows\.net$", re.I),
        availability_provider="Microsoft.Storage/storageAccounts",
        availability_description="Storage account name",
        claim_description="Create matching Storage account",
        storage=True,
    ),
)

SERVICE_BY_NAME = {spec.name: spec for spec in SERVICE_SPECS}
STORAGE_SERVICES = {spec.name for spec in SERVICE_SPECS if spec.storage}
