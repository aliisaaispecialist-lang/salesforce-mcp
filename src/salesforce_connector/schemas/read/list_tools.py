"""The shortlist, so choosing a tool is not a search through fifteen.

Every tool is published at connection time with its full description and both
schemas, which is roughly nineteen thousand tokens of reading before a model
has decided anything. That is how MCP works and this does not change it: the
protocol has no way for a server to hand out tools according to what the user
turned out to want, and this connector could not use one if it existed, because
its server holds no per-caller state by design.

What this does instead is answer the question directly. Asked for reads, it
names the reads and what each is for, in a few hundred tokens rather than
nineteen thousand. The chosen tool is then read in full through
`salesforce_tool_describe_by_name` and called natively, so approval, validation and the
destructive-write hints all still apply.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)


class ListToolsInput(BaseModel):
    """Which half of the connector to list."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    # A Literal rather than a pattern, so the published schema carries
    # `enum: [read, write, all]`. A regex is exact and is written for
    # validators; an enum is the same constraint written where a model reading
    # the schema will actually see the choices.
    kind: Annotated[
        Literal["read", "write", "all"],
        Field(
            description=(
                "Required. Exactly one of: read, write, all.\n\n"
                "Send 'read' when the user is asking a question and nothing should "
                "change: finding, listing, counting, describing. Send 'write' when "
                "the user is asking for something to happen: creating, updating, "
                "linking, logging. Send 'all' only when you genuinely cannot tell "
                "which of the two it is."
            ),
            examples=["read", "write"],
        ),
    ]


class ToolSummary(BaseModel):
    """One tool, in a line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(description="The tool name to call, exactly as written.")]
    purpose: Annotated[str, Field(description="What it does, in one sentence.")]
    use_when: Annotated[str, Field(description="The situation it is the right choice for.")]
    required_inputs: Annotated[
        tuple[str, ...],
        Field(description="The fields that must be supplied. Types come from tool_schema."),
    ]
    changes_data: Annotated[bool, Field(description="True when calling it alters Salesforce.")]
    needs_approval: Annotated[
        bool,
        Field(description="True when the user must confirm before it will run."),
    ]


class ListToolsOutput(BaseModel):
    """The shortlist, and what to do with it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Annotated[str, Field(description="Which half was listed.")]
    tools: Annotated[
        tuple[ToolSummary, ...],
        Field(description="Every matching tool, in a stable order."),
    ]
    returned: Annotated[int, Field(description="How many tools are listed here.")]
    next_action: Annotated[
        str,
        Field(
            description=(
                "What to do next. Always present, because a shortlist is never the "
                "answer to anything on its own."
            )
        ),
    ]


SPEC = ActionSpec(
    action_id="salesforce.tool_list_by_kind",
    tool_name="salesforce_tool_list_by_kind",
    title="List the Salesforce tools for reading or for writing",
    summary=(
        "Name the tools that read Salesforce, or the tools that change it, each with "
        "what it is for and what it needs."
    ),
    when_to_use=(
        "you are about to do something in Salesforce and want the shortlist for that "
        "half rather than weighing every tool: ask for 'read' to answer a question, "
        "'write' to make something happen. Cheap, changes nothing, and safe to call "
        "first whenever the right tool is not obvious."
    ),
    when_not_to_use=(
        "you already know which tool you want, in which case call "
        "salesforce_tool_describe_by_name for its fields or simply call the tool; or you want "
        "the fields and types of one tool, which is salesforce_tool_describe_by_name. This "
        "lists tools and never touches Salesforce data."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(ListToolsInput),
    output_schema=schema_of(ListToolsOutput),
    examples=(
        ActionExample(
            title="Which tools change Salesforce",
            arguments={"kind": "write"},
            result={
                "kind": "write",
                "tools": [
                    {
                        "name": "salesforce_contact_create",
                        "purpose": "Create a new contact and return its record id.",
                        "use_when": "the user wants somebody added to Salesforce.",
                        "required_inputs": ["last_name", "idempotency_key"],
                        "changes_data": True,
                        "needs_approval": True,
                    }
                ],
                "returned": 1,
                "next_action": (
                    "Call salesforce_tool_describe_by_name with the tool_name you chose to see "
                    "its fields and the exact type each one expects."
                ),
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="kind",
            prompt="Do you want to read something from Salesforce, or change something in it?",
            choices=("read", "write", "all"),
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when="kind was not one of read, write, or all.",
            remedy="Send exactly one of those three words in lower case.",
        ),
    ),
)
