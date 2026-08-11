"""Logging that cannot leak, and counters that separate calls from attempts.

The censoring tests matter most: they assert what must never appear in a log
line, whoever wrote it and however deeply it was nested.
"""

import json
import logging
from collections.abc import Mapping

import pytest
import structlog

from salesforce_connector.observability import (
    Metrics,
    bind_request,
    censor_secrets,
    clear_request,
    configure_logging,
    get_logger,
)

PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKC\n-----END RSA PRIVATE KEY-----"
TOKEN = "00D5g000004abcXYZ"


def censor(**fields: object) -> Mapping[str, object]:
    return censor_secrets(None, "info", dict(fields))


class TestCensoring:
    @pytest.mark.parametrize(
        "key",
        ["access_token", "refresh_token", "client_secret", "assertion", "authorization"],
    )
    def test_a_secret_named_field_is_masked(self, key: str) -> None:
        assert TOKEN not in str(censor(**{key: TOKEN}))

    def test_a_secret_nested_in_a_dict_is_masked(self) -> None:
        censored = censor(response={"access_token": TOKEN, "instance_url": "https://x"})

        assert TOKEN not in str(censored)
        assert "https://x" in str(censored)

    def test_a_bearer_header_inside_a_message_is_masked(self) -> None:
        assert TOKEN not in str(censor(detail=f"sent Authorization: Bearer {TOKEN}"))

    def test_a_private_key_block_is_masked_whole(self) -> None:
        censored = str(censor(detail=f"failed with {PRIVATE_KEY}"))

        assert "MIIEowIBAAKC" not in censored

    def test_ordinary_fields_are_left_alone(self) -> None:
        censored = censor(action_id="salesforce.contact_create", status=201)

        assert censored == {"action_id": "salesforce.contact_create", "status": 201}


class TestLogOutput:
    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        clear_request()
        structlog.reset_defaults()

    def test_each_event_is_one_json_object_on_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(logging.INFO)

        get_logger().info(
            "action.completed", action_id="salesforce.contact_search_by_text", ok=True
        )

        captured = capsys.readouterr()
        assert captured.out == ""
        written = json.loads(captured.err.strip())
        assert written["event"] == "action.completed"
        assert written["ok"] is True

    def test_a_secret_passed_as_a_field_is_still_masked(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(logging.INFO)

        get_logger().info("auth.token", access_token=TOKEN)

        assert TOKEN not in capsys.readouterr().err

    def test_a_bound_request_is_attached_without_being_passed_around(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(logging.INFO)
        bind_request("req-42", "salesforce.contact_create")

        get_logger().info("client.attempt")

        written = json.loads(capsys.readouterr().err.strip())
        assert written["request_id"] == "req-42"
        assert written["action_id"] == "salesforce.contact_create"

    def test_context_does_not_survive_the_call_that_bound_it(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(logging.INFO)
        bind_request("req-42", "salesforce.contact_create")
        clear_request()

        get_logger().info("unrelated")

        assert "req-42" not in capsys.readouterr().err


class TestMetrics:
    def test_calls_and_attempts_are_counted_separately(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.contact_search_by_text", ok=True, duration_ms=120.0)
        for _ in range(3):
            metrics.record_attempt("salesforce.contact_search_by_text")

        summary = metrics.summary()
        assert summary["calls"]["salesforce.contact_search_by_text"] == 1
        assert summary["attempts"]["salesforce.contact_search_by_text"] == 3
        assert summary["attempts_per_call"]["salesforce.contact_search_by_text"] == 3.0

    def test_failures_are_counted_by_the_category_a_caller_responds_to(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.contact_create", ok=False, duration_ms=50.0)
        metrics.record_failure("salesforce.contact_create", "transient")

        assert metrics.summary()["failures"]["salesforce.contact_create:transient"] == 1

    def test_a_successful_call_is_not_counted_as_a_failure(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.contact_create", ok=True, duration_ms=50.0)

        assert metrics.summary()["failures"] == {}
        assert metrics.summary()["successes"]["salesforce.contact_create"] == 1

    def test_exhausted_retries_are_distinguished_from_ordinary_ones(self) -> None:
        metrics = Metrics()

        metrics.record_retry("salesforce.contact_update_by_id")
        metrics.record_retry("salesforce.contact_update_by_id", exhausted=True)

        summary = metrics.summary()
        assert summary["retries"]["salesforce.contact_update_by_id"] == 2
        assert summary["retries_exhausted"]["salesforce.contact_update_by_id"] == 1

    def test_latency_is_reported_as_percentiles(self) -> None:
        metrics = Metrics()

        for value in range(1, 101):
            metrics.record_call(
                "salesforce.contact_search_by_text", ok=True, duration_ms=float(value)
            )

        latency = metrics.summary()["latency_ms"]["salesforce.contact_search_by_text"]
        assert latency["count"] == 100
        assert latency["p50"] == 50.5
        assert latency["p95"] == 96.0
        assert latency["max"] == 100.0

    def test_a_single_sample_does_not_break_the_percentiles(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.contact_search_by_text", ok=True, duration_ms=7.0)

        latency = metrics.summary()["latency_ms"]["salesforce.contact_search_by_text"]
        assert latency["p50"] == latency["p95"] == latency["max"] == 7.0

    def test_an_untouched_summary_is_empty_rather_than_absent(self) -> None:
        assert Metrics().summary()["calls"] == {}
