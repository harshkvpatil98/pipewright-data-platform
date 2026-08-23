"""Local implementations of the Phase 16 function catalogue.

Kept apart from ``pandas_backend`` because that module is the *algebra* --
nodes, joins, three-valued logic -- and this one is a lookup table of scalar
behaviour. Mixing them would bury the parts that are subtle in a hundred
one-liners.

Two rules run through everything here:

* **Null in, null out.** Every function is applied through :func:`_map`, which
  never calls the implementation for a missing value. A tool that turned NULL
  into "None" or 0 would corrupt data silently, and the all-null case is the
  one nobody tests by hand -- so it is not left to discipline.
* **Bad input yields null, not an exception.** A malformed date in row 40,000
  must not fail a pipeline that would otherwise have succeeded; the row becomes
  null and the count is reported. Functions that genuinely cannot proceed raise
  :class:`IRError` with something actionable instead.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import html
import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError


class _Missing:
    """Distinguishes "no value" from a legitimate ``None`` result."""


_MISSING = _Missing()


def _map(series: pd.Series, fn: Callable[[Any], Any]) -> pd.Series:
    """Apply ``fn`` to present values only, leaving nulls as nulls."""
    if len(series) == 0:
        return pd.Series([], dtype="object")

    def guarded(value: Any) -> Any:
        if value is None or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)):
            return None
        try:
            return fn(value)
        except (ValueError, TypeError, ArithmeticError, AttributeError, OverflowError):
            # The row is unusable, the pipeline is not. Callers that need to
            # know report the count of nulls they produced.
            return None

    return series.map(guarded)


def _text(series: pd.Series) -> pd.Series:
    """As text, without turning an integer column into "1.0"."""

    def render(value: Any) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    return _map(series, render)


def _boolean(series: pd.Series) -> pd.Series:
    return series.astype("boolean")


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _datetimes(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce", format="mixed")


def _literal(args: list[pd.Series], index: int, default: Any = _MISSING) -> Any:
    """The scalar value of an argument that must be constant across rows.

    Checked rather than assumed. These functions take their settings -- a
    pattern, a length, a period -- as arguments, and the IR does not stop
    somebody passing a *column* there. Reading row zero and applying it to every
    row would then be silently wrong for every row but the first, which is
    exactly the kind of wrongness nobody reports because the output looks fine.
    """
    if index >= len(args):
        if isinstance(default, _Missing):
            raise BadRequestError("A required argument is missing.")
        return default
    series = args[index]
    if len(series) == 0:
        return default if not isinstance(default, _Missing) else None

    try:
        distinct = series.dropna().unique()
    except TypeError:
        # Unhashable values cannot vary meaningfully as a setting anyway.
        distinct = []
    if len(distinct) > 1:
        raise BadRequestError(
            "This setting has to be the same for every row, but it was given a "
            f"column with {len(distinct)} different values."
        )

    value = series.iloc[0]
    return None if pd.isna(value) else value


# --------------------------------------------------------------------- text

_WHITESPACE = re.compile(r"\s+")
_HTML_TAG = re.compile(r"<[^>]*>")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WORDS = re.compile(r"\S+")


def _sentence_case(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return value
    return stripped[0].upper() + stripped[1:].lower()


def _slugify(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    return _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")


def _remove_accents(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    return "".join(character for character in folded if not unicodedata.combining(character))


def _fix_mojibake(value: str) -> str:
    """Undo the commonest encoding accident: UTF-8 bytes read as Latin-1.

    Only applied when the round trip actually succeeds *and* changes something,
    so text that was never broken is returned untouched.
    """
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired if repaired != value else value


def _truncate(value: str, length: int, suffix: str) -> str:
    if length <= 0:
        return ""
    if len(value) <= length:
        return value
    if len(suffix) >= length:
        return value[:length]
    return value[: length - len(suffix)] + suffix


def _extract_between(value: str, start: str, end: str) -> str | None:
    if not start or not end:
        return None
    first = value.find(start)
    if first == -1:
        return None
    begin = first + len(start)
    last = value.find(end, begin)
    return None if last == -1 else value[begin:last]


def _mask_partial(value: str, keep_last: int, keep_first: int, character: str) -> str:
    keep_last = max(0, keep_last)
    keep_first = max(0, keep_first)
    if keep_first + keep_last >= len(value):
        return value
    middle = len(value) - keep_first - keep_last
    return value[:keep_first] + (character or "*") * middle + (value[len(value) - keep_last :] if keep_last else "")


# ------------------------------------------------------------------ periods

_PERIODS = {
    "year": "YS",
    "quarter": "QS",
    "month": "MS",
    "week": "W-MON",
    "day": "D",
    "hour": "h",
    "minute": "min",
    "second": "s",
}


def _start_of(moment: Any, period: str) -> Any:
    stamp = pd.Timestamp(moment)
    if period == "year":
        return stamp.normalize().replace(month=1, day=1)
    if period == "quarter":
        first_month = 3 * ((stamp.month - 1) // 3) + 1
        return stamp.normalize().replace(month=first_month, day=1)
    if period == "month":
        return stamp.normalize().replace(day=1)
    if period == "week":
        return (stamp - pd.Timedelta(int(stamp.dayofweek), unit="D")).normalize()
    if period == "day":
        return stamp.normalize()
    if period == "hour":
        return stamp.floor("h")
    if period == "minute":
        return stamp.floor("min")
    if period == "second":
        return stamp.floor("s")
    raise BadRequestError(f"Unknown period {period!r}. Use one of: {', '.join(_PERIODS)}.")


def _end_of(moment: Any, period: str) -> Any:
    """The last instant of the period, not the first instant of the next one.

    Half-open ranges are right for filtering and wrong for display: a report
    labelled "to 2026-02-01" when it means January is a support ticket.
    """
    start = _start_of(moment, period)
    if period == "year":
        following = start.replace(year=start.year + 1)
    elif period == "quarter":
        following = start + pd.DateOffset(months=3)
    elif period == "month":
        following = start + pd.DateOffset(months=1)
    elif period == "week":
        following = start + pd.Timedelta(7, unit="D")
    elif period == "day":
        following = start + pd.Timedelta(1, unit="D")
    elif period == "hour":
        following = start + pd.Timedelta(1, unit="h")
    elif period == "minute":
        following = start + pd.Timedelta(1, unit="min")
    else:
        following = start + pd.Timedelta(1, unit="s")
    return pd.Timestamp(following) - pd.Timedelta(1, unit="us")


def _shift_months(moment: Any, months: int) -> Any:
    """Add whole months, clamping to the end of a shorter month.

    Written out rather than using `pd.DateOffset`, for two reasons: the offset
    object routes through a NumPy timedelta path pandas has deprecated, and
    doing the arithmetic here makes the clamping rule visible -- 31 January plus
    one month is 28 February, not 3 March.
    """
    stamp = pd.Timestamp(moment)
    total = (stamp.year * 12 + (stamp.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return stamp.replace(year=year, month=month, day=min(stamp.day, last_day))


def _business_days(start: Any, end: Any) -> int:
    """Whole weekdays from start to end, signed, excluding the end date."""
    first = pd.Timestamp(start).normalize().to_pydatetime().date()
    last = pd.Timestamp(end).normalize().to_pydatetime().date()
    sign = 1 if last >= first else -1
    low, high = (first, last) if sign == 1 else (last, first)
    return sign * int(np.busday_count(low, high))


def _add_business_days(start: Any, count: int) -> date:
    stamp = pd.Timestamp(start).normalize().to_pydatetime().date()
    step = 1 if count >= 0 else -1
    remaining = abs(int(count))
    current = stamp
    while remaining:
        current = current + timedelta(days=step)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _fiscal_year(moment: Any, start_month: int) -> int:
    stamp = pd.Timestamp(moment)
    if start_month < 1 or start_month > 12:
        raise BadRequestError("The fiscal year has to start in a month from 1 to 12.")
    # A year starting in month M is named for the calendar year it ends in,
    # which is the convention in every jurisdiction that does this at all.
    return stamp.year + 1 if start_month != 1 and stamp.month >= start_month else stamp.year


def _fiscal_quarter(moment: Any, start_month: int) -> int:
    stamp = pd.Timestamp(moment)
    if start_month < 1 or start_month > 12:
        raise BadRequestError("The fiscal year has to start in a month from 1 to 12.")
    offset = (stamp.month - start_month) % 12
    return offset // 3 + 1


# ------------------------------------------------------------- standardising

_TRUE_TOKENS = {"true", "t", "yes", "y", "1", "on"}
_FALSE_TOKENS = {"false", "f", "no", "n", "0", "off"}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
_URL = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_NON_DIGIT = re.compile(r"\D+")

#: ISO-3166 alpha-2 for the names that actually turn up in spreadsheets. A
#: partial map that reports misses beats a complete one nobody can audit.
_COUNTRIES_RAW = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.a.": "US",
    "u.s.": "US", "america": "US", "us": "US",
    "united kingdom": "GB", "great britain": "GB", "britain": "GB", "uk": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "gb": "GB",
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "france": "FR", "fr": "FR",
    "spain": "ES", "españa": "ES", "espana": "ES", "es": "ES",
    "italy": "IT", "italia": "IT", "it": "IT",
    "netherlands": "NL", "holland": "NL", "nl": "NL",
    "belgium": "BE", "be": "BE", "switzerland": "CH", "ch": "CH",
    "austria": "AT", "at": "AT", "sweden": "SE", "se": "SE",
    "norway": "NO", "no": "NO", "denmark": "DK", "dk": "DK",
    "finland": "FI", "fi": "FI", "ireland": "IE", "ie": "IE",
    "poland": "PL", "pl": "PL", "portugal": "PT", "pt": "PT",
    "canada": "CA", "ca": "CA", "mexico": "MX", "mx": "MX",
    "brazil": "BR", "brasil": "BR", "br": "BR", "argentina": "AR", "ar": "AR",
    "australia": "AU", "au": "AU", "new zealand": "NZ", "nz": "NZ",
    "india": "IN", "in": "IN", "china": "CN", "cn": "CN",
    "japan": "JP", "jp": "JP", "south korea": "KR", "korea": "KR", "kr": "KR",
    "singapore": "SG", "sg": "SG", "south africa": "ZA", "za": "ZA",
    "united arab emirates": "AE", "uae": "AE", "ae": "AE",
    "israel": "IL", "il": "IL", "turkey": "TR", "türkiye": "TR", "tr": "TR",
    "russia": "RU", "ru": "RU", "indonesia": "ID", "id": "ID",
}

#: Keyed without punctuation, so the lookup can normalise the input the same way.
_COUNTRIES = {
    re.sub(r"\s+", " ", name.replace(".", "").strip()): code
    for name, code in _COUNTRIES_RAW.items()
}

#: Dialling codes for the countries above, for E.164 normalisation.
_DIALLING = {
    "US": "1", "CA": "1", "GB": "44", "DE": "49", "FR": "33", "ES": "34",
    "IT": "39", "NL": "31", "BE": "32", "CH": "41", "AT": "43", "SE": "46",
    "NO": "47", "DK": "45", "FI": "358", "IE": "353", "PL": "48", "PT": "351",
    "MX": "52", "BR": "55", "AR": "54", "AU": "61", "NZ": "64", "IN": "91",
    "CN": "86", "JP": "81", "KR": "82", "SG": "65", "ZA": "27", "AE": "971",
    "IL": "972", "TR": "90", "RU": "7", "ID": "62",
}

#: The strings that mean "no value" in exported spreadsheets.
_NULL_TOKENS = {
    "", "na", "n/a", "n.a.", "null", "nil", "none", "nan", "-", "--", "?",
    "unknown", "not available", "#n/a", "#null!", "\\n",
}


def _standardise_phone(value: str, region: str) -> str | None:
    """Best-effort E.164. Returns null when the digits cannot be a number.

    Deliberately not a phone-number library: this handles the common cases and
    refuses the rest rather than confidently producing a number that does not
    dial.
    """
    raw = str(value).strip()
    explicit = raw.startswith("+")
    digits = _NON_DIGIT.sub("", raw)
    if not digits:
        return None
    if explicit:
        return f"+{digits}" if 8 <= len(digits) <= 15 else None

    code = _DIALLING.get((region or "").strip().upper())
    if code is None:
        return None
    if digits.startswith("00" + code):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = code + digits.lstrip("0")
    elif not digits.startswith(code):
        digits = code + digits
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def _standardise_postal(value: str, region: str) -> str:
    raw = str(value).strip().upper()
    code = (region or "").strip().upper()
    if code == "US":
        digits = _NON_DIGIT.sub("", raw)
        if len(digits) == 9:
            return f"{digits[:5]}-{digits[5:]}"
        return digits.zfill(5) if 0 < len(digits) <= 5 else raw
    if code == "GB":
        compact = re.sub(r"\s+", "", raw)
        return f"{compact[:-3]} {compact[-3:]}" if len(compact) > 3 else compact
    if code == "CA":
        compact = re.sub(r"\s+", "", raw)
        return f"{compact[:3]} {compact[3:]}" if len(compact) == 6 else compact
    return re.sub(r"\s+", " ", raw)


def _name_part(value: str, part: str) -> str | None:
    """Split a full name. Comma form ("Smith, John") is honoured first.

    Particles are kept with the surname, because "van der Berg" is one name and
    splitting it produces a person nobody can find again.
    """
    raw = re.sub(r"\s+", " ", str(value).strip())
    if not raw:
        return None
    if "," in raw:
        last, _, rest = raw.partition(",")
        pieces = rest.strip().split(" ") if rest.strip() else []
        first = pieces[0] if pieces else ""
        middle = " ".join(pieces[1:])
        last = last.strip()
    else:
        pieces = raw.split(" ")
        if len(pieces) == 1:
            first, middle, last = pieces[0], "", ""
        else:
            particles = {"van", "von", "de", "del", "della", "der", "den", "di", "da", "du", "la", "le", "bin", "ibn", "mac", "mc", "st"}
            index = len(pieces) - 1
            while index > 1 and pieces[index - 1].lower().strip(".") in particles:
                index -= 1
            first = pieces[0]
            middle = " ".join(pieces[1:index])
            last = " ".join(pieces[index:])
    return {"first": first, "middle": middle, "last": last}.get(part.lower(), None)


def _url_part(value: str, part: str) -> str | None:
    parsed = urllib.parse.urlsplit(str(value).strip())
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "domain": parsed.hostname or "",
        "path": parsed.path,
        "query": parsed.query,
        "fragment": parsed.fragment,
        "port": str(parsed.port) if parsed.port else "",
    }.get(part.lower())


def _detect_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, np.integer)):
        return "integer"
    if isinstance(value, (float, np.floating)):
        return "float"
    if isinstance(value, (datetime, pd.Timestamp, date)):
        return "timestamp"
    text_value = str(value).strip()
    if text_value.lower() in _TRUE_TOKENS | _FALSE_TOKENS:
        return "boolean"
    try:
        int(text_value)
        return "integer"
    except ValueError:
        pass
    try:
        float(text_value)
        return "float"
    except ValueError:
        pass
    if pd.notna(pd.to_datetime(text_value, errors="coerce", format="mixed")):
        return "timestamp"
    return "text"


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        current = [i]
        for j, b in enumerate(right, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b))
            )
        previous = current
    return previous[-1]


def _soundex(value: str) -> str:
    letters = [c for c in str(value).upper() if c.isalpha()]
    if not letters:
        return ""
    codes = {**dict.fromkeys("BFPV", "1"), **dict.fromkeys("CGJKQSXZ", "2"),
             **dict.fromkeys("DT", "3"), "L": "4", **dict.fromkeys("MN", "5"), "R": "6"}
    result = letters[0]
    previous = codes.get(letters[0], "")
    for character in letters[1:]:
        code = codes.get(character, "")
        if code and code != previous:
            result += code
        if character not in "HW":
            previous = code
    return (result + "000")[:4]


def _strip_currency(value: str, style: str) -> str:
    """Symbols and grouping removed, leaving something a number parser can read.

    Which character groups and which one is the decimal point depends on where
    the file came from, so it is a parameter rather than a guess.
    """
    raw = re.sub(r"[^\d.,\-+eE]", "", str(value)).strip()
    if style == "european":
        return raw.replace(".", "").replace(",", ".")
    return raw.replace(",", "")


def _parse_locale_number(value: str, style: str) -> float:
    raw = re.sub(r"[^\d,.\-+eE]", "", str(value).strip())
    if style == "european":
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    return float(raw)


def _json_path(value: Any, path: str) -> Any:
    """Read a dotted path out of parsed JSON. Missing keys give null."""
    import json

    document = value
    if isinstance(document, str):
        document = json.loads(document)
    for segment in str(path).split("."):
        if segment == "":
            continue
        if isinstance(document, dict):
            if segment not in document:
                return None
            document = document[segment]
        elif isinstance(document, list):
            index = int(segment)
            if index >= len(document) or index < -len(document):
                return None
            document = document[index]
        else:
            return None
    return document if document is None or isinstance(document, str) else json.dumps(document)


# --------------------------------------------------------------- the table

def _one(fn: Callable[[Any], Any]):
    return lambda args, expr: _map(args[0], fn)


def _text_one(fn: Callable[[str], Any]):
    return lambda args, expr: _map(_text(args[0]), fn)


HANDLERS: dict[str, Callable[[list[pd.Series], Any], pd.Series]] = {
    # -- text ------------------------------------------------------------
    "collapse_whitespace": _text_one(lambda v: _WHITESPACE.sub(" ", v).strip()),
    "remove_accents": _text_one(_remove_accents),
    "slugify": _text_one(_slugify),
    "strip_html": _text_one(lambda v: html.unescape(_HTML_TAG.sub("", v))),
    "title_case": _text_one(lambda v: v.title()),
    "sentence_case": _text_one(_sentence_case),
    "swap_case": _text_one(lambda v: v.swapcase()),
    "camel_to_words": _text_one(lambda v: _CAMEL.sub(" ", v)),
    "remove_control_characters": _text_one(lambda v: _CONTROL.sub("", v)),
    "fix_mojibake": _text_one(_fix_mojibake),
    "standardise_line_endings": _text_one(lambda v: v.replace("\r\n", "\n").replace("\r", "\n")),
    "trim_quotes": _text_one(lambda v: v.strip().strip("\"'")),
    "unescape": _text_one(lambda v: v.encode("utf-8", "backslashreplace").decode("unicode_escape")),
    "soundex": _text_one(_soundex),
    "word_count": _text_one(lambda v: len(_WORDS.findall(v))),
    "remove_characters": lambda args, expr: _map(
        _text(args[0]), lambda v, s=str(_literal(args, 1, "")): "".join(c for c in v if c not in s)
    ),
    "keep_characters": lambda args, expr: _map(
        _text(args[0]), lambda v, s=str(_literal(args, 1, "")): "".join(c for c in v if c in s)
    ),
    "count_occurrences": lambda args, expr: _map(
        _text(args[0]), lambda v, n=str(_literal(args, 1, "")): v.count(n) if n else 0
    ),
    "regex_count": lambda args, expr: _map(
        _text(args[0]), lambda v, p=str(_literal(args, 1, "")): len(re.findall(p, v))
    ),
    "extract_between": lambda args, expr: _map(
        _text(args[0]),
        lambda v, a=str(_literal(args, 1, "")), b=str(_literal(args, 2, "")): _extract_between(v, a, b),
    ),
    "extract_before": lambda args, expr: _map(
        _text(args[0]),
        lambda v, s=str(_literal(args, 1, "")): v.split(s)[0] if s and s in v else None,
    ),
    "extract_after": lambda args, expr: _map(
        _text(args[0]),
        lambda v, s=str(_literal(args, 1, "")): v.split(s, 1)[1] if s and s in v else None,
    ),
    "truncate_text": lambda args, expr: _map(
        _text(args[0]),
        lambda v, n=int(_literal(args, 1, 0) or 0), s=str(_literal(args, 2, "") or ""): _truncate(v, n, s),
    ),
    "normalise_unicode": lambda args, expr: _map(
        _text(args[0]),
        lambda v, f=str(_literal(args, 1, "NFC") or "NFC"): unicodedata.normalize(f.upper(), v),
    ),
    "char_at": lambda args, expr: _map(
        _text(args[0]),
        lambda v, i=int(_literal(args, 1, 1) or 1): v[i - 1] if 0 < i <= len(v) else None,
    ),
    "translate_characters": lambda args, expr: _map(
        _text(args[0]),
        lambda v, a=str(_literal(args, 1, "")), b=str(_literal(args, 2, "")): v.translate(
            str.maketrans(a, b[: len(a)].ljust(len(a), b[-1] if b else " ")) if a and b else {}
        ),
    ),
    "levenshtein": lambda args, expr: pd.Series(
        [
            None if pd.isna(a) or pd.isna(b) else _levenshtein(str(a), str(b))
            for a, b in zip(args[0], args[1])
        ],
        index=args[0].index,
        dtype="object",
    ),
    "similarity": lambda args, expr: pd.Series(
        [
            None
            if pd.isna(a) or pd.isna(b)
            else (
                1.0
                if str(a) == str(b)
                else 1.0 - _levenshtein(str(a), str(b)) / max(len(str(a)), len(str(b)), 1)
            )
            for a, b in zip(args[0], args[1])
        ],
        index=args[0].index,
        dtype="object",
    ),

    # -- numeric ----------------------------------------------------------
    "reciprocal": lambda args, expr: _map(
        _numeric(args[0]), lambda v: None if v == 0 else 1.0 / v
    ),
    "clamp": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, lo=_literal(args, 1, None), hi=_literal(args, 2, None): min(
            max(v, lo if lo is not None else v), hi if hi is not None else v
        ),
    ),
    "log": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, b=float(_literal(args, 1, 10) or 10): None
        if v <= 0 or b <= 0 or b == 1
        else float(np.log(v) / np.log(b)),
    ),
    "round_to": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, m=float(_literal(args, 1, 1) or 1): None if m == 0 else round(v / m) * m,
    ),
    "ceil_to": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, m=float(_literal(args, 1, 1) or 1): None if m == 0 else float(np.ceil(v / m) * m),
    ),
    "floor_to": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, m=float(_literal(args, 1, 1) or 1): None if m == 0 else float(np.floor(v / m) * m),
    ),
    "int_div": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, d=float(_literal(args, 1, 1) or 1): None if d == 0 else int(v // d),
    ),
    "is_even": lambda args, expr: _map(_numeric(args[0]), lambda v: int(v) % 2 == 0).astype("boolean"),
    "is_odd": lambda args, expr: _map(_numeric(args[0]), lambda v: int(v) % 2 == 1).astype("boolean"),

    # -- date and time ----------------------------------------------------
    "second": lambda args, expr: _map(_datetimes(args[0]), lambda v: pd.Timestamp(v).second),
    "day_of_year": lambda args, expr: _map(
        _datetimes(args[0]), lambda v: int(pd.Timestamp(v).dayofyear)
    ),
    "day_name": lambda args, expr: _map(_datetimes(args[0]), lambda v: pd.Timestamp(v).day_name()),
    "month_name": lambda args, expr: _map(
        _datetimes(args[0]), lambda v: pd.Timestamp(v).month_name()
    ),
    "add_months": lambda args, expr: _map(
        _datetimes(args[0]),
        lambda v, n=_literal(args, 1, 0): _shift_months(v, int(n or 0)),
    ),
    "add_years": lambda args, expr: _map(
        _datetimes(args[0]),
        lambda v, n=_literal(args, 1, 0): _shift_months(v, int(n or 0) * 12),
    ),
    "months_between": lambda args, expr: pd.Series(
        [
            None
            if pd.isna(a) or pd.isna(b)
            else (pd.Timestamp(b).year - pd.Timestamp(a).year) * 12
            + (pd.Timestamp(b).month - pd.Timestamp(a).month)
            for a, b in zip(_datetimes(args[0]), _datetimes(args[1]))
        ],
        index=args[0].index,
        dtype="object",
    ),
    "years_between": lambda args, expr: pd.Series(
        [
            None
            if pd.isna(a) or pd.isna(b)
            else (
                pd.Timestamp(b).year
                - pd.Timestamp(a).year
                - ((pd.Timestamp(b).month, pd.Timestamp(b).day) < (pd.Timestamp(a).month, pd.Timestamp(a).day))
            )
            for a, b in zip(_datetimes(args[0]), _datetimes(args[1]))
        ],
        index=args[0].index,
        dtype="object",
    ),
    "seconds_between": lambda args, expr: pd.Series(
        [
            None if pd.isna(a) or pd.isna(b) else (pd.Timestamp(b) - pd.Timestamp(a)).total_seconds()
            for a, b in zip(_datetimes(args[0]), _datetimes(args[1]))
        ],
        index=args[0].index,
        dtype="object",
    ),
    "start_of_period": lambda args, expr: _map(
        _datetimes(args[0]), lambda v, p=str(_literal(args, 1, "month") or "month"): _start_of(v, p)
    ),
    "end_of_period": lambda args, expr: _map(
        _datetimes(args[0]), lambda v, p=str(_literal(args, 1, "month") or "month"): _end_of(v, p)
    ),
    "is_weekend": lambda args, expr: _map(
        _datetimes(args[0]), lambda v: pd.Timestamp(v).dayofweek >= 5
    ).astype("boolean"),
    "business_days_between": lambda args, expr: pd.Series(
        [
            None if pd.isna(a) or pd.isna(b) else _business_days(a, b)
            for a, b in zip(_datetimes(args[0]), _datetimes(args[1]))
        ],
        index=args[0].index,
        dtype="object",
    ),
    "add_business_days": lambda args, expr: _map(
        _datetimes(args[0]),
        lambda v, n=int(_literal(args, 1, 0) or 0): _add_business_days(v, n),
    ),
    "fiscal_year": lambda args, expr: _map(
        _datetimes(args[0]), lambda v, m=int(_literal(args, 1, 1) or 1): _fiscal_year(v, m)
    ),
    "fiscal_quarter": lambda args, expr: _map(
        _datetimes(args[0]), lambda v, m=int(_literal(args, 1, 1) or 1): _fiscal_quarter(v, m)
    ),
    "age_years": lambda args, expr: _map(
        _datetimes(args[0]),
        lambda v: (
            lambda born, today: today.year
            - born.year
            - ((today.month, today.day) < (born.month, born.day))
        )(pd.Timestamp(v), pd.Timestamp(datetime.now(timezone.utc).date())),
    ),
    "epoch_seconds": lambda args, expr: _map(
        _datetimes(args[0]), lambda v: int(pd.Timestamp(v).timestamp())
    ),
    "from_epoch": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, u=str(_literal(args, 1, "seconds") or "seconds"): pd.Timestamp(
            float(v) / (1000.0 if u == "milliseconds" else 1.0), unit="s"
        ),
    ),
    "format_date": lambda args, expr: _map(
        _datetimes(args[0]),
        lambda v, f=str(_literal(args, 1, "%Y-%m-%d") or "%Y-%m-%d"): pd.Timestamp(v).strftime(f),
    ),
    "to_timezone": lambda args, expr: _map(
        _datetimes(args[0]),
        lambda v, z=str(_literal(args, 1, "UTC") or "UTC"): (
            pd.Timestamp(v).tz_localize("UTC") if pd.Timestamp(v).tzinfo is None else pd.Timestamp(v)
        ).tz_convert(z),
    ),

    # -- type and conversion ----------------------------------------------
    "to_integer": lambda args, expr: _map(
        _numeric(args[0]), lambda v: int(v) if np.isfinite(v) else None
    ),
    "to_boolean": lambda args, expr: _map(
        args[0],
        lambda v: True
        if (isinstance(v, bool) and v) or str(v).strip().lower() in _TRUE_TOKENS
        else (False if (isinstance(v, bool) or str(v).strip().lower() in _FALSE_TOKENS) else None),
    ).astype("boolean"),
    "to_timestamp": lambda args, expr: pd.to_datetime(args[0], errors="coerce", format="mixed"),
    "parse_number_locale": lambda args, expr: _map(
        _text(args[0]),
        lambda v, s=str(_literal(args, 1, "us") or "us"): _parse_locale_number(v, s),
    ),
    "strip_currency": lambda args, expr: _map(
        _text(args[0]),
        # Removes the grouping separator too, not just the symbol. Leaving
        # "1,200.50" behind produced text that looks like a number, fails to
        # parse, and becomes null one step later -- the commonest way a currency
        # column is silently emptied.
        lambda v, s=str(_literal(args, 1, "us") or "us"): _strip_currency(v, s),
    ),
    "detect_type": lambda args, expr: _map(args[0], _detect_type),
    "parse_json_path": lambda args, expr: _map(
        args[0], lambda v, p=str(_literal(args, 1, "") or ""): _json_path(v, p)
    ),

    # -- validation --------------------------------------------------------
    "is_email": lambda args, expr: _map(
        _text(args[0]), lambda v: bool(_EMAIL.match(v.strip()))
    ).astype("boolean"),
    "is_url": lambda args, expr: _map(
        _text(args[0]), lambda v: bool(_URL.match(v.strip()))
    ).astype("boolean"),
    "is_date": lambda args, expr: pd.to_datetime(
        args[0], errors="coerce", format="mixed"
    ).notna().astype("boolean"),
    "is_blank": lambda args, expr: pd.Series(
        [v is None or (not isinstance(v, (list, dict)) and pd.isna(v)) or str(v).strip() == "" for v in args[0]],
        index=args[0].index,
        dtype="boolean",
    ),
    "in_range": lambda args, expr: _map(
        _numeric(args[0]),
        lambda v, lo=_literal(args, 1, None), hi=_literal(args, 2, None): (
            (lo is None or v >= lo) and (hi is None or v <= hi)
        ),
    ).astype("boolean"),

    # -- encoding, hashing and privacy -------------------------------------
    "md5": _text_one(lambda v: hashlib.md5(v.encode("utf-8")).hexdigest()),
    "sha1": _text_one(lambda v: hashlib.sha1(v.encode("utf-8")).hexdigest()),
    "sha256": _text_one(lambda v: hashlib.sha256(v.encode("utf-8")).hexdigest()),
    "sha512": _text_one(lambda v: hashlib.sha512(v.encode("utf-8")).hexdigest()),
    "hmac_sha256": lambda args, expr: _map(
        _text(args[0]),
        lambda v, k=str(_literal(args, 1, "") or ""): hmac.new(
            k.encode("utf-8"), v.encode("utf-8"), hashlib.sha256
        ).hexdigest(),
    ),
    "base64_encode": _text_one(lambda v: base64.b64encode(v.encode("utf-8")).decode("ascii")),
    "base64_decode": _text_one(lambda v: base64.b64decode(v, validate=True).decode("utf-8")),
    "url_encode": _text_one(lambda v: urllib.parse.quote(v, safe="")),
    "url_decode": _text_one(urllib.parse.unquote),
    "html_escape": _text_one(lambda v: html.escape(v)),
    "html_unescape": _text_one(html.unescape),
    "mask_partial": lambda args, expr: _map(
        _text(args[0]),
        lambda v, last=int(_literal(args, 1, 4) or 0), first=int(_literal(args, 2, 0) or 0),
        ch=str(_literal(args, 3, "*") or "*"): _mask_partial(v, last, first, ch),
    ),
    "mask_full": lambda args, expr: _map(
        _text(args[0]), lambda v, ch=str(_literal(args, 1, "*") or "*"): ch * len(v)
    ),
    "pseudonymise": lambda args, expr: _map(
        _text(args[0]),
        # Salted, so the same value maps to the same token within a project and
        # to a different one across projects. An unsalted hash of an email is
        # reversible with a wordlist in minutes.
        lambda v, salt=str(_literal(args, 1, "") or ""): hashlib.sha256(
            (salt + "\x00" + v).encode("utf-8")
        ).hexdigest()[:16],
    ),

    # -- cleansing ---------------------------------------------------------
    "standardise_phone": lambda args, expr: _map(
        args[0], lambda v, r=str(_literal(args, 1, "US") or "US"): _standardise_phone(v, r)
    ),
    "standardise_email": _text_one(lambda v: v.strip().lower() or None),
    "standardise_url": _text_one(
        lambda v: (v.strip() if re.match(r"^[a-z]+://", v.strip(), re.I) else f"https://{v.strip()}")
        if v.strip()
        else None
    ),
    "standardise_postal_code": lambda args, expr: _map(
        _text(args[0]), lambda v, r=str(_literal(args, 1, "US") or "US"): _standardise_postal(v, r)
    ),
    "standardise_country": lambda args, expr: _map(
        _text(args[0]),
        # Dots and extra spacing are removed on both sides of the lookup, so
        # "U.S.A." and "usa" reach the same entry without the table needing a
        # row for every punctuation people use.
        lambda v, fmt=str(_literal(args, 1, "alpha2") or "alpha2"): _COUNTRIES.get(
            re.sub(r"\s+", " ", v.replace(".", "").strip().lower())
        ),
    ),
    "normalise_boolean": lambda args, expr: _map(
        args[0],
        lambda v: True
        if str(v).strip().lower() in _TRUE_TOKENS
        else (False if str(v).strip().lower() in _FALSE_TOKENS else None),
    ).astype("boolean"),
    "normalise_null_tokens": lambda args, expr: _map(
        _text(args[0]),
        lambda v, extra=str(_literal(args, 1, "") or ""): None
        if v.strip().lower() in _NULL_TOKENS
        or v.strip().lower() in {t.strip().lower() for t in extra.split(",") if t.strip()}
        else v,
    ),
    "name_part": lambda args, expr: _map(
        _text(args[0]), lambda v, p=str(_literal(args, 1, "first") or "first"): _name_part(v, p)
    ),
    "email_domain": _text_one(lambda v: v.strip().rsplit("@", 1)[-1].lower() if "@" in v else None),
    "url_part": lambda args, expr: _map(
        _text(args[0]), lambda v, p=str(_literal(args, 1, "host") or "host"): _url_part(v, p)
    ),
}
