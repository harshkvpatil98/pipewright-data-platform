"""Which bytes mean which characters.

A BOM settles it outright. Without one, nothing in the file says -- the same
bytes are a valid Latin-1 document and a valid Windows-1252 document and
usually a valid UTF-8 one too, and the only difference is what the text means.
So this reports a confidence and, when it is low, the bytes that made it
ambiguous, because "é or Ã© ?" is a question a person can answer in a second
and a library cannot answer at all.

The method, in order of how much it is worth:

1. **A BOM.** Certain. It is the file stating its own encoding.
2. **Pure ASCII.** Certain, and worth separating from "valid UTF-8": it means
   the question does not arise, so no review is needed.
3. **Valid UTF-8 with multi-byte sequences.** Very likely. UTF-8's structure is
   self-checking -- a continuation byte cannot appear without a lead byte -- so
   a long document decoding cleanly is strong evidence, and the odds of a
   Latin-1 document doing so by chance fall off a cliff with length.
4. **Otherwise a single-byte encoding**, scored on whether the high bytes make
   words. `Ã©` is two high bytes in a row where a Latin-1 text would have one.

This deliberately does not use `chardet`. It is not installed, and writing the
scoring out is what makes the evidence reportable: a library that returns
`("windows-1252", 0.73)` cannot show which bytes it was looking at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service_ingestion.sniff.evidence import (
    Candidate,
    Certainty,
    Finding,
    certain,
    preview_bytes,
)

#: Byte-order marks, longest first so UTF-32 is not read as UTF-16.
BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

#: The single-byte encodings worth considering, in the order they are tried.
#: `cp1252` before `latin-1` because `latin-1` decodes every byte sequence ever
#: produced -- it can never fail, so it can never be evidence of anything, and
#: putting it first would mean always answering "latin-1".
SINGLE_BYTE = ("cp1252", "iso-8859-15", "latin-1")

#: How much of the file is examined. Encoding does not change halfway through a
#: file, and reading 2GB to decide it would defeat the purpose.
SAMPLE_BYTES = 512 * 1024


@dataclass
class EncodingResult:
    encoding: str
    text: str
    finding: Finding

    def to_dict(self) -> dict[str, Any]:
        return {"encoding": self.encoding, "finding": self.finding.to_dict()}


def _bom(payload: bytes) -> tuple[str, int] | None:
    for mark, name in BOMS:
        if payload.startswith(mark):
            # utf-8-sig strips its own BOM; the UTF-16/32 codecs do too.
            return name, len(mark)
    return None


def _high_bytes(sample: bytes) -> list[int]:
    return [byte for byte in sample if byte >= 0x80]


def _utf8_multibyte_runs(sample: bytes) -> int:
    """How many multi-byte sequences a UTF-8 reading would contain.

    A document that decodes as UTF-8 with *no* multi-byte sequences is just
    ASCII, and says nothing about UTF-8 versus anything else.
    """
    runs = 0
    index = 0
    while index < len(sample):
        byte = sample[index]
        if byte < 0x80:
            index += 1
        elif 0xC0 <= byte < 0xE0:
            runs += 1
            index += 2
        elif 0xE0 <= byte < 0xF0:
            runs += 1
            index += 3
        elif byte >= 0xF0:
            runs += 1
            index += 4
        else:
            index += 1
    return runs


#: Byte values that are unassigned in Windows-1252. Seeing one means the file is
#: probably not cp1252, which is the single most useful negative signal here.
CP1252_UNDEFINED = frozenset({0x81, 0x8D, 0x8F, 0x90, 0x9D})


def _score_single_byte(sample: bytes, encoding: str) -> tuple[float, str]:
    """How much a single-byte reading looks like language rather than noise."""
    try:
        text = sample.decode(encoding)
    except UnicodeDecodeError:
        return 0.0, "does not decode"

    high = _high_bytes(sample)
    if not high:
        return 0.5, "no high bytes to judge by"

    if encoding == "cp1252" and any(byte in CP1252_UNDEFINED for byte in high):
        return 0.2, "contains bytes Windows-1252 leaves undefined"

    # Accented letters in real text sit inside words: `café`, `Müller`. Mojibake
    # clusters instead -- `Ã©`, `â€™` -- so a run of two or more high bytes is
    # the signal that this reading is the wrong one.
    clusters = 0
    run = 0
    for byte in sample:
        if byte >= 0x80:
            run += 1
        else:
            if run >= 2:
                clusters += 1
            run = 0
    if run >= 2:
        clusters += 1

    letters = sum(1 for character in text if character.isalpha() and ord(character) >= 0x80)
    ratio_letters = letters / max(len(high), 1)
    ratio_clustered = clusters / max(len(high), 1)

    score = 0.55 + 0.35 * ratio_letters - 0.5 * ratio_clustered
    reason = (
        f"{len(high)} high bytes, {ratio_letters:.0%} of them letters"
        + (f", {clusters} clustered" if clusters else "")
    )
    return max(0.0, min(0.95, score)), reason


def detect(payload: bytes) -> EncodingResult:
    """The encoding, the decoded text, and why."""
    sample = payload[:SAMPLE_BYTES]

    marked = _bom(sample)
    if marked is not None:
        name, width = marked
        try:
            text = payload.decode(name)
        except UnicodeDecodeError as exc:
            # A BOM that lies is rare and worth saying plainly rather than
            # falling back to something that merely does not crash.
            return _fallback(
                payload,
                f"The file starts with a {name} byte-order mark, but the bytes after "
                f"it are not valid {name}: {exc.reason}.",
            )
        return EncodingResult(
            encoding=name,
            # `utf-8-sig` consumes its own mark; the explicit-endian UTF-16 and
            # UTF-32 codecs do not, and a surviving U+FEFF glues itself to the
            # first column name -- so the table has a column called `\ufeffid`
            # that no formula or filter can ever match.
            text=text.lstrip("\ufeff"),
            finding=certain(
                "encoding",
                name,
                f"The file declares itself with a {name} byte-order mark.",
                evidence=[f"First {width} bytes: {preview_bytes(sample[:width], limit=width)}"],
            ),
        )

    if not _high_bytes(sample):
        # Reported as UTF-8 rather than ASCII, deliberately. Only the sample was
        # examined, and a 2GB file whose first 512KB are plain ASCII can still
        # have an accented name in row nine million -- read back as `ascii` that
        # row is corrupted, and UTF-8 reads every ASCII byte identically while
        # also handling the one that is not.
        return EncodingResult(
            encoding="utf-8",
            text=payload.decode("utf-8", errors="replace"),
            finding=certain(
                "encoding",
                "utf-8",
                (
                    "Every byte examined is below 128, so the encoding question does not "
                    "arise; UTF-8 reads them identically and covers anything further in."
                ),
            ),
        )

    candidates: list[Candidate] = []
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        utf8_ok = False
        utf8_reason = f"invalid at byte {exc.start}"
        utf8_evidence = preview_bytes(sample[max(0, exc.start - 12): exc.start + 12])
    else:
        utf8_ok = True
        runs = _utf8_multibyte_runs(sample)
        # Every additional well-formed sequence makes an accidental match less
        # likely; it saturates because ten is already conclusive.
        utf8_reason = f"{runs} well-formed multi-byte sequences"
        utf8_evidence = ""
        candidates.append(
            Candidate("utf-8", min(0.99, 0.80 + 0.02 * runs), utf8_reason)
        )

    for encoding in SINGLE_BYTE:
        score, reason = _score_single_byte(sample, encoding)
        if score > 0:
            candidates.append(Candidate(encoding, score, reason))

    evidence: list[str] = []
    if not utf8_ok:
        evidence.append(f"Not UTF-8 ({utf8_reason}): {utf8_evidence}")
    evidence.extend(_ambiguous_windows(sample))

    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    if not ranked:
        return _fallback(payload, "No candidate encoding decoded this file.")

    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    tied = runner_up is not None and runner_up.score / best.score >= 0.92

    # Two encodings that decode these particular bytes to the *same characters*
    # are not an ambiguity anybody needs to resolve. cp1252, iso-8859-15 and
    # latin-1 differ only on a handful of code points, and most documents use
    # none of them -- so reporting "é or é?" would be a question with one answer.
    if tied and runner_up is not None and _same_text(sample, str(best.value), str(runner_up.value)):
        tied = False
        equivalent = str(runner_up.value)
        evidence.append(
            f"{best.value} and {equivalent} decode these bytes identically, so the "
            "choice between them does not change what the file says."
        )
        runner_up = None

    if tied:
        certainty = Certainty.AMBIGUOUS
    elif best.score >= 0.85:
        certainty = Certainty.LIKELY
    else:
        certainty = Certainty.UNCERTAIN

    text = payload.decode(str(best.value), errors="replace")
    return EncodingResult(
        encoding=str(best.value),
        text=text,
        finding=Finding(
            stage="encoding",
            value=best.value,
            certainty=certainty,
            confidence=best.score,
            reason=(
                f"Read as {best.value}: {best.reason}."
                + (
                    f" {runner_up.value} fits almost as well, so this is a guess."
                    if tied and runner_up
                    else ""
                )
            ),
            candidates=ranked[:4],
            evidence=evidence,
        ),
    )


def _same_text(sample: bytes, first: str, second: str) -> bool:
    """Whether two encodings read these particular bytes the same way."""
    try:
        return sample.decode(first) == sample.decode(second)
    except (UnicodeDecodeError, LookupError):
        return False


def _ambiguous_windows(sample: bytes, *, limit: int = 3) -> list[str]:
    """The stretches of bytes a person would need to see to settle it."""
    found: list[str] = []
    index = 0
    while index < len(sample) and len(found) < limit:
        if sample[index] >= 0x80:
            start = max(0, index - 10)
            end = min(len(sample), index + 10)
            found.append(preview_bytes(sample[start:end], limit=end - start))
            index = end
        else:
            index += 1
    return found


def _fallback(payload: bytes, reason: str) -> EncodingResult:
    """Latin-1 decodes anything, which is why it is the last resort and not the first."""
    return EncodingResult(
        encoding="latin-1",
        text=payload.decode("latin-1", errors="replace"),
        finding=Finding(
            stage="encoding",
            value="latin-1",
            certainty=Certainty.UNCERTAIN,
            confidence=0.3,
            reason=(
                f"{reason} Falling back to latin-1, which decodes any byte sequence -- "
                "so this is a way to read the file, not a claim about what it says."
            ),
            evidence=_ambiguous_windows(payload[:SAMPLE_BYTES]),
        ),
    )
