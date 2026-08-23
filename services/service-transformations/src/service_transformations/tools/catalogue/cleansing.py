"""Cleansing and standardisation.

These are the tools that turn "the same thing, written eleven ways" into one
value. Every one of them reports null rather than guessing when it cannot be
confident -- a wrong country code is worse than a missing one, because nobody
goes looking for it.
"""

from __future__ import annotations

from service_transformations.tools.builders import call, text as lit
from service_transformations.tools.declare import Accepts, Example, Param, ParamKind, custom, simple

CATEGORY = "Cleansing"

REGIONS = ("US", "GB", "CA", "DE", "FR", "ES", "IT", "NL", "AU", "IN", "BR", "JP")


def _ex(rows, expect, params=None):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column="value",
    )


simple("clean.email", "Standardise an email", CATEGORY,
       "Trim and lower case. Empty results become null.", "standardise_email",
       synonyms=("normalise email", "lowercase email"),
       example=_ex([" Ada@Example.COM "], ["ada@example.com"]))

simple("clean.email_domain", "Email domain", CATEGORY,
       "The part after the @, lower case.", "email_domain",
       synonyms=("domain", "company from email"),
       example=_ex(["ada@Example.com", "not-an-email"], ["example.com", None]))

simple("clean.phone", "Standardise a phone number", CATEGORY,
       "Best-effort E.164. Numbers that cannot be made sense of become null.",
       "standardise_phone",
       synonyms=("e164", "telephone", "mobile", "normalise phone"),
       params=(Param("region", "Assume this country", ParamKind.SELECT, default="US",
                     options=REGIONS,
                     help="Used only when the number has no + prefix of its own."),),
       extra_args=lambda p: (lit(p["region"]),),
       example=_ex(["(555) 123-4567", "+44 20 7946 0958", "12"],
                   ["+15551234567", "+442079460958", None], {"region": "US"}))

simple("clean.url", "Standardise a URL", CATEGORY,
       "Add a scheme where one is missing.", "standardise_url",
       example=_ex(["example.com/x", "http://a.co"], ["https://example.com/x", "http://a.co"]))

simple("clean.url_part", "Part of a URL", CATEGORY,
       "Pull out the scheme, host, path, query or fragment.", "url_part",
       synonyms=("hostname", "domain from url", "path"),
       params=(Param("part", "Part", ParamKind.SELECT, default="host",
                     options=("scheme", "host", "path", "query", "fragment", "port")),),
       extra_args=lambda p: (lit(p["part"]),),
       example=_ex(["https://a.example.com/x?y=1"], ["a.example.com"], {"part": "host"}))

simple("clean.postal_code", "Standardise a postal code", CATEGORY,
       "Apply the country's usual spacing and padding.", "standardise_postal_code",
       synonyms=("zip", "postcode"),
       params=(Param("region", "Country", ParamKind.SELECT, default="US", options=REGIONS),),
       extra_args=lambda p: (lit(p["region"]),),
       example=_ex(["1234"], ["01234"], {"region": "US"}))

simple("clean.country", "Standardise a country", CATEGORY,
       "Map country names and abbreviations to an ISO code. Unrecognised names become null.",
       "standardise_country",
       synonyms=("iso country", "country code", "nationality"),
       params=(Param("format", "Output", ParamKind.SELECT, default="alpha2",
                     options=("alpha2",)),),
       extra_args=lambda p: (lit(p["format"]),),
       example=_ex(["United States", "u.s.a.", "Freedonia"], ["US", "US", None],
                   {"format": "alpha2"}))

simple("clean.name_part", "Split a full name", CATEGORY,
       "Take the first, middle or last name. Particles stay with the surname.",
       "name_part",
       synonyms=("first name", "surname", "last name", "split name"),
       params=(Param("part", "Part", ParamKind.SELECT, default="first",
                     options=("first", "middle", "last")),),
       extra_args=lambda p: (lit(p["part"]),),
       example=_ex(["Ada Lovelace", "van der Berg, Jan", "Jan van der Berg"],
                   ["Lovelace", "van der Berg", "van der Berg"], {"part": "last"}))

simple("clean.boolean_tokens", "Standardise yes/no", CATEGORY,
       "Read Y/N, yes/no, 1/0, on/off as true and false.", "normalise_boolean",
       accepts=Accepts.ANY, synonyms=("yes no", "y n", "true false"),
       example=_ex(["Y", "off", "maybe"], [True, False, None]))

simple("clean.line_endings", "Standardise line endings", CATEGORY,
       "Turn Windows and old-Mac line endings into plain newlines.",
       "standardise_line_endings",
       synonyms=("crlf", "newlines"),
       example=_ex(["a\r\nb"], ["a\nb"]))

simple("clean.control_characters", "Remove control characters", CATEGORY,
       "Strip the invisible characters that break exports.", "remove_control_characters",
       synonyms=("non printable", "invisible"),
       example=_ex(["a\x00b"], ["ab"]))

simple("clean.mojibake", "Fix mangled characters", CATEGORY,
       "Repair text where UTF-8 was read as Latin-1 -- the Â£ and â€™ problem.",
       "fix_mojibake",
       synonyms=("encoding", "garbled", "utf8", "latin1"),
       example=_ex(["Â£5"], ["£5"]))

simple("clean.trim_quotes", "Trim surrounding quotes", CATEGORY,
       "Remove quote marks left by a bad export.", "trim_quotes",
       synonyms=("unquote", "strip quotes"),
       example=_ex(['"hello"'], ["hello"]))

simple("clean.unescape", "Unescape", CATEGORY,
       "Turn backslash escapes back into the characters they stand for.", "unescape",
       example=_ex(["a\\tb"], ["a\tb"]))


def _standardise_case_and_space(column, params):
    """The two commonest cleanups, applied together because they are almost
    always wanted together and doing them as two steps doubles the recipe."""
    collapsed = call("collapse_whitespace", column)
    style = params["style"]
    if style == "lower":
        return call("lower", collapsed)
    if style == "upper":
        return call("upper", collapsed)
    if style == "title":
        return call("title_case", collapsed)
    return collapsed


custom("clean.standardise", "Tidy up text", CATEGORY,
       "Collapse whitespace and apply a consistent case, in one step.",
       _standardise_case_and_space,
       synonyms=("clean", "tidy", "normalise text", "standardise"),
       params=(Param("style", "Case", ParamKind.SELECT, default="none",
                     options=("none", "lower", "upper", "title")),),
       example=_ex(["  ADA   lovelace "], ["Ada Lovelace"], {"style": "title"}))
