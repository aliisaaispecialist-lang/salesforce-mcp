"""Logging that cannot leak, and counters that separate calls from attempts.

The redaction tests matter most: they assert what must never appear in a log
line, whoever wrote it and however it was nested.
"""

import json
import logging
from io import StringIO

import pytest

from salesforce_connector.observability import (
    Metrics,
    RedactingFormatter,
    configure_logging,
    log_event,
    redact,
)

PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKC\n-----END RSA PRIVATE KEY-----"


class TestRedaction:
    @pytest.mark.parametrize(
        ("line", "secret"),
        [
            ("Authorization: Bearer 00D5g000004abcXYZ", "00D5g000004abcXYZ"),
            ('{"access_token": "00D5g000004abcXYZ"}', "00D5g000004abcXYZ"),
            ('{"refresh_token": "5Aep861z9BQ"}', "5Aep861z9BQ"),
            ('{"client_secret": "shhh"}', "shhh"),
            ('{"assertion": "eyJhbGciOi.J9.sig"}', "eyJhbGciOi.J9.sig"),
        ],
    )
    def test_token_shaped_values_are_masked(self, line: str, secret: str) -> None:
        assert secret not in redact(line)

    def test_a_private_key_block_is_masked_whole(self) -> None:
        masked = redact(f"failed with key {PRIVATE_KEY} attached")

        assert "MIIEowIBAAKC" not in masked
        assert "BEGIN RSA PRIVATE KEY" not in masked

    def test_ordinary_text_is_left_alone(self) -> None:
        line = '{"action_id": "salesforce.create_contact", "status": 201}'

        assert redact(line) == line


class TestLogOutput:
    def make_logger(self) -> tuple[logging.Logger, StringIO]:
        stream = StringIO()
        logger = logging.getLogger("test_observability")
        logger.handlers.clear()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        return logger, stream

    def test_each_event_is_one_json_object(self) -> None:
        logger, stream = self.make_logger()

        log_event(logger, "action.completed", request_id="req-1", action_id="a.b", ok=True)

        written = json.loads(stream.getvalue().strip())
        assert written["event"] == "action.completed"
        assert written["request_id"] == "req-1"
        assert written["level"] == "info"

    def test_a_secret_passed_as_a_field_is_still_masked(self) -> None:
        logger, stream = self.make_logger()

        log_event(logger, "auth.token", access_token="00D5g000004abcXYZ")

        assert "00D5g000004abcXYZ" not in stream.getvalue()

    def test_the_package_logger_writes_to_stderr_not_stdout(self) -> None:
        logger = configure_logging()

        streams = [getattr(h, "stream", None) for h in logger.handlers]

        assert all(stream is not None for stream in streams)
        assert not any(getattr(s, "name", "") == "<stdout>" for s in streams)


class TestMetrics:
    def test_calls_and_attempts_are_counted_separately(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.search_contact", ok=True, duration_ms=120.0)
        for _ in range(3):
            metrics.record_attempt("salesforce.search_contact")

        summary = metrics.summary()
        assert summary["calls"]["salesforce.search_contact"] == 1
        assert summary["attempts"]["salesforce.search_contact"] == 3
        assert summary["attempts_per_call"]["salesforce.search_contact"] == 3.0

    def test_failures_are_counted_by_the_category_a_caller_responds_to(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.create_contact", ok=False, duration_ms=50.0)
        metrics.record_failure("salesforce.create_contact", "transient")

        assert metrics.summary()["failures"]["salesforce.create_contact:transient"] == 1

    def test_a_successful_call_is_not_counted_as_a_failure(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.create_contact", ok=True, duration_ms=50.0)

        assert metrics.summary()["failures"] == {}
        assert metrics.summary()["successes"]["salesforce.create_contact"] == 1

    def test_exhausted_retries_are_distinguished_from_ordinary_ones(self) -> None:
        metrics = Metrics()

        metrics.record_retry("salesforce.update_contact")
        metrics.record_retry("salesforce.update_contact", exhausted=True)

        summary = metrics.summary()
        assert summary["retries"]["salesforce.update_contact"] == 2
        assert summary["retries_exhausted"]["salesforce.update_contact"] == 1

    def test_latency_is_reported_as_percentiles(self) -> None:
        metrics = Metrics()

        for value in range(1, 101):
            metrics.record_call("salesforce.search_contact", ok=True, duration_ms=float(value))

        latency = metrics.summary()["latency_ms"]["salesforce.search_contact"]
        assert latency["count"] == 100
        assert latency["p50"] == 50.5
        assert latency["p95"] == 96.0
        assert latency["max"] == 100.0

    def test_a_single_sample_does_not_break_the_percentiles(self) -> None:
        metrics = Metrics()

        metrics.record_call("salesforce.search_contact", ok=True, duration_ms=7.0)

        latency = metrics.summary()["latency_ms"]["salesforce.search_contact"]
        assert latency["p50"] == latency["p95"] == latency["max"] == 7.0

    def test_an_untouched_summary_is_empty_rather_than_absent(self) -> None:
        assert Metrics().summary()["calls"] == {}
