"""Which actions exist, and how to reach one by its id.

A lookup rather than a chain of comparisons: adding a sixth action means adding
a line here, not editing a branch that every other action also passes through.

The order is sorted rather than incidental. The protocol requires the tool list
not to vary between connections and recommends a stable order, because clients
cache it and its stability affects prompt cache hits. Dictionary insertion
order would satisfy that by accident today and break the day someone reorders
an import.
"""

from collections.abc import Mapping
from typing import Final

from salesforce_connector.actions.action import Action
from salesforce_connector.actions.add_activity_note import AddActivityNote
from salesforce_connector.actions.create_contact import CreateContact
from salesforce_connector.actions.create_opportunity import CreateOpportunity
from salesforce_connector.actions.link_contact_to_opportunity import LinkContactToOpportunity
from salesforce_connector.actions.search_contact import SearchContact
from salesforce_connector.actions.soql_query import SoqlQuery
from salesforce_connector.actions.update_contact import UpdateContact
from salesforce_connector.client import SalesforceClient
from salesforce_connector.contract import ActionDescriptor
from salesforce_connector.errors.model import ErrorContext, InvalidInputError

_ACTIONS: Final[tuple[type[Action], ...]] = (
    SearchContact,
    SoqlQuery,
    CreateContact,
    UpdateContact,
    CreateOpportunity,
    LinkContactToOpportunity,
    AddActivityNote,
)

BY_ID: Final[Mapping[str, type[Action]]] = {
    action.spec.action_id: action for action in sorted(_ACTIONS, key=lambda a: a.spec.action_id)
}


def descriptors() -> tuple[ActionDescriptor, ...]:
    """Describe every action, in a stable order, for a consumer to expose."""
    return tuple(
        ActionDescriptor(
            action_id=action.spec.action_id,
            tool_name=action.spec.tool_name,
            title=action.spec.title,
            description=action.spec.description(),
            kind=action.spec.kind,
            risk=action.spec.risk,
            idempotent=action.spec.idempotent,
            requires_approval=action.spec.requires_approval,
            input_schema=action.spec.input_schema,
            output_schema=action.spec.output_schema,
            examples=action.spec.examples,
        )
        for action in BY_ID.values()
    )


def build(action_id: str, client: SalesforceClient) -> Action:
    """Return the action with this id, ready to run.

    Args:
        action_id: The assigned id, for example `salesforce.search_contact`.
        client: The Salesforce client the action will use.

    Returns:
        The action.

    Raises:
        InvalidInputError: No action has that id. The message lists the ones
            that do, so a caller that guessed can correct itself in one step.
    """
    action = BY_ID.get(action_id)
    if action is None:
        raise InvalidInputError(
            f"{action_id!r} is not an action this connector offers.",
            ErrorContext(
                next_step=f"Use one of: {', '.join(BY_ID)}.",
                invalid_fields=("action_id",),
            ),
        )
    return action(client)
