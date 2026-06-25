from __future__ import annotations

from argparse import Namespace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cloudclaim.clouds.aws.availability import check_target, check_targets, normalize_availability
from cloudclaim.clouds.aws.claims import claim_targets, compact_env_name, select_solution_stack, terminate_environment
from cloudclaim.clouds.aws.client import precheck as aws_precheck
from cloudclaim.clouds.aws.commands import build_parser, run_check, run_precheck, run_services, selected_services_from_arg
from cloudclaim.clouds.aws.inputs import load_targets
from cloudclaim.clouds.aws.models import AwsClaimOptions, AwsTarget, ClaimHandler
from cloudclaim.clouds.aws.output import print_check_results, print_claim_result
from cloudclaim.clouds.aws.services import classify_hostname, normalize_hostname


class AwsHostnameClassificationTests(unittest.TestCase):
    def test_normalizes_urls_and_case(self) -> None:
        self.assertEqual(normalize_hostname("HTTPS://Cc-Test-Eb.Us-East-1.ElasticBeanstalk.Com/path"), "cc-test-eb.us-east-1.elasticbeanstalk.com")

    def test_does_not_classify_unqualified_elastic_beanstalk_hostname(self) -> None:
        target = classify_hostname("cc-test-eb-app.elasticbeanstalk.com")

        self.assertIsNone(target)

    def test_classifies_regional_elastic_beanstalk_hostname(self) -> None:
        target = classify_hostname("cc-test-eb-app.us-west-2.elasticbeanstalk.com")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.service, "elastic_beanstalk")
        self.assertEqual(target.name, "cc-test-eb-app")
        self.assertEqual(target.region, "us-west-2")

    def test_classifies_elastic_beanstalk_descendant_as_parent_cname(self) -> None:
        target = classify_hostname("child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.service, "elastic_beanstalk")
        self.assertEqual(target.hostname, "cc-test-eb-parent.us-west-2.elasticbeanstalk.com")
        self.assertEqual(target.name, "cc-test-eb-parent")
        self.assertEqual(target.region, "us-west-2")
        self.assertEqual(target.source_host, "child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com")

    def test_does_not_classify_s3_as_claimable(self) -> None:
        self.assertIsNone(classify_hostname("cc-test-bucket.s3.amazonaws.com"))

    def test_does_not_classify_elb_as_supported_service(self) -> None:
        self.assertIsNone(classify_hostname("cc-test-elb-123456789.us-east-1.elb.amazonaws.com"))

    def test_does_not_classify_other_aws_hostname_as_supported_service(self) -> None:
        self.assertIsNone(classify_hostname("cc-test-accelerator.awsglobalaccelerator.com"))


class AwsInputParsingTests(unittest.TestCase):
    def test_load_targets_reads_plain_text_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hosts.txt"
            path.write_text(
                "\n".join(["hostname", "cc-test-eb-app.us-east-1.elasticbeanstalk.com", "cc-test-bucket.s3.amazonaws.com"]),
                encoding="utf-8",
            )

            targets = load_targets([str(path)])

        self.assertEqual([target.hostname for target in targets], ["cc-test-eb-app.us-east-1.elasticbeanstalk.com", "cc-test-bucket.s3.amazonaws.com"])
        self.assertEqual([target.service for target in targets], ["elastic_beanstalk", "unsupported"])

    def test_load_targets_normalizes_elastic_beanstalk_descendants(self) -> None:
        targets = load_targets(["child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com"])

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].hostname, "cc-test-eb-parent.us-west-2.elasticbeanstalk.com")
        self.assertEqual(targets[0].service, "elastic_beanstalk")

    def test_load_targets_rejects_non_txt_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "hosts.csv"
            path.write_text("hostname\ncc-test-eb-app.us-east-1.elasticbeanstalk.com\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                load_targets([str(path)])


class AwsAvailabilityTests(unittest.TestCase):
    def test_normalize_available_requires_exact_hostname_match(self) -> None:
        target = AwsTarget("elastic_beanstalk", "cc-test-eb.us-east-1.elasticbeanstalk.com", "cc-test-eb", "us-east-1")

        payload = normalize_availability(True, {"Available": True, "FullyQualifiedCNAME": "cc-test-eb.us-west-2.elasticbeanstalk.com"}, target)

        self.assertFalse(payload["registration_available"])
        self.assertEqual(payload["registration_status"], "not_available")

    def test_check_target_reports_available(self) -> None:
        target = AwsTarget("elastic_beanstalk", "cc-test-eb.us-east-1.elasticbeanstalk.com", "cc-test-eb", "us-east-1")
        with patch(
            "cloudclaim.clouds.aws.availability.aws_json",
            return_value=(True, {"Available": True, "FullyQualifiedCNAME": "cc-test-eb.us-east-1.elasticbeanstalk.com"}),
        ) as aws_json:
            result = check_target(target, "profile")

        self.assertTrue(result["registration_available"])
        aws_json.assert_called_once_with(
            ["elasticbeanstalk", "check-dns-availability", "--cname-prefix", "cc-test-eb"],
            region="us-east-1",
            profile="profile",
            timeout=60,
        )

    def test_unsupported_check_does_not_call_aws(self) -> None:
        target = AwsTarget("unsupported", "cc-test-bucket.s3.amazonaws.com", "", "us-east-1")
        with patch("cloudclaim.clouds.aws.availability.aws_json") as aws_json:
            result = check_targets([target])

        self.assertEqual(result[0]["registration_status"], "unsupported")
        aws_json.assert_not_called()


class AwsClaimTests(unittest.TestCase):
    def test_select_solution_stack_prefers_python_on_amazon_linux(self) -> None:
        with patch(
            "cloudclaim.clouds.aws.claims.aws_json",
            return_value=(
                True,
                {
                    "SolutionStacks": [
                        "64bit Windows Server running IIS",
                        "64bit Amazon Linux 2023 v4.0.0 running Node.js 20",
                        "64bit Amazon Linux 2023 v4.0.0 running Python 3.11",
                    ]
                },
            ),
        ):
            stack = select_solution_stack("us-east-1", None, None)

        self.assertEqual(stack, "64bit Amazon Linux 2023 v4.0.0 running Python 3.11")

    def test_compact_env_name_fits_elastic_beanstalk_limit(self) -> None:
        self.assertLessEqual(len(compact_env_name("very-long-target-name-for-cloudclaim-testing")), 40)

    def test_claim_targets_checks_before_create(self) -> None:
        target = AwsTarget("elastic_beanstalk", "cc-test-eb.us-east-1.elasticbeanstalk.com", "cc-test-eb", "us-east-1")
        options = AwsClaimOptions(application_name="cloudclaim-test", solution_stack_name="stack")

        with patch(
            "cloudclaim.clouds.aws.availability.aws_json",
            return_value=(True, {"Available": True, "FullyQualifiedCNAME": "cc-test-eb.us-east-1.elasticbeanstalk.com"}),
        ) as availability_aws_json, patch(
            "cloudclaim.clouds.aws.claims.aws_json",
            side_effect=[
                (True, {"ApplicationName": "cloudclaim-test"}),
                (True, {"EnvironmentName": "cc-cc-test-eb-12345678", "CNAME": "cc-test-eb.us-east-1.elasticbeanstalk.com"}),
            ],
        ) as claim_aws_json:
            result = claim_targets([target], options, selected_services=None, cleanup=False)

        self.assertEqual(result["results"][0]["status"], "claimed")
        availability_aws_json.assert_called_once_with(
            ["elasticbeanstalk", "check-dns-availability", "--cname-prefix", "cc-test-eb"],
            region="us-east-1",
            profile=None,
            timeout=60,
        )
        self.assertEqual(claim_aws_json.mock_calls[1].args[0][0:2], ["elasticbeanstalk", "create-environment"])

    def test_claim_targets_does_not_create_when_not_available(self) -> None:
        target = AwsTarget("elastic_beanstalk", "cc-test-eb.us-east-1.elasticbeanstalk.com", "cc-test-eb", "us-east-1")
        with patch(
            "cloudclaim.clouds.aws.availability.aws_json",
            return_value=(True, {"Available": False, "FullyQualifiedCNAME": "cc-test-eb.us-east-1.elasticbeanstalk.com"}),
        ) as availability_aws_json, patch("cloudclaim.clouds.aws.claims.aws_json") as claim_aws_json:
            result = claim_targets([target], AwsClaimOptions(), selected_services=None, cleanup=False)

        self.assertEqual(result["results"][0]["status"], "not_claimed")
        availability_aws_json.assert_called_once()
        claim_aws_json.assert_not_called()

    def test_claim_create_time_not_available_is_counted_as_attempted(self) -> None:
        target = AwsTarget("elastic_beanstalk", "cc-test-eb.us-east-1.elasticbeanstalk.com", "cc-test-eb", "us-east-1")
        handler = ClaimHandler("elastic_beanstalk", "test", lambda target, options: (_ for _ in ()).throw(RuntimeError("CNAME is not available.")))

        with (
            patch(
                "cloudclaim.clouds.aws.claims.check_target",
                return_value={
                    "aws_hostname": target.hostname,
                    "aws_service": target.service,
                    "registration_available": True,
                    "registration_checked_region": target.region,
                    "registration_checked_name": target.name,
                    "registration_status": "available",
                },
            ),
            patch("cloudclaim.clouds.aws.claims.CLAIM_HANDLERS", {target.service: handler}),
        ):
            result = claim_targets([target], AwsClaimOptions(), selected_services=None, cleanup=False)

        entry = result["results"][0]
        self.assertEqual(entry["status"], "not_claimed")
        self.assertEqual(entry["registration_status"], "not_available")
        self.assertIs(entry["registration_available"], False)
        self.assertIs(entry["claim_attempted"], True)

    def test_claim_targets_does_not_call_aws_for_unsupported(self) -> None:
        target = AwsTarget("unsupported", "cc-test-bucket.s3.amazonaws.com", "", "us-east-1")
        with patch("cloudclaim.clouds.aws.availability.aws_json") as availability_aws_json, patch("cloudclaim.clouds.aws.claims.aws_json") as claim_aws_json:
            result = claim_targets([target], AwsClaimOptions(), selected_services=None, cleanup=False)

        self.assertEqual(result["results"][0]["status"], "unsupported")
        availability_aws_json.assert_not_called()
        claim_aws_json.assert_not_called()

    def test_terminate_environment_waits_out_pending_creation(self) -> None:
        with patch(
            "cloudclaim.clouds.aws.claims.aws_json",
            side_effect=[
                (True, {"Environments": [{"Status": "Launching"}]}),
                (True, {"Environments": [{"Status": "Ready"}]}),
                (True, {"EnvironmentName": "cc-cc-test-eb-12345678"}),
            ],
        ) as aws_json, patch("cloudclaim.clouds.aws.claims.time.sleep") as sleep:
            ok, message = terminate_environment("cc-cc-test-eb-12345678", "us-east-1", "dev")

        self.assertTrue(ok)
        self.assertEqual(message, "")
        sleep.assert_called_once_with(15)
        self.assertEqual(aws_json.mock_calls[0].args[0][0:2], ["elasticbeanstalk", "describe-environments"])
        self.assertEqual(aws_json.mock_calls[1].args[0][0:2], ["elasticbeanstalk", "describe-environments"])
        self.assertEqual(aws_json.mock_calls[2].args[0][0:2], ["elasticbeanstalk", "terminate-environment"])

    def test_terminate_environment_accepts_already_terminating_environment(self) -> None:
        with patch(
            "cloudclaim.clouds.aws.claims.aws_json",
            return_value=(True, {"Environments": [{"Status": "Terminating"}]}),
        ) as aws_json:
            ok, message = terminate_environment("cc-cc-test-eb-12345678", "us-east-1", None)

        self.assertTrue(ok)
        self.assertEqual(message, "")
        self.assertEqual(len(aws_json.mock_calls), 1)
        self.assertEqual(aws_json.mock_calls[0].args[0][0:2], ["elasticbeanstalk", "describe-environments"])


class AwsOutputTests(unittest.TestCase):
    def test_check_parser_does_not_have_region_fallback(self) -> None:
        parser = build_parser(prog="cloudclaim aws")
        args = parser.parse_args(["check", "cc-test-eb.us-east-1.elasticbeanstalk.com"])

        self.assertFalse(hasattr(args, "region"))

    def test_check_parser_accepts_env_file(self) -> None:
        parser = build_parser(prog="cloudclaim aws")
        args = parser.parse_args(["check", "--env-file", "creds.env", "cc-test-eb.us-east-1.elasticbeanstalk.com"])

        self.assertEqual(args.env_file, "creds.env")

    def test_services_output_lists_only_claimable_services(self) -> None:
        output = io.StringIO()
        args = Namespace(json=True, color=False, no_color=True)

        with redirect_stdout(output):
            self.assertEqual(run_services(args), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(list(payload), ["elastic_beanstalk"])

    def test_selected_services_rejects_not_claimable_services(self) -> None:
        with self.assertRaises(SystemExit):
            selected_services_from_arg("made_up_service")

    def test_precheck_outputs_json(self) -> None:
        output = io.StringIO()
        args = Namespace(json=True, color=False, no_color=True, profile="dev")

        with (
            redirect_stdout(output),
            patch.dict("os.environ", {}, clear=True),
            patch("cloudclaim.clouds.aws.commands.load_env_file", return_value={}),
            patch(
                "cloudclaim.clouds.aws.commands.precheck",
                return_value={
                    "ok": True,
                    "provider": "aws",
                    "account": "123456789012",
                    "arn": "arn:aws:iam::123456789012:user/dev",
                    "user_id": "uid",
                    "region": "us-west-2",
                    "profile": "dev",
                },
            ) as precheck_mock,
        ):
            self.assertEqual(run_precheck(args), 0)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["account"], "123456789012")
        precheck_mock.assert_called_once_with(region=None, profile="dev")

    def test_client_precheck_reports_success(self) -> None:
        with patch(
            "cloudclaim.clouds.aws.client.aws_json",
            return_value=(True, {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/dev", "UserId": "uid"}),
        ) as aws_json:
            result = aws_precheck(region="us-west-2", profile="dev")

        self.assertTrue(result["ok"])
        self.assertEqual(result["account"], "123456789012")
        self.assertEqual(result["profile"], "dev")
        aws_json.assert_called_once_with(["sts", "get-caller-identity"], region="us-west-2", profile="dev", timeout=30)

    def test_client_precheck_reports_failure(self) -> None:
        with patch("cloudclaim.clouds.aws.client.aws_json", return_value=(False, {"stderr": "Unable to locate credentials"})):
            result = aws_precheck(region="us-east-1", profile=None)

        self.assertFalse(result["ok"])
        self.assertIn("credentials", result["message"])

    def test_client_precheck_failure_mentions_profile(self) -> None:
        with patch("cloudclaim.clouds.aws.client.aws_json", return_value=(False, {"stderr": "profile not found"})):
            result = aws_precheck(region="us-east-1", profile="cloudclaim")

        self.assertFalse(result["ok"])
        self.assertIn("cloudclaim", result["message"])

    def test_print_check_results_outputs_normal_text_by_default(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "aws_hostname": "cc-test-eb.us-east-1.elasticbeanstalk.com",
                        "aws_service": "elastic_beanstalk",
                        "registration_available": True,
                        "registration_checked_region": "us-east-1",
                        "registration_checked_name": "cc-test-eb",
                    }
                ]
            )

        text = output.getvalue()
        self.assertIn("[INF] aws check: 1/1 available", text)
        self.assertIn("cc-test-eb.us-east-1.elasticbeanstalk.com [available] [aws] [elastic_beanstalk]", text)

    def test_print_check_results_notes_elastic_beanstalk_parent_normalization(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "aws_hostname": "cc-test-eb-parent.us-west-2.elasticbeanstalk.com",
                        "aws_service": "elastic_beanstalk",
                        "source_host": "child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com",
                        "registration_available": True,
                        "registration_checked_region": "us-west-2",
                        "registration_checked_name": "cc-test-eb-parent",
                    }
                ]
            )

        text = output.getvalue()
        self.assertIn("cc-test-eb-parent.us-west-2.elasticbeanstalk.com [available] [aws] [elastic_beanstalk]", text)
        self.assertIn("[child:child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com]", text)

    def test_print_check_results_json_includes_elastic_beanstalk_parent_note(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_check_results(
                [
                    {
                        "aws_hostname": "cc-test-eb-parent.us-west-2.elasticbeanstalk.com",
                        "aws_service": "elastic_beanstalk",
                        "source_host": "child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com",
                        "registration_available": True,
                        "registration_checked_region": "us-west-2",
                        "registration_checked_name": "cc-test-eb-parent",
                    }
                ],
                json_output=True,
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["input_hostname"], "child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com")
        self.assertEqual(payload["note"], "child:child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com")

    def test_print_claim_result_simplifies_not_available_output(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "application_name": "cloudclaim-eb",
                    "results": [
                        {
                            "aws_hostname": "cc-test-eb.us-east-1.elasticbeanstalk.com",
                            "aws_service": "elastic_beanstalk",
                            "registration_available": False,
                            "registration_checked_region": "us-east-1",
                            "registration_checked_name": "cc-test-eb",
                            "registration_status": "not_available",
                            "status": "not_claimed",
                            "message": "AWS availability check did not return available",
                        }
                    ],
                }
            )

        text = output.getvalue()
        self.assertIn("cc-test-eb.us-east-1.elasticbeanstalk.com [not-available] [aws] [elastic_beanstalk]", text)
        self.assertNotIn("AWS availability check did not return available", text)

    def test_print_claim_result_simplifies_create_time_not_available_output(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            print_claim_result(
                {
                    "application_name": "cloudclaim-eb",
                    "results": [
                        {
                            "aws_hostname": "cc-test-eb.us-east-1.elasticbeanstalk.com",
                            "aws_service": "elastic_beanstalk",
                            "registration_available": False,
                            "registration_checked_region": "us-east-1",
                            "registration_checked_name": "cc-test-eb",
                            "registration_status": "not_available",
                            "status": "not_claimed",
                            "claim_attempted": True,
                            "message": "AWS reported the name is not available",
                        }
                    ],
                }
            )

        text = output.getvalue()
        self.assertIn("[INF] aws claim: 0/1 claimed, 1/1 attempted", text)
        self.assertIn("cc-test-eb.us-east-1.elasticbeanstalk.com [not-available] [aws] [elastic_beanstalk]", text)
        self.assertNotIn("[claim:failed]", text)
        self.assertNotIn("AWS reported the name is not available", text)

    def test_run_check_prechecks_supported_targets(self) -> None:
        output = io.StringIO()
        target = AwsTarget("elastic_beanstalk", "cc-test-eb.us-east-1.elasticbeanstalk.com", "cc-test-eb", "us-east-1")

        with (
            redirect_stdout(output),
            patch.dict("os.environ", {}, clear=True),
            patch("cloudclaim.clouds.aws.commands.load_env_file", return_value={}),
            patch("cloudclaim.clouds.aws.commands.load_targets", return_value=[target]),
            patch("cloudclaim.clouds.aws.commands.precheck", return_value={"ok": True, "provider": "aws", "account": "123456789012"}),
            patch("cloudclaim.clouds.aws.commands.check_targets", return_value=[]),
        ):
            self.assertEqual(
                run_check(Namespace(inputs=["cc-test-eb.us-east-1.elasticbeanstalk.com"], profile=None, json=False, out=None, color=False, no_color=True)),
                0,
            )

        self.assertIn("[INF] aws precheck: ok [123456789012]", output.getvalue())

    def test_run_check_skips_precheck_for_unsupported_only(self) -> None:
        output = io.StringIO()
        target = AwsTarget("unsupported", "cc-test-bucket.s3.amazonaws.com", "", "us-east-1")

        with (
            redirect_stdout(output),
            patch.dict("os.environ", {}, clear=True),
            patch("cloudclaim.clouds.aws.commands.load_env_file", return_value={}) as load_env_file,
            patch("cloudclaim.clouds.aws.commands.load_targets", return_value=[target]),
            patch("cloudclaim.clouds.aws.commands.precheck") as precheck_mock,
            patch("cloudclaim.clouds.aws.commands.check_targets", return_value=[]),
        ):
            self.assertEqual(
                run_check(Namespace(inputs=["cc-test-bucket.s3.amazonaws.com"], profile=None, json=False, out=None, color=False, no_color=True)),
                0,
            )

        load_env_file.assert_not_called()
        precheck_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
