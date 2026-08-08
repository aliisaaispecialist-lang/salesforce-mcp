"""What Salesforce sends back, and the failure each response must become.

The cases that matter are the ones where the obvious mapping is wrong: a rate
limit arriving as HTTP 403, a lock contention that reads like a conflict, and
the pattern ordering that decides whether INVALID_SESSION_ID is bad input or
an expired session.
"""

import pytest

from salesforce_connector.contract import ErrorCategory
from salesforce_connector.errors.mapping import to_connector_error
from salesforce_connector.errors.model import (
    AuthenticationError,
    ConflictError,
    ConnectorError,
    InvalidInputError,
    PermissionDeniedError,
    RateLimitError,
    RecordNotFoundError,
    TransportError,
)


def rest_fault(code: str, message: str = "something went wrong") -> list[dict[str, object]]:
    return [{"message": message, "errorCode": code}]


class TestOverridesBeatPatterns:
    """Three codes the shape rules classify wrongly, and must not."""

    def test_request_limit_exceeded_is_a_rate_limit_despite_arriving_as_403(self) -> None:
        error = to_connector_error(403, rest_fault("REQUEST_LIMIT_EXCEEDED"), retry_after=30.0)

        assert isinstance(error, RateLimitError)
        assert error.to_action_error().category is ErrorCategory.TRANSIENT
        assert error.to_action_error().retryable is True

    def test_a_real_403_is_still_a_permission_failure(self) -> None:
        error = to_connector_error(403, rest_fault("INSUFFICIENT_ACCESS"))

        assert isinstance(error, PermissionDeniedError)
        assert error.to_action_error().retryable is False

    def test_row_lock_contention_is_transient_not_a_conflict(self) -> None:
        error = to_connector_error(400, rest_fault("UNABLE_TO_LOCK_ROW"))

        assert isinstance(error, TransportError)
        assert error.to_action_error().retryable is True

    def test_expired_password_is_auth_though_it_starts_with_invalid(self) -> None:
        error = to_connector_error(400, rest_fault("INVALID_OPERATION_WITH_EXPIRED_PASSWORD"))

        assert isinstance(error, AuthenticationError)


class TestPatternOrdering:
    """INVALID_* is broad, so narrower rules must claim their codes first."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("INVALID_SESSION_ID", AuthenticationError),
            ("INVALID_LOGIN", AuthenticationError),
            ("INVALID_FIELD", InvalidInputError),
            ("INVALID_TYPE", InvalidInputError),
        ],
    )
    def test_auth_rules_win_over_the_broad_input_rule(
        self, code: str, expected: type[ConnectorError]
    ) -> None:
        assert isinstance(to_connector_error(400, rest_fault(code)), expected)


class TestUnseenCodesStillClassify:
    """The point of matching by shape: codes nobody has listed."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("SOMETHING_NEW_TOO_LONG", InvalidInputError),
            ("FUTURE_WIDGET_NOT_FOUND", RecordNotFoundError),
            ("DUPLICATE_WIDGET_VALUE", ConflictError),
            ("WIDGET_QUOTA_LIMIT_EXCEEDED", RateLimitError),
            ("WIDGET_ACCESS_DENIED", PermissionDeniedError),
        ],
    )
    def test_a_code_absent_from_every_list_is_still_classified(
        self, code: str, expected: type[ConnectorError]
    ) -> None:
        assert isinstance(to_connector_error(400, rest_fault(code)), expected)


class TestBodyShapes:
    """Salesforce answers with a list; its OAuth endpoint answers with an object."""

    def test_the_oauth_object_shape_is_understood(self) -> None:
        body = {"error": "invalid_grant", "error_description": "consumer not approved"}

        error = to_connector_error(400, body)

        assert isinstance(error, AuthenticationError)
        assert "consumer not approved" in error.to_action_error().reason

    def test_an_empty_body_still_produces_an_actionable_failure(self) -> None:
        action_error = to_connector_error(500, None).to_action_error()

        assert "HTTP 500" in action_error.reason
        assert action_error.next_step


class TestNamedFields:
    def test_named_fields_are_reported_to_the_caller(self) -> None:
        body = [{"message": "duplicate", "errorCode": "DUPLICATES_DETECTED", "fields": ["Email"]}]

        assert to_connector_error(400, body).to_action_error().invalid_fields == ("Email",)

    def test_a_field_list_given_as_a_bare_string_is_not_split_into_letters(self) -> None:
        body = [{"errorCode": "INVALID_FIELD", "fields": "Email"}]

        assert to_connector_error(400, body).to_action_error().invalid_fields == ()

    def test_repeated_fields_are_reported_once_in_the_order_seen(self) -> None:
        body = [
            {"errorCode": "REQUIRED_FIELD_MISSING", "fields": ["LastName", "Email"]},
            {"errorCode": "REQUIRED_FIELD_MISSING", "fields": ["Email", "Phone"]},
        ]

        fields = to_connector_error(400, body).to_action_error().invalid_fields

        assert fields == ("LastName", "Email", "Phone")


class TestFallbacks:
    def test_status_is_used_when_the_body_carries_no_code(self) -> None:
        assert isinstance(to_connector_error(409, []), ConflictError)

    def test_an_unrecognised_server_error_is_treated_as_transient(self) -> None:
        assert isinstance(to_connector_error(503, ""), TransportError)

    def test_an_unrecognised_client_error_is_not_retried(self) -> None:
        error = to_connector_error(418, "")

        assert type(error) is ConnectorError
        assert error.to_action_error().retryable is False


class TestWhatReachesTheModel:
    def test_every_failure_states_a_next_step(self) -> None:
        codes = ["INVALID_SESSION_ID", "INSUFFICIENT_ACCESS", "DUPLICATES_DETECTED", "NOT_FOUND"]

        steps = [to_connector_error(400, rest_fault(c)).to_action_error().next_step for c in codes]

        assert all(step.strip() for step in steps)

    def test_a_long_provider_message_is_capped(self) -> None:
        body = rest_fault("INVALID_FIELD", "x" * 5000)

        reason = to_connector_error(400, body).to_action_error().reason

        assert len(reason) < 400
        assert "Salesforce code INVALID_FIELD" in reason


def test_an_ambiguous_upsert_is_a_conflict_rather_than_a_surprise() -> None:
    """The one failure Salesforce reports with a 3xx and no error code.

    An external id matching several records answers 300 with a list of their
    URLs. Every other rule here reads a code, and there is none, so without a
    status entry this arrives as connector.unexpected -- carrying no remedy,
    under a code upsert_record does not document.
    """
    failure = to_connector_error(
        300,
        [
            "/services/data/v67.0/sobjects/Contact/003xx000004TmiQAAS",
            "/services/data/v67.0/sobjects/Contact/003xx000004TmiRAAS",
        ],
    )

    assert failure.code == "salesforce.conflict"
    assert not failure.to_action_error().retryable
