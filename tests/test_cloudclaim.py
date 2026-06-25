from __future__ import annotations

from argparse import Namespace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cloudclaim.clouds.azure.commands import build_parser, run_check, run_claim, run_precheck, run_services, selected_services_from_arg
from cloudclaim.clouds.azure.availability import (
    AVAILABILITY_HANDLERS,
    check_api_management,
    check_target,
    check_targets,
    check_traffic_manager,
    normalize_availability,
)
from cloudclaim.clouds.azure.claims import (
    CLAIMABLE_SERVICES,
    CLAIM_HANDLERS,
    claim_api_management,
    claim_app_service,
    claim_targets,
    claim_traffic_manager,
    classify_claim_error,
)
from cloudclaim.clouds.azure.client import precheck as azure_precheck
from cloudclaim.clouds.azure.inputs import load_targets
from cloudclaim.clouds.azure.models import AzureTarget, ClaimHandler
from cloudclaim.clouds.azure.output import print_check_results, print_claim_result
from cloudclaim.clouds.azure.services import classify_hostname, normalize_hostname
from cloudclaim.core.output import print_banner, should_color, tag


class HostnameClassificationTests(unittest.TestCase):
    def test_normalizes_urls_and_case(self) -> None:
        self.assertEqual(normalize_hostname("HTTPS://Cc-Test-App.AzureWebsites.Net/path"), "cc-test-app.azurewebsites.net")

    def test_ignores_regional_app_service_stamp_hostname(self) -> None:
        self.assertIsNone(classify_hostname("cc-test-app-stamp.westeurope-01.azurewebsites.net", "eastus"))

    def test_classifies_global_app_service(self) -> None:
        target = classify_hostname("cc-test-app.azurewebsites.net", "eastus")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.service, "app_service")
        self.assertEqual(target.name, "cc-test-app")
        self.assertEqual(target.location, "eastus")

    def test_classifies_public_ip_dns_label_location(self) -> None:
        target = classify_hostname("cc-test-label.eastus.cloudapp.azure.com", "westus")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.service, "public_ip_dns_label")
        self.assertEqual(target.name, "cc-test-label")
        self.assertEqual(target.location, "eastus")

    def test_classifies_traffic_manager(self) -> None:
        target = classify_hostname("cc-test-tm.trafficmanager.net", "auto")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.service, "traffic_manager")
        self.assertEqual(target.name, "cc-test-tm")
        self.assertEqual(target.location, "auto")

    def test_classifies_api_management(self) -> None:
        target = classify_hostname("cc-test-apim.azure-api.net", "eastus2")
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.service, "api_management")
        self.assertEqual(target.name, "cc-test-apim")
        self.assertEqual(target.location, "eastus2")

    def test_unsupported_azure_hostname_is_not_classified(self) -> None:
        self.assertIsNone(
            classify_hostname(
                "cc-test-container.internal.cc-test-env.westeurope.azurecontainerapps.io",
                "auto",
            )
        )

    def test_azureedge_is_not_classified(self) -> None:
        self.assertIsNone(classify_hostname("cc-test-edge.azureedge.net", "auto"))
        self.assertIsNone(classify_hostname("cdnverify.cc-test-edge.azureedge.net", "auto"))
        self.assertIsNone(classify_hostname("child.cc-test-edge.azureedge.net", "auto"))

    def test_ignores_wildcards(self) -> None:
        self.assertIsNone(classify_hostname("*.trafficmanager.net", "eastus"))


class InputParsingTests(unittest.TestCase):
    def test_load_targets_reads_plain_text_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hosts.txt"
            path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "hostname",
                        "cc-test-tm-file.trafficmanager.net",
                        "not-azure.example.com",
                    ]
                ),
                encoding="utf-8",
            )

            targets = load_targets([str(path)], "auto")

        self.assertEqual(
            [target.azure_hostname for target in targets],
            ["cc-test-tm-file.trafficmanager.net", "not-azure.example.com"],
        )
        self.assertEqual([target.service for target in targets], ["traffic_manager", "unsupported"])

    def test_load_targets_rejects_non_txt_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hosts.json"
            path.write_text('["cc-test-app.azurewebsites.net"]', encoding="utf-8")

            with self.assertRaises(SystemExit):
                load_targets([str(path)], "auto")

    def test_direct_regional_app_service_input_is_unsupported(self) -> None:
        targets = load_targets(["cc-test-app-stamp.westeurope-01.azurewebsites.net"], "auto")

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].service, "unsupported")
        self.assertEqual(targets[0].azure_hostname, "cc-test-app-stamp.westeurope-01.azurewebsites.net")


class OutputFormattingTests(unittest.TestCase):
    def test_location_defaults_to_auto(self) -> None:
        parser = build_parser(prog="cloudclaim azure")
        args = parser.parse_args(["check", "cc-test-app.azurewebsites.net"])

        self.assertEqual(args.location, "auto")

    def test_location_can_be_set_after_command(self) -> None:
        parser = build_parser(prog="cloudclaim azure")
        args = parser.parse_args(["claim", "cc-test-app.azurewebsites.net", "--location", "westus"])

        self.assertEqual(args.location, "westus")

    def test_location_can_be_set_before_command(self) -> None:
        parser = build_parser(prog="cloudclaim azure")
        args = parser.parse_args(["--location", "westus2", "claim", "cc-test-app.azurewebsites.net"])

        self.assertEqual(args.location, "westus2")

    def test_services_output_lists_only_claimable_services(self) -> None:
        output = io.StringIO()
        args = Namespace(json=True, color=False, no_color=True)

        with redirect_stdout(output):
            self.assertEqual(run_services(args), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(set(payload), CLAIMABLE_SERVICES)
        self.assertEqual(set(payload), set(CLAIM_HANDLERS))

    def test_selected_services_rejects_not_claimable_services(self) -> None:
        with self.assertRaises(SystemExit):
            selected_services_from_arg("made_up_service")

    def test_precheck_outputs_json(self) -> None:
        output = io.StringIO()
        args = Namespace(json=True, color=False, no_color=True)

        with redirect_stdout(output), patch(
            "cloudclaim.clouds.azure.commands.precheck",
            return_value={
                "ok": True,
                "provider": "azure",
                "account": "user@example.com",
                "subscription_id": "sub",
                "subscription_name": "Subscription",
                "tenant_id": "tenant",
            },
        ):
            self.assertEqual(run_precheck(args), 0)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subscription_id"], "sub")

    def test_client_precheck_reports_success(self) -> None:
        with patch(
            "cloudclaim.clouds.azure.client.az_json",
            return_value=(True, {"id": "sub", "name": "Subscription", "tenantId": "tenant", "user": {"name": "user@example.com"}}),
        ):
            result = azure_precheck()

        self.assertTrue(result["ok"])
        self.assertEqual(result["subscription_id"], "sub")
        self.assertEqual(result["account"], "user@example.com")

    def test_client_precheck_reports_failure(self) -> None:
        with patch("cloudclaim.clouds.azure.client.az_json", return_value=(False, {"stderr": "please run az login"})):
            result = azure_precheck()

        self.assertFalse(result["ok"])
        self.assertIn("az login", result["message"])

    def test_print_check_results_outputs_normal_text_by_default(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                        "azure_service": "public_ip_dns_label",
                        "registration_available": True,
                        "registration_checked_location": "eastus",
                        "registration_checked_name": "cc-test-label",
                    }
                ]
            )

        text = output.getvalue()
        self.assertIn("[INF] azure check: 1/1 available", text)
        self.assertIn(
            "cc-test-label.eastus.cloudapp.azure.com [available] [azure] [public_ip_dns_label]",
            text,
        )

    def test_print_check_results_can_color_tags(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                        "azure_service": "public_ip_dns_label",
                        "registration_available": True,
                        "registration_checked_location": "eastus",
                        "registration_checked_name": "cc-test-label",
                    }
                ],
                color=True,
            )

        self.assertIn("\033[", output.getvalue())
        self.assertIn("[available]", output.getvalue())

    def test_print_banner_can_color_name(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_banner(color=True)

        text = output.getvalue()
        self.assertIn("\033[", text)
        self.assertIn("____", text)
        self.assertIn("by @b1bek", text)

    def test_print_check_results_outputs_json_when_requested(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                        "azure_service": "public_ip_dns_label",
                        "registration_available": True,
                        "registration_checked_location": "eastus",
                        "registration_checked_name": "cc-test-label",
                    }
                ],
                json_output=True,
            )

        payload = json.loads(output.getvalue())
        self.assertIs(payload["available"], True)
        self.assertEqual(payload["hostname"], "cc-test-label.eastus.cloudapp.azure.com")

    def test_print_check_results_treats_unknown_availability_as_false(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results([{"azure_hostname": "unknown.example.com", "registration_available": ""}], json_output=True)

        payload = json.loads(output.getvalue())
        self.assertIs(payload["available"], False)

    def test_print_check_results_reports_unsupported_as_unsupported(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "azure_hostname": "cc-test-container.internal.cc-test-env.westeurope.azurecontainerapps.io",
                        "azure_service": "unsupported",
                        "registration_available": "",
                        "registration_status": "unsupported",
                    }
                ]
            )

        self.assertIn(
            "cc-test-container.internal.cc-test-env.westeurope.azurecontainerapps.io [unsupported] [azure] [unsupported]",
            output.getvalue(),
        )

    def test_print_check_results_keeps_not_available_simple(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "azure_hostname": "cc-test-label-used.eastus.cloudapp.azure.com",
                        "azure_service": "public_ip_dns_label",
                        "registration_available": False,
                        "registration_checked_location": "eastus",
                        "registration_checked_name": "cc-test-label-used",
                        "registration_status": "not_available",
                    }
                ]
            )

        text = output.getvalue()
        self.assertIn("[INF] azure check: 0/1 available", text)
        self.assertIn("cc-test-label-used.eastus.cloudapp.azure.com [not-available] [azure] [public_ip_dns_label]", text)

    def test_print_claim_result_outputs_normal_text_by_default(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                            "azure_service": "public_ip_dns_label",
                            "registration_available": True,
                            "registration_checked_location": "eastus",
                            "registration_checked_name": "cc-test-label",
                            "status": "claimed",
                        }
                    ],
                    "cleanup_started": True,
                    "cleanup_command": "az group delete -n rg-cloudclaim-azure-test --yes --no-wait",
                }
            )

        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], "[INF] azure claim: 1/1 claimed, 1/1 attempted")
        self.assertIn(
            "cc-test-label.eastus.cloudapp.azure.com [claimed] [azure] [public_ip_dns_label] [rg:rg-cloudclaim-azure-test]",
            output.getvalue(),
        )
        self.assertNotIn("cleanup failed", output.getvalue())
        self.assertNotIn("az group delete -n rg-cloudclaim-azure-test --yes --no-wait", output.getvalue())

    def test_print_claim_result_simplifies_not_available_output(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label-unavailable.eastus.cloudapp.azure.com",
                            "azure_service": "public_ip_dns_label",
                            "registration_available": False,
                            "registration_checked_location": "eastus",
                            "registration_checked_name": "cc-test-label-unavailable",
                            "registration_status": "not_available",
                            "status": "not_claimed",
                            "message": "Azure availability check did not return available",
                        }
                    ],
                }
            )

        text = output.getvalue()
        self.assertIn("cc-test-label-unavailable.eastus.cloudapp.azure.com [not-available] [azure] [public_ip_dns_label]", text)
        self.assertNotIn("[cc-test-label-unavailable]", text)
        self.assertNotIn("[eastus]", text)
        self.assertNotIn("Azure availability check did not return available", text)

    def test_print_claim_result_reports_unsupported_before_not_available(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-container.internal.cc-test-env.westeurope.azurecontainerapps.io",
                            "azure_service": "unsupported",
                            "registration_available": "",
                            "registration_checked_location": "westeurope",
                            "registration_checked_name": "cc-test-container",
                            "registration_status": "unsupported",
                            "status": "unsupported_claim",
                            "message": "no claim handler for this Azure service",
                        }
                    ],
                }
            )

        text = output.getvalue()
        self.assertIn(
            "cc-test-container.internal.cc-test-env.westeurope.azurecontainerapps.io [unsupported] [azure] [unsupported]",
            text,
        )
        self.assertNotIn("[not-available]", text)

    def test_print_claim_result_simplifies_create_time_not_available_output(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label-01.eastus.cloudapp.azure.com",
                            "azure_service": "public_ip_dns_label",
                            "registration_available": False,
                            "registration_checked_location": "eastus",
                            "registration_checked_name": "cc-test-label-01",
                            "registration_status": "not_available",
                            "status": "not_claimed",
                            "claim_attempted": True,
                            "message": "Azure reported the name is not available",
                        }
                    ],
                }
            )

        text = output.getvalue()
        self.assertIn("[INF] azure claim: 0/1 claimed, 1/1 attempted", text)
        self.assertIn("cc-test-label-01.eastus.cloudapp.azure.com [not-available] [azure] [public_ip_dns_label]", text)
        self.assertNotIn("[claim:failed]", text)
        self.assertNotIn("[rg:rg-cloudclaim-azure-test]", text)
        self.assertNotIn("Azure reported the name is not available", text)

    def test_print_claim_result_includes_failure_reason(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-app-quota.azurewebsites.net",
                            "azure_service": "app_service",
                            "registration_available": True,
                            "registration_checked_location": "eastus",
                            "registration_checked_name": "cc-test-app-quota",
                            "registration_status": "available",
                            "status": "claim_failed",
                            "failure_reason": "quota",
                            "hint": "Azure quota blocked proof resource creation. Use a region/subscription with App Service quota, or pass --location to force a known-good region.",
                            "message": "create App Service plan failed: quota exceeded",
                        }
                    ],
                }
            )

        self.assertIn(
            "cc-test-app-quota.azurewebsites.net [failed] [azure] [app_service] [rg:rg-cloudclaim-azure-test] [claim:failed] [quota] [region:eastus] create App Service plan failed: quota exceeded",
            output.getvalue(),
        )
        self.assertIn("[hint] Azure quota blocked proof resource creation.", output.getvalue())

    def test_print_claim_result_mentions_cleanup_started_only_when_requested(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                            "registration_available": True,
                            "status": "claimed",
                        }
                    ],
                    "cleanup_started": True,
                    "cleanup_command": "az group delete -n rg-cloudclaim-azure-test --yes --no-wait",
                }
            )

        self.assertIn("[INF] cleanup started: rg-cloudclaim-azure-test", output.getvalue())

    def test_print_claim_result_mentions_cleanup_failure(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                            "registration_available": True,
                            "status": "claimed",
                        }
                    ],
                    "cleanup_started": False,
                    "cleanup_command": "az group delete -n rg-cloudclaim-azure-test --yes --no-wait",
                    "cleanup_error": "permission denied",
                }
            )

        self.assertIn("[WRN] cleanup failed: rg-cloudclaim-azure-test [permission denied]", output.getvalue())
        self.assertIn("permission denied", output.getvalue())

    def test_color_helpers_respect_modes(self) -> None:
        self.assertTrue(should_color("always"))
        self.assertFalse(should_color("never"))
        self.assertTrue(should_color("auto"))
        self.assertEqual(tag("available", color=False), "[available]")
        self.assertIn("\033[", tag("available", color=True))

    def test_print_claim_result_outputs_json_when_requested(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                            "azure_service": "public_ip_dns_label",
                            "registration_available": True,
                            "registration_checked_location": "eastus",
                            "registration_checked_name": "cc-test-label",
                            "status": "claimed",
                        }
                    ],
                    "cleanup_started": True,
                    "cleanup_command": "az group delete -n rg-cloudclaim-azure-test --yes --no-wait",
                },
                json_output=True,
            )

        lines = output.getvalue().splitlines()
        claim_payload = json.loads(lines[0])
        cleanup_payload = json.loads(lines[1])
        self.assertIs(claim_payload["claimed"], True)
        self.assertIs(claim_payload["available"], True)
        self.assertIs(claim_payload["checked"], True)
        self.assertIs(claim_payload["claim_attempted"], True)
        self.assertEqual(claim_payload["status"], "claimed")
        self.assertIs(cleanup_payload["cleanup_started"], True)

    def test_print_claim_result_reports_unclaimed_as_false(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "resource_group": "rg-cloudclaim-azure-test",
                    "results": [
                        {
                            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
                            "registration_available": False,
                            "registration_status": "not_available",
                            "status": "not_claimed",
                            "message": "Azure availability check did not return available",
                        }
                    ],
                },
                json_output=True,
            )

        payload = json.loads(output.getvalue())
        self.assertIs(payload["claimed"], False)
        self.assertIs(payload["available"], False)
        self.assertIs(payload["checked"], True)
        self.assertIs(payload["claim_attempted"], False)
        self.assertEqual(payload["status"], "not_claimed")

    def test_run_check_streams_results_before_backend_returns(self) -> None:
        output = io.StringIO()
        item = {
            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
            "azure_service": "public_ip_dns_label",
            "registration_available": True,
            "registration_checked_location": "eastus",
            "registration_checked_name": "cc-test-label",
            "registration_status": "available",
        }

        def fake_check_targets(targets, on_result=None):
            self.assertIn("azure check: 1 target", output.getvalue())
            assert on_result is not None
            on_result(item)
            self.assertIn("cc-test-label.eastus.cloudapp.azure.com [available] [azure] [public_ip_dns_label]", output.getvalue())
            return [item]

        args = Namespace(inputs=["cc-test-label.eastus.cloudapp.azure.com"], location="eastus", json=False, out=None, color=False, no_color=True)
        with (
            redirect_stdout(output),
            patch("cloudclaim.clouds.azure.commands.load_targets", return_value=[object()]),
            patch("cloudclaim.clouds.azure.commands.check_targets", side_effect=fake_check_targets),
        ):
            self.assertEqual(run_check(args), 0)

    def test_run_check_prechecks_supported_targets(self) -> None:
        output = io.StringIO()
        target = AzureTarget("public_ip_dns_label", "cc-test-label.eastus.cloudapp.azure.com", "cc-test-label", "eastus")

        with (
            redirect_stdout(output),
            patch("cloudclaim.clouds.azure.commands.load_targets", return_value=[target]),
            patch("cloudclaim.clouds.azure.commands.precheck", return_value={"ok": True, "provider": "azure", "subscription_id": "sub", "subscription_name": "Subscription"}),
            patch("cloudclaim.clouds.azure.commands.check_targets", return_value=[]),
        ):
            self.assertEqual(run_check(Namespace(inputs=["cc-test-label.eastus.cloudapp.azure.com"], location="eastus", json=False, out=None, color=False, no_color=True)), 0)

        self.assertIn("[INF] azure precheck: ok [Subscription]", output.getvalue())

    def test_run_check_skips_precheck_for_unsupported_only(self) -> None:
        output = io.StringIO()
        target = AzureTarget("unsupported", "cc-test-frontdoor.azurefd.net", "", "auto")

        with (
            redirect_stdout(output),
            patch("cloudclaim.clouds.azure.commands.load_targets", return_value=[target]),
            patch("cloudclaim.clouds.azure.commands.precheck") as precheck_mock,
            patch("cloudclaim.clouds.azure.commands.check_targets", return_value=[]),
        ):
            self.assertEqual(run_check(Namespace(inputs=["cc-test-frontdoor.azurefd.net"], location="auto", json=False, out=None, color=False, no_color=True)), 0)

        precheck_mock.assert_not_called()

    def test_run_claim_streams_results_before_backend_returns(self) -> None:
        output = io.StringIO()
        item = {
            "azure_hostname": "cc-test-label.eastus.cloudapp.azure.com",
            "azure_service": "public_ip_dns_label",
            "registration_available": True,
            "registration_checked_location": "eastus",
            "registration_checked_name": "cc-test-label",
            "registration_status": "available",
            "status": "claimed",
        }

        def fake_claim_targets(*args, **kwargs):
            self.assertIn("azure claim: 1 target", output.getvalue())
            current_result = {"resource_group": "rg-cloudclaim-azure-test", "results": [item]}
            kwargs["on_result"](item, current_result)
            self.assertIn(
                "cc-test-label.eastus.cloudapp.azure.com [claimed] [azure] [public_ip_dns_label] [rg:rg-cloudclaim-azure-test]",
                output.getvalue(),
            )
            return current_result

        args = Namespace(
            inputs=["cc-test-label.eastus.cloudapp.azure.com"],
            location="eastus",
            resource_group="rg-cloudclaim-azure-test",
            services=None,
            cleanup=False,
            json=False,
            out=None,
            color=False,
            no_color=True,
        )
        with (
            redirect_stdout(output),
            patch("cloudclaim.clouds.azure.commands.load_targets", return_value=[object()]),
            patch("cloudclaim.clouds.azure.commands.claim_targets", side_effect=fake_claim_targets),
        ):
            self.assertEqual(run_claim(args), 0)


class ClaimCleanupBehaviorTests(unittest.TestCase):
    def test_made_up_service_is_not_supported(self) -> None:
        self.assertNotIn("made_up_service", AVAILABILITY_HANDLERS)
        self.assertNotIn("made_up_service", CLAIM_HANDLERS)

    def test_check_traffic_manager_uses_subscription_scoped_provider_dns_availability(self) -> None:
        target = AzureTarget(
            service="traffic_manager",
            azure_hostname="cc-test-tm.trafficmanager.net",
            name="cc-test-tm",
            location="auto",
        )

        with patch("cloudclaim.clouds.azure.availability.az_json", return_value=(True, {"nameAvailable": True})) as az_json:
            result = check_traffic_manager(target, "sub")

        az_json.assert_called_once_with(
            [
                "rest",
                "--method",
                "post",
                "--url",
                "https://management.azure.com/subscriptions/sub/providers/Microsoft.Network/checkTrafficManagerNameAvailabilityV2?api-version=2022-04-01",
                "--body",
                '{"name": "cc-test-tm", "type": "microsoft.network/trafficmanagerprofiles"}',
            ],
            timeout=60,
        )
        self.assertEqual(result["registration_provider"], "Microsoft.Network/trafficManagerProfiles")
        self.assertEqual(result["registration_status"], "available")
        self.assertIs(result["registration_available"], True)

    def test_check_api_management_uses_provider_name_availability(self) -> None:
        target = AzureTarget(
            service="api_management",
            azure_hostname="cc-test-apim.azure-api.net",
            name="cc-test-apim",
            location="auto",
        )

        with patch("cloudclaim.clouds.azure.availability.az_json", return_value=(True, {"nameAvailable": True})) as az_json:
            result = check_api_management(target, "sub")

        az_json.assert_called_once_with(["apim", "check-name", "--name", "cc-test-apim"], timeout=60)
        self.assertEqual(result["registration_provider"], "Microsoft.ApiManagement/service")
        self.assertEqual(result["registration_status"], "available")
        self.assertIs(result["registration_available"], True)

    def test_claim_traffic_manager_creates_profile_with_unique_dns_name(self) -> None:
        target = AzureTarget(
            service="traffic_manager",
            azure_hostname="cc-test-tm.trafficmanager.net",
            name="cc-test-tm",
            location="auto",
        )

        with patch("cloudclaim.clouds.azure.claims.az_json", return_value=(True, {"name": "cc-test-tm"})) as az_json:
            result = claim_traffic_manager(target, "rg-test", "auto")

        args = az_json.call_args.args[0]
        self.assertEqual(args[:4], ["network", "traffic-manager", "profile", "create"])
        self.assertEqual(args[args.index("-g") + 1], "rg-test")
        self.assertEqual(args[args.index("-n") + 1], "cc-test-tm")
        self.assertEqual(args[args.index("--unique-dns-name") + 1], "cc-test-tm")
        self.assertEqual(args[args.index("--routing-method") + 1], "Priority")
        self.assertEqual(result["location"], "global")

    def test_claim_api_management_creates_consumption_service(self) -> None:
        target = AzureTarget(
            service="api_management",
            azure_hostname="cc-test-apim.azure-api.net",
            name="cc-test-apim",
            location="westus2",
        )

        with patch("cloudclaim.clouds.azure.claims.az_json", return_value=(True, {"name": "cc-test-apim"})) as az_json:
            result = claim_api_management(target, "rg-test", "auto")

        az_json.assert_called_once()
        args = az_json.call_args.args[0]
        self.assertEqual(args[:3], ["apim", "create", "-g"])
        self.assertEqual(args[args.index("-g") + 1], "rg-test")
        self.assertEqual(args[args.index("-n") + 1], "cc-test-apim")
        self.assertEqual(args[args.index("-l") + 1], "westus2")
        self.assertEqual(args[args.index("--sku-name") + 1], "Consumption")
        self.assertIn("--publisher-email", args)
        self.assertEqual(result["location"], "westus2")
        self.assertEqual(result["sku"], "Consumption")

    def test_claim_error_classifier_detects_quota(self) -> None:
        reason, hint = classify_claim_error("Operation cannot be completed without additional quota. Current Limit (Total VMs): 0")

        self.assertEqual(reason, "quota")
        self.assertIn("--location", hint)

    def test_claim_error_classifier_detects_not_available(self) -> None:
        reason, hint = classify_claim_error("Label 'cc-test-tm' is not available in 'cc-test-tm.trafficmanager.net'")

        self.assertEqual(reason, "not_available")
        self.assertEqual(hint, "")

    def test_availability_normalizer_detects_not_available_message(self) -> None:
        target = AzureTarget(
            service="public_ip_dns_label",
            azure_hostname="cc-test-label-01.eastus.cloudapp.azure.com",
            name="cc-test-label-01",
            location="eastus",
        )

        result = normalize_availability(
            True,
            {"message": "DNS name label is not available."},
            target,
            "Microsoft.Network/publicIPAddresses/dnsSettings",
        )

        self.assertEqual(result["registration_status"], "not_available")
        self.assertIs(result["registration_available"], False)

    def test_check_target_reports_unknown_services_as_unsupported(self) -> None:
        target = AzureTarget(
            service="unsupported",
            azure_hostname="cc-test-frontdoor.azurefd.net",
            name="",
            location="auto",
        )

        result = check_target(target, "sub")

        self.assertEqual(result["registration_status"], "unsupported")
        self.assertEqual(result["registration_available"], "")
        self.assertIn("No availability handler", result["registration_message"])

    def test_check_targets_does_not_read_subscription_for_unsupported_only(self) -> None:
        target = AzureTarget(
            service="unsupported",
            azure_hostname="cc-test-app-stamp.westeurope-01.azurewebsites.net",
            name="",
            location="auto",
        )

        with patch("cloudclaim.clouds.azure.availability.subscription_id") as subscription:
            results = check_targets([target])

        subscription.assert_not_called()
        self.assertEqual(results[0]["registration_status"], "unsupported")

    def test_app_service_auto_location_retries_quota_failure(self) -> None:
        target = AzureTarget(
            service="app_service",
            azure_hostname="cc-test-app.azurewebsites.net",
            name="cc-test-app",
            location="auto",
        )
        calls = []

        def fake_az_json(args, timeout=60):
            calls.append(args)
            if args[:3] == ["appservice", "plan", "create"] and "eastus" in args:
                return False, {"stderr": "Operation cannot be completed without additional quota. Current Limit (Total VMs): 0"}
            return True, {}

        with (
            patch("cloudclaim.clouds.azure.claims.app_service_plans", return_value=[]),
            patch("cloudclaim.clouds.azure.claims.az_json", side_effect=fake_az_json),
        ):
            result = claim_app_service(target, "rg-test", "auto")

        self.assertEqual(result["location"], "eastus2")
        self.assertEqual(calls[0][calls[0].index("-l") + 1], "eastus")
        self.assertEqual(calls[1][calls[1].index("-l") + 1], "eastus2")

    def test_app_service_quota_reuses_existing_same_region_plan(self) -> None:
        target = AzureTarget(
            service="app_service",
            azure_hostname="cc-test-app-existing.japaneast-01.azurewebsites.net",
            name="cc-test-app-existing",
            location="japaneast",
        )
        calls = []

        def fake_az_json(args, timeout=60):
            calls.append(args)
            if args[:3] == ["appservice", "plan", "create"]:
                return False, {"stderr": "Operation cannot be completed without additional quota. Current Limit (Total VMs): 0"}
            if args[:2] == ["webapp", "create"]:
                return True, {"defaultHostName": "cc-test-app-existing.azurewebsites.net"}
            return True, {}

        existing_plan = {
            "id": "/subscriptions/sub/resourceGroups/rg-shared/providers/Microsoft.Web/serverfarms/shared-japaneast-plan",
            "name": "shared-japaneast-plan",
            "resourceGroup": "rg-shared",
        }

        with (
            patch("cloudclaim.clouds.azure.claims.app_service_plans", return_value=[existing_plan]),
            patch("cloudclaim.clouds.azure.claims.az_json", side_effect=fake_az_json),
        ):
            result = claim_app_service(target, "rg-test", "auto")

        self.assertTrue(result["reused_plan"])
        self.assertEqual(result["plan"], "shared-japaneast-plan")
        self.assertEqual(result["plan_resource_group"], "rg-shared")
        self.assertEqual(result["location"], "japaneast")
        self.assertEqual(calls[1][calls[1].index("-p") + 1], existing_plan["id"])
        self.assertEqual(calls[1][calls[1].index("-g") + 1], "rg-test")

    def test_claim_keeps_resources_by_default(self) -> None:
        target = AzureTarget(
            service="public_ip_dns_label",
            azure_hostname="cc-test-label.eastus.cloudapp.azure.com",
            name="cc-test-label",
            location="eastus",
        )
        handler = ClaimHandler("public_ip_dns_label", "test", lambda target, rg, loc: {"resource_group": rg})

        with (
            patch("cloudclaim.clouds.azure.claims.subscription_id", return_value="sub"),
            patch(
                "cloudclaim.clouds.azure.claims.check_target",
                return_value={
                    "azure_hostname": target.azure_hostname,
                    "azure_service": target.service,
                    "registration_available": True,
                    "registration_checked_location": target.location,
                    "registration_checked_name": target.name,
                    "registration_status": "available",
                },
            ),
            patch("cloudclaim.clouds.azure.claims.create_resource_group") as create_rg,
            patch("cloudclaim.clouds.azure.claims.delete_resource_group") as delete_rg,
            patch("cloudclaim.clouds.azure.claims.CLAIM_HANDLERS", {target.service: handler}),
        ):
            result = claim_targets([target], "rg-test", "eastus", selected_services=None, cleanup=False)

        create_rg.assert_called_once_with("rg-test", "eastus")
        delete_rg.assert_not_called()
        self.assertNotIn("cleanup_started", result)
        self.assertFalse(result["cleanup_requested"])
        self.assertEqual(result["results"][0]["status"], "claimed")

    def test_claim_deletes_only_when_cleanup_requested(self) -> None:
        target = AzureTarget(
            service="public_ip_dns_label",
            azure_hostname="cc-test-label.eastus.cloudapp.azure.com",
            name="cc-test-label",
            location="eastus",
        )
        handler = ClaimHandler("public_ip_dns_label", "test", lambda target, rg, loc: {"resource_group": rg})

        with (
            patch("cloudclaim.clouds.azure.claims.subscription_id", return_value="sub"),
            patch(
                "cloudclaim.clouds.azure.claims.check_target",
                return_value={
                    "azure_hostname": target.azure_hostname,
                    "azure_service": target.service,
                    "registration_available": True,
                    "registration_checked_location": target.location,
                    "registration_checked_name": target.name,
                    "registration_status": "available",
                },
            ),
            patch("cloudclaim.clouds.azure.claims.create_resource_group"),
            patch("cloudclaim.clouds.azure.claims.delete_resource_group", return_value=(True, "")) as delete_rg,
            patch("cloudclaim.clouds.azure.claims.CLAIM_HANDLERS", {target.service: handler}),
        ):
            result = claim_targets([target], "rg-test", "eastus", selected_services=None, cleanup=True)

        delete_rg.assert_called_once_with("rg-test")
        self.assertTrue(result["cleanup_requested"])
        self.assertTrue(result["cleanup_started"])

    def test_claim_create_time_not_available_becomes_not_claimed(self) -> None:
        target = AzureTarget(
            service="public_ip_dns_label",
            azure_hostname="cc-test-label-01.eastus.cloudapp.azure.com",
            name="cc-test-label-01",
            location="eastus",
        )
        handler = ClaimHandler("public_ip_dns_label", "test", lambda target, rg, loc: (_ for _ in ()).throw(RuntimeError("DNS name label is not available.")))

        with (
            patch("cloudclaim.clouds.azure.claims.subscription_id", return_value="sub"),
            patch(
                "cloudclaim.clouds.azure.claims.check_target",
                return_value={
                    "azure_hostname": target.azure_hostname,
                    "azure_service": target.service,
                    "registration_available": True,
                    "registration_checked_location": target.location,
                    "registration_checked_name": target.name,
                    "registration_status": "available",
                },
            ),
            patch("cloudclaim.clouds.azure.claims.create_resource_group"),
            patch("cloudclaim.clouds.azure.claims.CLAIM_HANDLERS", {target.service: handler}),
        ):
            result = claim_targets([target], "rg-test", "eastus", selected_services=None, cleanup=False)

        entry = result["results"][0]
        self.assertEqual(entry["status"], "not_claimed")
        self.assertEqual(entry["registration_status"], "not_available")
        self.assertIs(entry["registration_available"], False)
        self.assertIs(entry["claim_attempted"], True)

    def test_claim_does_not_attempt_without_plain_available(self) -> None:
        target = AzureTarget(
            service="public_ip_dns_label",
            azure_hostname="cc-test-label-used.eastus.cloudapp.azure.com",
            name="cc-test-label-used",
            location="eastus",
        )
        handler = ClaimHandler("public_ip_dns_label", "test", lambda target, rg, loc: {"resource_group": rg})

        with (
            patch("cloudclaim.clouds.azure.claims.subscription_id", return_value="sub"),
            patch(
                "cloudclaim.clouds.azure.claims.check_target",
                return_value={
                    "azure_hostname": target.azure_hostname,
                    "azure_service": target.service,
                    "registration_available": False,
                    "registration_checked_location": target.location,
                    "registration_checked_name": target.name,
                    "registration_status": "not_available",
                },
            ),
            patch("cloudclaim.clouds.azure.claims.create_resource_group") as create_rg,
            patch("cloudclaim.clouds.azure.claims.CLAIM_HANDLERS", {target.service: handler}),
        ):
            result = claim_targets([target], "rg-test", "eastus", selected_services=None, cleanup=False)

        create_rg.assert_not_called()
        self.assertEqual(result["results"][0]["status"], "not_claimed")

    def test_claim_does_not_read_subscription_for_unsupported_only(self) -> None:
        target = AzureTarget(
            service="unsupported",
            azure_hostname="cc-test-app-stamp.westeurope-01.azurewebsites.net",
            name="",
            location="auto",
        )

        with patch("cloudclaim.clouds.azure.claims.subscription_id") as subscription:
            result = claim_targets([target], "rg-test", "auto", selected_services=None, cleanup=False)

        subscription.assert_not_called()
        self.assertEqual(result["results"][0]["status"], "unsupported")

if __name__ == "__main__":
    unittest.main()
