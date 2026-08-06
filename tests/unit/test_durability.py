"""Not losing work, and not doing it twice.

Three properties: returned data cannot be altered after the fact, a key
remembers what it already achieved, and a step that finished stays finished.
"""

import pytest

from salesforce_connector.checkpoint import Journal
from salesforce_connector.idempotency import IdempotencyLedger, KeyState
from salesforce_connector.immutable import freeze


class TestFreezing:
    def test_a_mapping_cannot_be_changed(self) -> None:
        frozen = freeze({"Id": "003xx"})

        with pytest.raises(TypeError):
            frozen["Id"] = "other"

    def test_a_nested_mapping_cannot_be_changed_either(self) -> None:
        frozen = freeze({"records": [{"Id": "003xx"}]})

        with pytest.raises(TypeError):
            frozen["records"][0]["Id"] = "other"

    def test_a_list_becomes_a_tuple(self) -> None:
        assert freeze({"records": [1, 2]})["records"] == (1, 2)

    def test_a_string_is_not_taken_apart_into_letters(self) -> None:
        assert freeze({"Name": "Ada"})["Name"] == "Ada"

    def test_values_are_still_readable(self) -> None:
        frozen = freeze({"records": [{"Id": "003xx", "Email": "a@b.c"}], "done": True})

        assert frozen["records"][0]["Email"] == "a@b.c"
        assert frozen["done"] is True


class TestTheLedger:
    def test_an_unseen_key_is_simply_absent(self) -> None:
        assert IdempotencyLedger().find("key-1") is None

    def test_a_started_key_is_in_flight(self) -> None:
        ledger = IdempotencyLedger()

        assert ledger.begin("key-1").state is KeyState.IN_FLIGHT

    def test_beginning_a_completed_key_returns_what_it_produced(self) -> None:
        ledger = IdempotencyLedger()
        ledger.begin("key-1")
        ledger.complete("key-1", {"id": "003xx"})

        repeated = ledger.begin("key-1")

        assert repeated.state is KeyState.COMPLETED
        assert repeated.result is not None
        assert repeated.result["id"] == "003xx"

    def test_a_recorded_result_cannot_be_altered(self) -> None:
        ledger = IdempotencyLedger()
        entry = ledger.complete("key-1", {"id": "003xx"})

        assert entry.result is not None
        with pytest.raises(TypeError):
            entry.result["id"] = "tampered"  # type: ignore[index]

    def test_a_failed_key_is_marked_safe_to_try_again(self) -> None:
        ledger = IdempotencyLedger()
        ledger.begin("key-1")

        assert ledger.fail("key-1").state is KeyState.FAILED

    def test_keys_do_not_interfere_with_each_other(self) -> None:
        ledger = IdempotencyLedger()
        ledger.complete("key-1", {"id": "003xx"})
        ledger.begin("key-2")

        assert ledger.find("key-2") is not None
        assert ledger.find("key-2").state is KeyState.IN_FLIGHT  # type: ignore[union-attr]


class TestTheJournal:
    def test_nothing_is_done_at_the_start(self) -> None:
        journal = Journal()

        assert journal.completed() == ()
        assert journal.last() is None

    def test_a_recorded_step_is_known_to_be_done(self) -> None:
        journal = Journal()
        journal.record("create_opportunity", {"id": "006xx"})

        assert journal.is_done("create_opportunity")
        assert not journal.is_done("link_contact_role")

    def test_a_resume_can_read_what_a_finished_step_produced(self) -> None:
        journal = Journal()
        journal.record("create_opportunity", {"id": "006xx"})

        checkpoint = journal.find("create_opportunity")

        assert checkpoint is not None
        assert checkpoint.data["id"] == "006xx"

    def test_steps_are_reported_in_the_order_they_finished(self) -> None:
        journal = Journal()
        journal.record("create_opportunity")
        journal.record("link_contact_role")

        assert journal.completed() == ("create_opportunity", "link_contact_role")

    def test_the_furthest_point_reached_is_where_a_resume_begins(self) -> None:
        journal = Journal()
        journal.record("page_1", {"cursor": "01gxx-1"})
        journal.record("page_2", {"cursor": "01gxx-2"})

        last = journal.last()

        assert last is not None
        assert last.data["cursor"] == "01gxx-2"

    def test_recording_a_step_twice_does_not_duplicate_it(self) -> None:
        journal = Journal()
        journal.record("create_opportunity", {"id": "006xx"})
        journal.record("create_opportunity", {"id": "006xx"})

        assert journal.completed() == ("create_opportunity",)

    def test_what_a_step_produced_cannot_be_altered(self) -> None:
        journal = Journal()
        checkpoint = journal.record("create_opportunity", {"id": "006xx"})

        with pytest.raises(TypeError):
            checkpoint.data["id"] = "tampered"  # type: ignore[index]
