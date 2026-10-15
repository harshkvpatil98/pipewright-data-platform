"""Whether two pieces of text are the same thing written differently.

One answer to one question: the Assistant's entity resolution and the
recipe tools that match fuzzily (fuzzy joins and lookups, fuzzy
deduplication, clustering similar values, golden records) all ask it here.
Moved from `service_intelligence/matching.py` in E1 so the two could not
drift apart.

**Methods**, each a score from 0 to 1:

- ``letters`` (the Assistant's, and the default): the share of letters two
  values have in order, taking the better of the values as written and with
  their words sorted, so "Smith John" matches "John Smith".
- ``edits``: one minus the number of single-letter insertions, deletions and
  substitutions to turn one into the other, over the longer one's length.
- ``tokens``: how much the two share word by word, ignoring order and
  repeats ("Acme Widgets Ltd" and "Widgets Acme").
- ``jaro_winkler``: weighs agreement at the start, which suits short names.
- ``sound``: 1 when every word sounds alike by Soundex (English names), 0
  otherwise.

**Blocking, then comparison.** Comparing every value with every other is
quadratic; values are grouped by a cheap key (the first letters of the
normalised value with its words sorted, or the Soundex codes for ``sound``)
and only compared within a group, at most `MAX_BLOCK_SIZE` at a time. That
trades a few missed matches (a typo in the first letter) for matching being
usable at all, and it is stated wherever a result is shown.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

METHODS = ("letters", "edits", "tokens", "jaro_winkler", "sound")

# Business-entity noise that carries no identity.
SUFFIXES = (
    "ltd", "limited", "llc", "inc", "incorporated", "plc", "gmbh", "sa", "sas",
    "bv", "nv", "pty", "co", "corp", "corporation", "company", "holdings", "group",
)

# Below this, two strings are different things that happen to share letters.
DEFAULT_THRESHOLD = 0.86
# Above this, they are the same thing with near-certainty.
CONFIDENT_THRESHOLD = 0.95

# How many leading characters form a blocking key. Two is enough to cut the
# comparison count by orders of magnitude while keeping typo'd first letters
# rare enough to accept.
BLOCK_PREFIX = 2

# A ceiling on comparisons within one block, so a block of ten thousand
# identical prefixes cannot hang a request.
MAX_BLOCK_SIZE = 400


def normalise(value: Any, *, drop_suffixes: bool = True) -> str:
    """Strip everything that is formatting rather than identity."""
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [token for token in text.split() if token and not (drop_suffixes and token in SUFFIXES)]
    return " ".join(tokens)


def similarity(left: str, right: str, method: str = "letters") -> float:
    """How alike two normalised strings are, between 0 and 1."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if method == "letters":
        left_sorted = " ".join(sorted(left.split()))
        right_sorted = " ".join(sorted(right.split()))
        direct = SequenceMatcher(None, left, right).ratio()
        sorted_ratio = SequenceMatcher(None, left_sorted, right_sorted).ratio()
        return max(direct, sorted_ratio)
    if method == "edits":
        from rapidfuzz.distance import Levenshtein

        return float(Levenshtein.normalized_similarity(left, right))
    if method == "tokens":
        from rapidfuzz import fuzz

        return float(fuzz.token_set_ratio(left, right)) / 100
    if method == "jaro_winkler":
        from rapidfuzz.distance import JaroWinkler

        return float(JaroWinkler.normalized_similarity(left, right))
    if method == "sound":
        return 1.0 if sound_key(left) == sound_key(right) and sound_key(left) else 0.0
    raise ValueError(f"There is no matching method called {method!r}. Use one of: {', '.join(METHODS)}.")


def soundex(word: str) -> str:
    """The American Soundex code of one word: a letter and three digits."""
    letters = [c for c in word.upper() if "A" <= c <= "Z"]
    if not letters:
        return ""
    codes = {**dict.fromkeys("BFPV", "1"), **dict.fromkeys("CGJKQSXZ", "2"), **dict.fromkeys("DT", "3"),
             "L": "4", **dict.fromkeys("MN", "5"), "R": "6"}
    first = letters[0]
    out = [first]
    previous = codes.get(first, "")
    for letter in letters[1:]:
        code = codes.get(letter, "")
        if code and code != previous:
            out.append(code)
        if letter not in "HW":
            previous = code
    return ("".join(out) + "000")[:4]


def sound_key(value: str) -> str:
    return " ".join(sorted(code for code in (soundex(word) for word in value.split()) if code))


def blocking_key(value: str, method: str = "letters") -> str:
    """A cheap key that puts likely matches in the same bucket.

    Built from the *token-sorted* value, not the raw one: "Smith John" and
    "John Smith" are the same person, and a plain prefix puts them in different
    blocks where they are never compared.
    """
    if method == "sound":
        return sound_key(value)
    tokens = sorted(value.split())
    return "".join(tokens)[:BLOCK_PREFIX] if tokens else ""


def blocks(keys: Iterable[str], method: str = "letters") -> dict[str, list[str]]:
    """Group values by a cheap key so comparison stays sub-quadratic."""
    grouped: dict[str, list[str]] = {}
    for value in keys:
        grouped.setdefault(blocking_key(value, method), []).append(value)
    return grouped


def best_matches(wanted: Iterable[str], candidates: Iterable[str], *, method: str = "letters",
                 threshold: float = DEFAULT_THRESHOLD) -> dict[str, tuple[str, float]]:
    """For each normalised value wanted, the most alike candidate at or above the threshold.

    Ties go to the candidate that sorts first, so the answer never depends on
    the order the candidates came in.
    """
    by_block: dict[str, list[str]] = {}
    for candidate in sorted(set(candidates)):
        by_block.setdefault(blocking_key(candidate, method), []).append(candidate)
    found: dict[str, tuple[str, float]] = {}
    for value in set(wanted):
        if not value:
            continue
        best: tuple[str, float] | None = None
        for candidate in by_block.get(blocking_key(value, method), [])[:MAX_BLOCK_SIZE]:
            score = similarity(value, candidate, method)
            if score >= threshold and (best is None or score > best[1]):
                best = (candidate, score)
        if best is not None:
            found[value] = best
    return found


def clusters(values: Iterable[str], *, method: str = "letters",
             threshold: float = DEFAULT_THRESHOLD) -> dict[str, int]:
    """Number groups of alike values: every value to its group, linking alike pairs transitively.

    Groups are numbered in the order their first value sorts, so the same
    values always give the same numbers.
    """
    unique = sorted({value for value in values if value})
    parent = {value: value for value in unique}

    def root(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for block in blocks(unique, method).values():
        members = block[:MAX_BLOCK_SIZE]
        for index, left in enumerate(members):
            for right in members[index + 1:]:
                if similarity(left, right, method) >= threshold:
                    a, b = root(left), root(right)
                    if a != b:
                        parent[max(a, b)] = min(a, b)
    numbers: dict[str, int] = {}
    out: dict[str, int] = {}
    for value in unique:
        top = root(value)
        if top not in numbers:
            numbers[top] = len(numbers) + 1
        out[value] = numbers[top]
    return out
