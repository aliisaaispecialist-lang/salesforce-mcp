"""One tool's fields, with the type of each said in words.

A JSON Schema is exact and is written for validators. `{"anyOf": [{"type":
"number"}, {"type": "null"}]}` is precise about `amount`, and it is also the
shape a model skims as "some value", which is how a deal worth 45000 arrives
as the word "one" and fails before it reaches Salesforce.

So this reports every field three ways at once: the type in English, one
correct value written out, and whether it is required. A model that reads
"a number, written in digits, for example 45000" has nothing left to guess.

Nothing here is invented. The words are derived from the schema the tool
already publishes, so a field cannot be described here in a way the validator
would disagree with.
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from salesforce_connector.contract import ActionExample, ActionKind, RiskLevel
from salesforce_connector.schemas.envelope import (
    ActionSpec,
    ErrorGuidance,
    MissingInput,
    schema_of,
)


class ToolSchemaInput(BaseModel):
    """Which tool to explain."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    tool_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            description=(
                "Required. The tool to explain, named exactly as it is published, "
                "including the salesforce_ prefix. Call salesforce_list_tools first "
                "if you are not sure of the name; a wrong name is answered with the "
                "list of right ones."
            ),
            examples=["salesforce_create_opportunity"],
        ),
    ]


class FieldGuide(BaseModel):
    """One input field, and everything needed to fill it in correctly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(description="The argument name, spelled exactly.")]
    type: Annotated[
        str,
        Field(
            description=(
                "What to send, in words: text, a number written in digits, a date as "
                "YYYY-MM-DD, exactly one of a listed set. Follow this literally. A "
                "number means digits, so 45000 and never the word."
            )
        ),
    ]
    required: Annotated[bool, Field(description="True when the call fails if this is left out.")]
    example: Annotated[
        str | None,
        Field(
            default=None,
            description="One correct value, written exactly as it should be sent.",
        ),
    ] = None
    description: Annotated[str, Field(description="What the field means and how it is used.")]


class ToolSchemaOutput(BaseModel):
    """Everything needed to call one tool correctly the first time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: Annotated[str, Field(description="The tool explained.")]
    purpose: Annotated[str, Field(description="What it does.")]
    use_when: Annotated[str, Field(description="When it is the right tool.")]
    do_not_use_when: Annotated[
        str, Field(description="When it is the wrong tool, and which one is right instead.")
    ]
    changes_data: Annotated[bool, Field(description="True when calling it alters Salesforce.")]
    needs_approval: Annotated[
        bool,
        Field(
            description=(
                "True when the call is refused unless approved is true and the user "
                "has confirmed it."
            )
        ),
    ]
    fields: Annotated[
        tuple[FieldGuide, ...],
        Field(description="Every input field, required ones first."),
    ]
    example_call: Annotated[
        dict[str, Any],
        Field(description="A complete, valid set of arguments. Copy its shape."),
    ]
    errors: Annotated[
        tuple[dict[str, str], ...],
        Field(description="What can fail, and what to do about each."),
    ]


SPEC = ActionSpec(
    action_id="salesforce.tool_schema",
    tool_name="salesforce_tool_schema",
    title="Explain one Salesforce tool's fields and types",
    summary=(
        "Report one tool's input fields, the exact type each expects, a correct "
        "example value, and a complete worked call."
    ),
    when_to_use=(
        "you have chosen a tool and are about to call it, especially one taking a "
        "number, a date, or a value from a fixed set. Also after a call was rejected "
        "for a bad argument, to see what the field actually wanted."
    ),
    when_not_to_use=(
        "you do not know which tool you want yet, which is salesforce_list_tools; or "
        "you want Salesforce's own field names for an object, which is "
        "salesforce_describe_object. This explains this connector's tools, not "
        "Salesforce's data."
    ),
    kind=ActionKind.READ,
    risk=RiskLevel.LOW,
    idempotent=True,
    requires_approval=False,
    input_schema=schema_of(ToolSchemaInput),
    output_schema=schema_of(ToolSchemaOutput),
    examples=(
        ActionExample(
            title="Check what a field expects before sending it",
            arguments={"tool_name": "salesforce_create_opportunity"},
            result={
                "tool_name": "salesforce_create_opportunity",
                "purpose": "Create a sales opportunity and return its record id.",
                "use_when": "the user wants to record a new deal.",
                "do_not_use_when": "the deal already exists and needs changing.",
                "changes_data": True,
                "needs_approval": True,
                "fields": [
                    {
                        "name": "amount",
                        "type": "a number, written in digits",
                        "required": False,
                        "example": "45000",
                        "description": "Optional. Value of the deal in the org's currency.",
                    }
                ],
                "example_call": {"name": "Example Corp - renewal", "stage_name": "Qualify"},
                "errors": [
                    {
                        "code": "connector.invalid_input",
                        "when": "A field was the wrong type.",
                        "remedy": "Send the type named above and call again.",
                    }
                ],
            },
        ),
    ),
    missing_inputs=(
        MissingInput(
            field="tool_name",
            prompt="Which tool would you like explained? For example salesforce_create_contact.",
        ),
    ),
    errors=(
        ErrorGuidance(
            code="connector.invalid_input",
            when="No tool has that name.",
            remedy=(
                "The message lists every valid name. Use one of those exactly, "
                "including the salesforce_ prefix."
            ),
        ),
    ),
)
