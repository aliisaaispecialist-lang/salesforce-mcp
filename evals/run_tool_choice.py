"""Measure how often a model picks the right tool, and what it picks instead.

    python evals/run_tool_choice.py                  # the whole set
    python evals/run_tool_choice.py --limit 12       # a cheap smoke run
    python evals/run_tool_choice.py --effort low     # sweep the cost dial
    python evals/run_tool_choice.py --out runs/before.json

Nothing is executed. The model is given the published tool list and one
prompt, and the only thing recorded is which tool it reached for. That keeps a
run read-only against Salesforce and makes the numbers comparable between
before and after a change to a name or a description.

Four numbers come out, and one of them is the point:

  selection    of the prompts that have a right answer, how many got it
  abstention   of the prompts that have none, how many were correctly refused
  per tool     which tools are chosen reliably and which are not
  confusion    what was picked instead, which is the only output that says
               *why* a tool is losing

Selection and abstention are kept apart on purpose. A connector that always
picks something scores well on the first and nothing on the second, and this
one is built to refuse a request it cannot serve, so the refusal is exactly
what needs measuring.

Two backends. `--via cli` (the default) drives Claude Code against the real
MCP server, so it measures the descriptions as a host actually receives them
and it bills the Claude Code subscription. `--via api` calls the Messages API
with the tool list rebuilt into a `tools` array, which isolates the connector
from any host's own prompt and tools but bills an API account.

Either way it costs real money and nothing here runs under pytest. `anthropic`
is imported at call time so it stays out of the project's dependencies.
"""

# ruff: noqa: T201 - the report is the output; printing it is the point.

import argparse
import json
import pathlib
import sys
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import via_cli

from salesforce_connector.actions import registry
from salesforce_connector.protocol import surface

HAPPY_PATH = pathlib.Path(__file__).with_name("happy_path.jsonl")

MODEL = "claude-opus-5"
INPUT_PER_MTOK = 5.00
OUTPUT_PER_MTOK = 25.00

# What a host would put in front of the model. The connector's own guidance,
# used verbatim, because measuring anything else measures a fiction.
SYSTEM = (
    "You are connected to a Salesforce connector. Use its tools to answer the "
    "user. If no tool fits the request, say so plainly and call nothing.\n\n"
)


@dataclass(frozen=True)
class Answer:
    """One prompt, and what the model did with it."""

    prompt: str
    expected: str | None
    chosen: str | None
    note: str
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    trouble: str | None = None
    sent: Mapping[str, Any] = field(default_factory=dict)
    """The arguments the model filled in, when it called something."""

    @property
    def correct(self) -> bool:
        return self.chosen == self.expected


def published_tools() -> list[dict[str, Any]]:
    """The tools exactly as a client receives them.

    Read from the connector rather than written out here, so a rename or a
    description edit is picked up by the next run without anyone remembering
    to update the eval.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in surface.published(registry.descriptors())
    ]


def cases(where: pathlib.Path, limit: int | None) -> list[dict[str, Any]]:
    lines = [one for one in where.read_text(encoding="utf-8").splitlines() if one.strip()]
    loaded = [json.loads(one) for one in lines]
    return loaded[:limit] if limit else loaded


def asked(client: Any, tools: list[dict[str, Any]], case: dict[str, Any], effort: str) -> Answer:
    """Put one prompt to the model and record which tool it reached for.

    Thinking is left on deliberately. With it disabled, this model sometimes
    writes a tool call into its visible text instead of emitting a tool_use
    block: the turn succeeds, nothing is called, and no error is raised. In an
    eval that failure is invisible and would be scored as an abstention, so
    every number here would be wrong in the same direction.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM,
        tools=tools,
        tool_choice={"type": "auto"},
        # Through `extra_body` rather than as a named argument, because the
        # SDK's typed signature only grew `output_config` recently and this
        # machine has 0.76.0. The field is forwarded to the API either way, so
        # this works on an old SDK and a new one without pinning a version for
        # a script that is not part of the build.
        extra_body={"output_config": {"effort": effort}},
        messages=[{"role": "user", "content": case["prompt"]}],
    )
    picked = next((block.name for block in response.content if block.type == "tool_use"), None)
    return Answer(
        prompt=case["prompt"],
        expected=case["expect"],
        chosen=picked,
        note=case.get("note", ""),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def report(answers: list[Answer]) -> dict[str, Any]:
    """Turn the raw answers into the four numbers worth looking at."""
    # A case that could not be asked is not a case the model got wrong. Scoring
    # a rate-limited run as "chose nothing" would count it as a correct refusal
    # and flatter the abstention number.
    failed = [one for one in answers if one.trouble]
    scored = [one for one in answers if not one.trouble]
    positive = [one for one in scored if one.expected is not None]
    negative = [one for one in scored if one.expected is None]

    per_tool: dict[str, list[int]] = {}
    for one in positive:
        got, total = per_tool.setdefault(one.expected or "", [0, 0])
        per_tool[one.expected or ""] = [got + int(one.correct), total + 1]

    confused = Counter(
        (one.expected or "none", one.chosen or "none") for one in scored if not one.correct
    )
    spent = (
        sum(one.input_tokens for one in answers) / 1e6 * INPUT_PER_MTOK
        + sum(one.output_tokens for one in answers) / 1e6 * OUTPUT_PER_MTOK
        + sum(one.usd for one in answers)
    )

    return {
        "model": MODEL,
        "selection": _share(sum(one.correct for one in positive), len(positive)),
        "abstention": _share(sum(one.correct for one in negative), len(negative)),
        "per_tool": {name: _share(got, total) for name, (got, total) in sorted(per_tool.items())},
        "confusion": [
            {"expected": want, "chosen": got, "times": count}
            for (want, got), count in confused.most_common()
        ],
        "usd": round(spent, 4),
        "did_not_run": [{"prompt": one.prompt, "why": one.trouble} for one in failed],
    }


def _share(got: int, total: int) -> dict[str, Any]:
    return {"right": got, "of": total, "pct": round(100 * got / total, 1) if total else None}


def show(figures: dict[str, Any], answers: list[Answer]) -> None:
    # The CLI backend is killed the moment the choice is made, which is before
    # the event carrying the run's cost. Printing $0.0 there would be a lie;
    # printing nothing is the truth.
    priced = f"${figures['usd']}" if figures["usd"] else "not measured (killed at first choice)"
    print(f"\nmodel: {figures['model']}    cost: {priced}\n")
    for name in ("selection", "abstention"):
        one = figures[name]
        print(f"{name:12} {one['right']:>3}/{one['of']:<3} {one['pct']}%")

    print("\nper tool")
    for name, one in figures["per_tool"].items():
        flag = "  <-- " if one["pct"] is not None and one["pct"] < 100 else "      "  # noqa: PLR2004
        print(f"  {name:52} {one['right']}/{one['of']}{flag}")

    if figures["confusion"]:
        print("\nwhat it picked instead")
        for one in figures["confusion"]:
            print(f"  {one['expected']:44} -> {one['chosen']}  x{one['times']}")

    _show_skipped(figures)
    _show_misses(answers)


def _show_skipped(figures: dict[str, Any]) -> None:
    """Name the cases that could not be asked, so nobody reads round them."""
    if not figures["did_not_run"]:
        return
    print(f"\n{len(figures['did_not_run'])} cases did not run and are excluded")
    for one in figures["did_not_run"][:5]:
        print(f"  {one['why']}: {one['prompt']}")


def _show_misses(answers: list[Answer]) -> None:
    wrong = [one for one in answers if not one.correct and not one.trouble]
    if not wrong:
        return
    print("\nmisses")
    for one in wrong:
        print(f"  {one.prompt}")
        print(f"      wanted {one.expected}, got {one.chosen}")


def through_cli(case: dict[str, Any], config: pathlib.Path, effort: str) -> Answer:
    """Score one case by asking Claude Code, not the API."""
    picked, sent, spent, trouble = via_cli.chosen(case["prompt"], config, "opus", effort)
    return Answer(
        prompt=case["prompt"],
        expected=case["expect"],
        chosen=picked,
        note=case.get("note", ""),
        usd=spent,
        trouble=trouble,
        sent=sent,
    )


def _authenticated() -> Any:
    """Build an API client, or say plainly what is missing."""
    try:
        import anthropic
    except ImportError:
        raise SystemExit(
            "--via api needs the Anthropic SDK, which is not a dependency of "
            "the connector: pip install anthropic"
        ) from None
    try:
        client = anthropic.Anthropic()
        client.models.retrieve(MODEL)
    except TypeError as unauthenticated:
        raise SystemExit(
            f"No Anthropic credentials found: {unauthenticated}\n"
            f"Export ANTHROPIC_API_KEY, run `ant auth login`, or drop --via api "
            f"and let the default bill the Claude Code subscription instead."
        ) from None
    return client


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--limit", type=int, help="run only the first N cases")
    parsed.add_argument(
        "--cases",
        type=pathlib.Path,
        default=HAPPY_PATH,
        help="the case file to run (default: happy_path.jsonl)",
    )
    parsed.add_argument(
        "--via",
        default="cli",
        choices=["cli", "api"],
        help=(
            "cli drives Claude Code against the real MCP server and bills the "
            "subscription; api calls the Messages API and bills an API account "
            "(default: cli)"
        ),
    )
    parsed.add_argument(
        "--effort",
        default="high",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="how hard the model thinks before choosing (default: high, the API default)",
    )
    parsed.add_argument("--out", type=pathlib.Path, help="write the figures to this file as JSON")
    parsed.add_argument("--workers", type=int, default=4, help="how many calls to run at once")
    args = parsed.parse_args()

    to_run = cases(args.cases, args.limit)
    print(f"{len(to_run)} cases from {args.cases.name}, via={args.via}, effort={args.effort}")

    if args.via == "cli":
        config = via_cli.written_config(pathlib.Path(__file__).with_name(".eval-mcp.json"))

        def run_one(case: dict[str, Any]) -> Answer:
            return through_cli(case, config, args.effort)
    else:
        client = _authenticated()
        tools = published_tools()
        print(f"{len(tools)} tools published")

        def run_one(case: dict[str, Any]) -> Answer:
            return asked(client, tools, case, args.effort)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        answers = list(pool.map(run_one, to_run))

    figures = report(answers)
    show(figures, answers)
    if args.out:
        args.out.write_text(json.dumps(figures, indent=2), encoding="utf-8")
        print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
