"""Encoding, hashing and privacy tools.

The privacy tools are deliberately blunt: masking and hashing are one-way, and a
"reversible tokenisation" that stores its key beside the data is a false comfort
this platform should not offer.
"""

from __future__ import annotations

from service_transformations.tools.builders import integer, text as lit
from service_transformations.tools.declare import Example, Param, ParamKind, simple

CATEGORY = "Encoding & privacy"


def _ex(rows, expect, params=None):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column="value",
    )


simple("hash.md5", "MD5", CATEGORY,
       "MD5 digest, in hex. Fast and broken -- fine for change detection, never for secrets.",
       "md5",
       synonyms=("checksum", "digest", "fingerprint"),
       example=_ex(["abc"], ["900150983cd24fb0d6963f7d28e17f72"]))

simple("hash.sha1", "SHA-1", CATEGORY, "SHA-1 digest, in hex.", "sha1",
       example=_ex(["abc"], ["a9993e364706816aba3e25717850c26c9cd0d89d"]))

simple("hash.sha256", "SHA-256", CATEGORY, "SHA-256 digest, in hex.", "sha256",
       synonyms=("hash", "sha"),
       example=_ex(["abc"], ["ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"]))

simple("hash.sha512", "SHA-512", CATEGORY, "SHA-512 digest, in hex.", "sha512",
       example=_ex(["abc"], [
           "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
           "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
       ]))

simple("hash.hmac_sha256", "HMAC SHA-256", CATEGORY,
       "Keyed digest, so the same value hashes differently under a different key.",
       "hmac_sha256",
       synonyms=("keyed hash", "signature"),
       params=(Param("key", "Key", ParamKind.TEXT),),
       extra_args=lambda p: (lit(p["key"]),),
       example=_ex(["abc"], ["342e519ce0ad6c03a36b98eeb3f1d130db4813b9df4d1160eda488d712dc78ee"],
                   {"key": "k"}))

simple("privacy.pseudonymise", "Pseudonymise", CATEGORY,
       "A short, stable token per value, salted so it cannot be looked up elsewhere.",
       "pseudonymise",
       synonyms=("anonymise", "token", "de-identify", "surrogate"),
       params=(Param("salt", "Salt", ParamKind.TEXT,
                     help="Use a different salt per project. The same value maps to the "
                          "same token under one salt and a different one under another."),),
       extra_args=lambda p: (lit(p["salt"]),),
       example=_ex(["ada@example.com"], ["f2cead3438378b04"], {"salt": "project-1"}))

simple("privacy.mask_partial", "Mask, keeping the ends", CATEGORY,
       "Hide the middle, leaving a few characters visible for recognition.",
       "mask_partial",
       synonyms=("redact", "hide", "last four", "pii"),
       params=(
           Param("keep_last", "Keep at the end", ParamKind.INTEGER, default=4, minimum=0, maximum=100),
           Param("keep_first", "Keep at the start", ParamKind.INTEGER, default=0, minimum=0, maximum=100),
           Param("character", "Mask character", ParamKind.TEXT, required=False, default="*"),
       ),
       extra_args=lambda p: (
           integer(int(p["keep_last"])), integer(int(p["keep_first"])), lit(p["character"] or "*"),
       ),
       example=_ex(["4111111111111111"], ["************1111"],
                   {"keep_last": 4, "keep_first": 0, "character": "*"}))

simple("privacy.mask_full", "Mask completely", CATEGORY,
       "Replace every character, keeping the length.", "mask_full",
       synonyms=("redact fully", "blank out"),
       params=(Param("character", "Mask character", ParamKind.TEXT, required=False, default="*"),),
       extra_args=lambda p: (lit(p["character"] or "*"),),
       example=_ex(["secret"], ["******"], {"character": "*"}))

simple("encode.base64", "Base64 encode", CATEGORY, "Encode as base64.", "base64_encode",
       example=_ex(["abc"], ["YWJj"]))

simple("encode.base64_decode", "Base64 decode", CATEGORY,
       "Decode base64. Values that are not valid base64 become null.", "base64_decode",
       example=_ex(["YWJj", "!!"], ["abc", None]))

simple("encode.url", "URL encode", CATEGORY, "Percent-encode for use in a URL.", "url_encode",
       synonyms=("percent encode", "escape url"),
       example=_ex(["a b&c"], ["a%20b%26c"]))

simple("encode.url_decode", "URL decode", CATEGORY, "Decode percent-encoding.", "url_decode",
       example=_ex(["a%20b"], ["a b"]))

simple("encode.html", "HTML escape", CATEGORY,
       "Escape characters that would otherwise be markup.", "html_escape",
       synonyms=("escape html",),
       example=_ex(["<b>"], ["&lt;b&gt;"]))

simple("encode.html_unescape", "HTML unescape", CATEGORY,
       "Turn HTML entities back into characters.", "html_unescape",
       example=_ex(["&amp;"], ["&"]))
