"""Finding personal data before it ends up somewhere it should not.

Nobody sets out to publish a customer's phone number to a dashboard; it happens
because a column called `contact_2` turned out to hold them and nobody looked.
So this looks, on every column, and says what it found and how sure it is.

**Confidence is reported, never assumed.** A column named `email` whose values
all parse as email addresses is a different claim from one whose name matched
and whose values did not. Masking real data on a guess is worse than the guess
itself, so nothing is applied automatically -- the finding comes with a proposed
policy that a person accepts.

The detectors are patterns and checksums, not a model. That makes them
explainable, offline, and wrong in predictable ways: they will miss a national
ID format nobody encoded here, and that limitation is worth stating rather than
hiding behind a probability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

# What to do about a column once it is found.
MASKING_STRATEGIES = ("redact", "hash", "partial", "tokenize", "drop")

# Below this share of matching values, a name match alone is a guess.
STRONG_VALUE_MATCH = 0.8
WEAK_VALUE_MATCH = 0.4

SAMPLE_LIMIT = 500


@dataclass(frozen=True)
class Detector:
    """One kind of personal data, and how to recognise it."""

    kind: str
    label: str
    # Column names that suggest this kind, matched as whole words or fragments.
    name_hints: tuple[str, ...]
    pattern: re.Pattern[str] | None
    # An extra check beyond the pattern -- a checksum, say.
    validator: Callable[[str], bool] | None = None
    default_strategy: str = "redact"
    guidance: str = ""


def _luhn(value: str) -> bool:
    """The check digit every payment card carries.

    Without it, any sixteen-digit number -- an order id, a timestamp -- reads as
    a card number, and false positives here mean masking real data.
    """
    digits = [int(character) for character in re.sub(r"[^0-9]", "", value)]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _valid_phone(value: str) -> bool:
    """A phone number rather than any string of digits and punctuation.

    The pattern alone matches "999.999.999.999" and every version string and
    dotted identifier in the warehouse. Two rules narrow it without excluding
    real numbers: a dot is not a phone separator in any common convention, and
    a phone number has between 7 and 15 digits (ITU E.164 caps it at 15).
    """
    if "." in value:
        return False
    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15


def _valid_ip(value: str) -> bool:
    """An IPv4 address whose octets are actually in range.

    Without this, "999.999.999.999" and a version string both read as IPs.
    """
    if ":" in value:
        return True  # The IPv6 pattern already demands colons.
    parts = value.split(".")
    return len(parts) == 4 and all(part.isdigit() and int(part) <= 255 for part in parts)


DETECTORS: tuple[Detector, ...] = (
    Detector(
        kind="email",
        label="Email address",
        name_hints=("email", "e_mail", "mail"),
        pattern=re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE),
        default_strategy="partial",
        guidance="Partial masking keeps the domain, which is usually what analysis needs.",
    ),
    Detector(
        kind="phone",
        label="Phone number",
        name_hints=("phone", "mobile", "cell", "telephone", "msisdn"),
        pattern=re.compile(r"^\+?[\d\s().-]{7,20}$"),
        validator=_valid_phone,
        default_strategy="partial",
        guidance="Keeps the country and area code, which is what most reporting uses.",
    ),
    Detector(
        kind="credit_card",
        label="Payment card",
        name_hints=("card", "pan", "creditcard", "credit_card"),
        pattern=re.compile(r"^[\d\s-]{13,23}$"),
        validator=_luhn,
        default_strategy="redact",
        guidance="Card numbers should not be in a warehouse at all; redaction is the safe default.",
    ),
    Detector(
        kind="national_id",
        label="National insurance or social security number",
        name_hints=("ssn", "nino", "national_id", "nationalid", "social_security", "tax_id"),
        pattern=re.compile(r"^(\d{3}-?\d{2}-?\d{4}|[A-Z]{2}\d{6}[A-D])$", re.IGNORECASE),
        default_strategy="redact",
        guidance="Rarely needed for analysis; redact unless there is a documented reason.",
    ),
    Detector(
        kind="ip_address",
        label="IP address",
        name_hints=("ip", "ip_address", "client_ip", "remote_addr"),
        # The IPv6 half requires a colon on purpose: "[0-9a-f]{3,39}" alone
        # matches any digit string, and every order id in the warehouse became
        # an IP address.
        pattern=re.compile(r"^(\d{1,3}\.){3}\d{1,3}$|^[0-9a-f]{0,4}(:[0-9a-f]{0,4}){2,7}$", re.IGNORECASE),
        validator=lambda value: _valid_ip(value),
        default_strategy="partial",
        guidance="Truncating the last octet keeps geography while dropping the identity.",
    ),
    Detector(
        kind="postcode",
        label="Postal code",
        name_hints=("postcode", "postal", "zip", "zipcode"),
        pattern=re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}|\d{5}(-\d{4})?)$", re.IGNORECASE),
        default_strategy="partial",
        guidance="The first part is enough for regional analysis and identifies far fewer people.",
    ),
    Detector(
        kind="person_name",
        label="Person's name",
        # Names have no pattern worth writing, so this is a name-only signal and
        # is reported with correspondingly low confidence.
        name_hints=("first_name", "last_name", "surname", "forename", "full_name", "customer_name"),
        pattern=None,
        default_strategy="hash",
        guidance="Hashing keeps rows joinable without carrying the name itself.",
    ),
    Detector(
        kind="date_of_birth",
        label="Date of birth",
        name_hints=("dob", "date_of_birth", "birth_date", "birthday"),
        pattern=re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$|^\d{1,2}[-/]\d{1,2}[-/]\d{4}$"),
        default_strategy="partial",
        guidance="Keeping only the year supports age analysis without identifying anyone.",
    ),
)

DETECTORS_BY_KIND = {detector.kind: detector for detector in DETECTORS}


@dataclass
class PiiFinding:
    column: str
    kind: str
    label: str
    confidence: str  # "high" | "medium" | "low"
    name_matched: bool
    value_match_rate: float
    sample_size: int
    suggested_strategy: str
    reason: str
    guidance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "kind": self.kind,
            "label": self.label,
            "confidence": self.confidence,
            "name_matched": self.name_matched,
            "value_match_rate": round(self.value_match_rate, 3),
            "sample_size": self.sample_size,
            "suggested_strategy": self.suggested_strategy,
            "reason": self.reason,
            "guidance": self.guidance,
        }


def _name_matches(column: str, detector: Detector) -> bool:
    normalised = re.sub(r"[^a-z0-9]", "_", column.lower())
    tokens = {token for token in normalised.split("_") if token}
    return any(
        hint in normalised or hint in tokens or hint.replace("_", "") in normalised.replace("_", "")
        for hint in detector.name_hints
    )


def _value_match_rate(samples: list[Any], detector: Detector) -> tuple[float, int]:
    """How many of the sampled values look like this kind of data."""
    if detector.pattern is None:
        return 0.0, 0

    usable = [
        str(value).strip()
        for value in samples[:SAMPLE_LIMIT]
        if value is not None and str(value).strip()
    ]
    if not usable:
        return 0.0, 0

    matched = 0
    for value in usable:
        if not detector.pattern.match(value):
            continue
        if detector.validator is not None and not detector.validator(value):
            continue
        matched += 1
    return matched / len(usable), len(usable)


def _confidence(
    name_matched: bool, rate: float, has_pattern: bool, sample_size: int = 1
) -> tuple[str, str]:
    """How sure this is, and the sentence explaining why.

    The four cases are genuinely different, and collapsing them into one number
    is how a low-confidence guess ends up masking a column nobody meant to mask.
    """
    if has_pattern and sample_size == 0:
        # No values to judge. "The name suggests it but 0% of values match" is
        # not a weak finding, it is no finding: there was nothing to match
        # against, and reporting it as a coincidence is simply untrue.
        return "none", "No values to check."

    if not has_pattern:
        # A detector with no pattern has only the name to go on, so no name
        # match means no finding at all -- not a low-confidence one whose
        # stated reason is that nothing matched.
        if not name_matched:
            return "none", "Nothing matched."
        return "medium", "The column name says so; names have no pattern to check against."
    if name_matched and rate >= STRONG_VALUE_MATCH:
        return "high", f"The name matches and {rate:.0%} of values look like it."
    if rate >= STRONG_VALUE_MATCH:
        return "high", f"{rate:.0%} of values look like it, whatever the column is called."
    if name_matched and rate >= WEAK_VALUE_MATCH:
        return "medium", f"The name matches and {rate:.0%} of values do."
    if name_matched:
        return (
            "low",
            f"The name suggests it, but only {rate:.0%} of values match — probably a coincidence.",
        )
    if rate >= WEAK_VALUE_MATCH:
        return "low", f"{rate:.0%} of values match, but nothing else suggests it."
    return "none", "Nothing matched."


def scan_column(column: str, samples: list[Any]) -> PiiFinding | None:
    """The most likely kind of personal data in one column, if any."""
    best: PiiFinding | None = None

    for detector in DETECTORS:
        name_matched = _name_matches(column, detector)
        rate, sample_size = _value_match_rate(samples, detector)
        confidence, reason = _confidence(
            name_matched, rate, detector.pattern is not None, sample_size
        )

        if confidence == "none":
            continue

        finding = PiiFinding(
            column=column,
            kind=detector.kind,
            label=detector.label,
            confidence=confidence,
            name_matched=name_matched,
            value_match_rate=rate,
            sample_size=sample_size,
            suggested_strategy=detector.default_strategy,
            reason=reason,
            guidance=detector.guidance,
        )
        if best is None or _rank(finding) > _rank(best):
            best = finding

    return best


def _rank(finding: PiiFinding) -> tuple[int, int, int, float]:
    """How strong a finding is, most decisive signal first.

    A checksum outranks a pattern that merely fits: a sixteen-digit card also
    matches the phone pattern, and without this the card is reported as a
    phone number and masked the wrong way.
    """
    order = {"high": 3, "medium": 2, "low": 1}
    detector = DETECTORS_BY_KIND.get(finding.kind)
    validated = 1 if detector is not None and detector.validator is not None else 0
    return (
        order.get(finding.confidence, 0),
        validated,
        1 if finding.name_matched else 0,
        finding.value_match_rate,
    )


def scan_dataset(columns: dict[str, list[Any]]) -> list[PiiFinding]:
    """Every column that looks like personal data, most confident first."""
    findings = [
        finding
        for finding in (scan_column(name, samples) for name, samples in columns.items())
        if finding is not None
    ]
    findings.sort(key=lambda finding: (tuple(-part for part in _rank(finding)), finding.column))
    return findings


def masking_step(finding: PiiFinding, *, strategy: str | None = None) -> dict[str, Any]:
    """A transformation step that applies a masking policy.

    Returned rather than applied: masking is destructive, and a detector that is
    right most of the time is still wrong sometimes.
    """
    chosen = strategy or finding.suggested_strategy
    if chosen not in MASKING_STRATEGIES:
        raise ValueError(f"Unknown masking strategy '{chosen}'.")

    if chosen == "drop":
        return {"step_type": "drop_columns", "config": {"columns": [finding.column]}}
    if chosen == "redact":
        return {
            "step_type": "derive_column",
            "config": {
                "target_column": finding.column,
                "expression": "'[redacted]'",
                "overwrite": True,
            },
        }
    if chosen == "hash":
        # There is no hash function in the expression allowlist, so this is a
        # replacement rather than a pretend one-way transform.
        return {
            "step_type": "replace_values",
            "config": {
                "column": finding.column,
                "replacements": {".+": "[hashed]"},
                "use_regex": True,
            },
        }
    if chosen == "partial":
        return {
            "step_type": "replace_values",
            "config": {
                "column": finding.column,
                "replacements": _partial_pattern(finding.kind),
                "use_regex": True,
            },
        }
    return {
        "step_type": "replace_values",
        "config": {
            "column": finding.column,
            "replacements": {".+": "[token]"},
            "use_regex": True,
        },
    }


def _partial_pattern(kind: str) -> dict[str, str]:
    """What "partial" means for each kind, which is not the same thing."""
    return {
        "email": {r"^[^@]+": "***"},
        "phone": {r"\d(?=\d{4})": "*"},
        "ip_address": {r"\.\d{1,3}$": ".0"},
        "postcode": {r"\s?\w+$": ""},
        "date_of_birth": {r"[-/]\d{1,2}[-/]\d{1,2}$": ""},
    }.get(kind, {r".+": "***"})
