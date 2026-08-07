"""Where a secret can hide in a log line, and whether censoring finds it.

Both cases here were leaks. The censor recursed into dictionaries but not
lists, and a Salesforce reply is very often a list of records, so a token at
records[0].access_token was written out whole. And the bearer pattern matched
word characters only, while a real session id contains an exclamation mark, so
half of it was masked and the rest printed.

The first version of the injection suite passed on a technicality: it asked
whether the full token appeared as one contiguous string, which stays true when
half of it leaks. These ask about the parts.
"""

import logging

import pytest
import structlog

from salesforce_connector.observability import censor_secrets, configure_logging, get_logger

# Shaped like the real thing: an org prefix, an exclamation mark, then the
# session material. The mark is what the old pattern stopped at.
SESSION_ID = "00D5g000004abc!AQEAQPgtNhpFCVwtBrokenHalfHere"
TAIL = "AQEAQPgtNhpFCVwtBrokenHalfHere"


def censor(**fields: object) -> dict[str, object]:
    return dict(censor_secrets(None, "info", dict(fields)))


@pytest.mark.security
class TestCensoringFollowsTheShapeOfTheData:
    def test_a_secret_inside_a_list_of_records_is_masked(self) -> None:
        censored = censor(response={"records": [{"Id": "003xx", "access_token": SESSION_ID}]})

        assert SESSION_ID not in str(censored)
        assert TAIL not in str(censored)

    def test_a_secret_nested_two_containers_deep_is_masked(self) -> None:
        censored = censor(body={"results": [{"tokens": [{"refresh_token": SESSION_ID}]}]})

        assert TAIL not in str(censored)

    def test_a_bare_list_of_secrets_is_masked(self) -> None:
        censored = censor(access_token=[SESSION_ID, SESSION_ID])

        assert TAIL not in str(censored)

    def test_ordinary_records_in_a_list_survive_intact(self) -> None:
        censored = censor(response={"records": [{"Id": "003xx", "Name": "Ada Lovelace"}]})

        assert "Ada Lovelace" in str(censored)
        assert "003xx" in str(censored)


@pytest.mark.security
class TestTheWholeTokenIsMaskedNotHalfOfIt:
    def test_a_session_id_containing_a_mark_is_masked_past_the_mark(self) -> None:
        censored = censor(detail=f"sent Authorization: Bearer {SESSION_ID}")

        rendered = str(censored)
        assert SESSION_ID not in rendered
        # The half that used to survive.
        assert TAIL not in rendered

    @pytest.mark.parametrize(
        "line",
        [
            f'{{"header": "Bearer {SESSION_ID}"}}',
            f"Authorization: Bearer {SESSION_ID}; charset=utf-8",
            f"[Bearer {SESSION_ID}]",
            f"Bearer {SESSION_ID}",
        ],
    )
    def test_it_is_masked_whatever_punctuation_follows_it(self, line: str) -> None:
        assert TAIL not in str(censor(detail=line))

    def test_the_word_bearer_alone_does_not_swallow_the_rest_of_a_sentence(self) -> None:
        censored = censor(detail="Bearer tokens are issued by the connected app")

        # Something is masked, but the sentence after the first word survives,
        # so an ordinary message is not reduced to nothing.
        assert "issued by the connected app" in str(censored)


@pytest.mark.security
class TestNoneOfThisReachesStderr:
    def test_a_list_of_records_carrying_a_token_logs_clean(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        structlog.reset_defaults()
        configure_logging(logging.INFO)

        get_logger().info(
            "client.response",
            body={"records": [{"Id": "003xx", "access_token": SESSION_ID}]},
        )

        captured = capsys.readouterr()
        assert TAIL not in captured.err
        assert captured.out == ""
