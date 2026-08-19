"""Check that the committed documents survive being written to disk.

This exists because it happened. A PowerShell round-trip over `README.md` read
the file as the system codepage and wrote it back as UTF-8, which turns every
multi-byte character into the familiar run of accented punctuation. The result
is still valid UTF-8, so nothing complained: not git, not the linter, not the
type checker, not one of nine hundred tests. It was pushed, and the first thing
that noticed was a person reading the page and asking what the strange symbols
were.

That is the shape of fault worth a test. It is invisible to every tool in the
pipeline, it damages the one artefact most people will actually read, and the
edit that causes it looks entirely ordinary.

Four properties, each catching a different failure:

  **Valid UTF-8** catches a file written in the system codepage outright.
  **No BOM** catches Windows PowerShell's `-Encoding utf8`, which adds one; a
  leading BOM can also stop a Markdown parser seeing a first-line heading.
  **Not double-encoded** catches the case above, which passes both other checks
  and is the only one of the three that actually reached GitHub.
  **No replacement characters** catches a lossy decode, where a byte nothing
  could read became U+FFFD.

The double-encoding check is written as a reversal rather than as a search for
known bad sequences. The first version of this file searched, guessed the wrong
mapping, and passed against a genuinely corrupted README. Guessing was the
mistake: the damage depends on a codepage table, so the honest test is to
attempt the inverse operation and see whether it succeeds.

**One corruption here cannot catch, stated plainly.** A file written with
`-Encoding ascii`, or any encoder set to replace on failure, turns every
character it cannot represent into a literal `?`. The result is valid UTF-8,
carries no BOM, cannot be reversed, and contains no replacement character,
because a question mark is an ordinary thing for a document to contain. The
information is simply gone and nothing about the file says so. Only reading it
finds that one.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

DOCUMENTS = sorted(ROOT.glob("*.md")) + sorted((ROOT / "tests" / "postman").glob("*.json"))
NAMES = [path.name for path in DOCUMENTS]

BOM = b"\xef\xbb\xbf"

# The codepage a Windows shell falls back to, and therefore the one a file gets
# misread in. Deliberately not latin-1: cp1252 maps 0x80 through 0x9F to real
# characters, so the damage is not a byte-for-codepoint shift and cannot be
# recognised by eye or by a fixed list of sequences.
MISREAD_AS = "cp1252"


def _double_encoded(text: str) -> str | None:
    """Return what this text was before it was mangled, or None if it is fine.

    The reasoning is the inverse of the accident. Corruption happens when UTF-8
    bytes are read as `cp1252` and written back as UTF-8, so every character in
    a corrupted file came out of the cp1252 table and every one of them can go
    back into it. Undo both steps: if the result is valid UTF-8 and differs
    from what we started with, the file went through that round trip.

    A healthy document fails the first step. Genuine emoji, arrows and dashes
    have no cp1252 encoding at all, so there is nothing to reverse. A file of
    pure ASCII survives both steps unchanged, which is why the comparison
    matters as much as the success.
    """
    try:
        recovered = text.encode(MISREAD_AS).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return recovered if recovered != text else None


@pytest.mark.parametrize("path", DOCUMENTS, ids=NAMES)
def test_it_is_valid_utf8(path: Path) -> None:
    """Anything else is a file written in whatever codepage the machine had."""
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as broken:
        pytest.fail(
            f"{path.name} is not valid UTF-8: {broken}. It was probably written by a "
            f"tool that defaulted to the system codepage. Rewrite it as UTF-8."
        )


@pytest.mark.parametrize("path", DOCUMENTS, ids=NAMES)
def test_it_carries_no_byte_order_mark(path: Path) -> None:
    """Windows PowerShell's `-Encoding utf8` adds one, and nothing here wants it."""
    assert not path.read_bytes().startswith(BOM), (
        f"{path.name} starts with a UTF-8 BOM. Windows PowerShell's `Set-Content "
        f"-Encoding utf8` writes one; use `utf8NoBOM`, or write the file with a tool "
        f"that does not add it."
    )


@pytest.mark.parametrize("path", DOCUMENTS, ids=NAMES)
def test_nothing_was_lost_to_a_replacement_character(path: Path) -> None:
    """U+FFFD is what a decoder leaves behind when it gave up on a byte.

    It is never written on purpose, so one appearing means a character was read
    by something that could not represent it and the original is gone. Cheap to
    check and it names the position, which is usually enough to see what the
    character was meant to be.
    """
    text = path.read_text(encoding="utf-8")
    at = text.find("�")
    assert at == -1, (
        f"{path.name} contains a replacement character at position {at}, near "
        f"{text[max(0, at - 40) : at + 40]!r}. Something read this file with an "
        f"encoding that could not represent that character, and it is now lost."
    )


@pytest.mark.parametrize("path", DOCUMENTS, ids=NAMES)
def test_no_character_was_double_encoded(path: Path) -> None:
    """The one that actually shipped, and the only one nothing else can see."""
    text = path.read_text(encoding="utf-8")
    recovered = _double_encoded(text)
    assert recovered is None, (
        f"{path.name} was read as {MISREAD_AS} and written back as UTF-8, so every "
        f"multi-byte character in it is now a run of accented punctuation. Recover it "
        f"with text.encode({MISREAD_AS!r}).decode('utf-8'), which yields text starting "
        f"{recovered[:60]!r}."
    )
