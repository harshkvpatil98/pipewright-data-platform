"""Text tools.

The largest category and the one people reach for first, because the commonest
problem in every dataset is that somebody typed it.
"""

from __future__ import annotations

from service_transformations.tools.builders import all_null, call, integer, text as lit
from service_transformations.tools.declare import Accepts, Example, Param, ParamKind, custom, simple

CATEGORY = "Text"


def _ex(rows, expect, params=None, column="value", note=""):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column=column,
        note=note,
    )


# ------------------------------------------------------------------ trimming

simple("text.trim", "Trim whitespace", CATEGORY,
       "Remove spaces, tabs and newlines from both ends.", "trim",
       synonyms=("strip", "whitespace", "clean spaces"),
       example=_ex(["  hello  ", "x"], ["hello", "x"]))

simple("text.trim_start", "Trim leading whitespace", CATEGORY,
       "Remove whitespace from the start only.", "ltrim",
       synonyms=("left trim", "lstrip"),
       example=_ex(["  hello  "], ["hello  "]))

simple("text.trim_end", "Trim trailing whitespace", CATEGORY,
       "Remove whitespace from the end only.", "rtrim",
       synonyms=("right trim", "rstrip"),
       example=_ex(["  hello  "], ["  hello"]))

simple("text.collapse_whitespace", "Collapse whitespace", CATEGORY,
       "Replace every run of whitespace with a single space, and trim the ends.",
       "collapse_whitespace",
       synonyms=("squeeze spaces", "normalise spaces", "double spaces"),
       example=_ex(["a   b \t c "], ["a b c"]))

# --------------------------------------------------------------------- case

simple("text.upper", "UPPERCASE", CATEGORY, "Convert to upper case.", "upper",
       synonyms=("capitals", "caps", "uppercase"),
       example=_ex(["hello"], ["HELLO"]))

simple("text.lower", "lowercase", CATEGORY, "Convert to lower case.", "lower",
       synonyms=("lowercase", "small"),
       example=_ex(["HELLO"], ["hello"]))

simple("text.title_case", "Title Case", CATEGORY,
       "Capitalise the first letter of every word.", "title_case",
       synonyms=("capitalise each word", "proper case", "initcap"),
       example=_ex(["hello world"], ["Hello World"]))

simple("text.sentence_case", "Sentence case", CATEGORY,
       "Capitalise the first letter and lower the rest.", "sentence_case",
       synonyms=("first letter capital",),
       example=_ex(["hELLO WORLD"], ["Hello world"]))

simple("text.swap_case", "Swap case", CATEGORY,
       "Turn upper case into lower and lower into upper.", "swap_case",
       synonyms=("invert case",),
       example=_ex(["Hello"], ["hELLO"]))

# ------------------------------------------------------------------ padding

simple("text.pad_left", "Pad left", CATEGORY,
       "Pad to a fixed width by adding characters on the left.", "lpad",
       synonyms=("zero pad", "leading zeros", "fixed width"),
       params=(
           Param("length", "Total length", ParamKind.INTEGER, default=10, minimum=1, maximum=4000),
           Param("fill", "Fill character", ParamKind.TEXT, required=False, default="0"),
       ),
       extra_args=lambda p: (integer(int(p["length"])), lit(p["fill"] or "0")),
       example=_ex(["42"], ["00042"], {"length": 5, "fill": "0"}))

simple("text.pad_right", "Pad right", CATEGORY,
       "Pad to a fixed width by adding characters on the right.", "rpad",
       params=(
           Param("length", "Total length", ParamKind.INTEGER, default=10, minimum=1, maximum=4000),
           Param("fill", "Fill character", ParamKind.TEXT, required=False, default=" "),
       ),
       extra_args=lambda p: (integer(int(p["length"])), lit(p["fill"] or " ")),
       example=_ex(["42"], ["42..."], {"length": 5, "fill": "."}))

simple("text.truncate", "Truncate", CATEGORY,
       "Shorten to a maximum length, optionally ending with a suffix.", "truncate_text",
       synonyms=("shorten", "cut", "limit length", "ellipsis"),
       params=(
           Param("length", "Maximum length", ParamKind.INTEGER, default=50, minimum=1, maximum=100000),
           Param("suffix", "Suffix", ParamKind.TEXT, required=False, default=""),
       ),
       extra_args=lambda p: (integer(int(p["length"])), lit(p["suffix"] or "")),
       example=_ex(["abcdefgh"], ["abc…"], {"length": 4, "suffix": "…"}))

# ---------------------------------------------------------------- extraction

simple("text.left", "First characters", CATEGORY,
       "Keep the first N characters.", "left",
       synonyms=("first n", "prefix", "head"),
       params=(Param("count", "How many", ParamKind.INTEGER, default=1, minimum=0, maximum=100000),),
       extra_args=lambda p: (integer(int(p["count"])),),
       example=_ex(["abcdef"], ["abc"], {"count": 3}))

simple("text.right", "Last characters", CATEGORY,
       "Keep the last N characters.", "right",
       synonyms=("last n", "suffix", "tail"),
       params=(Param("count", "How many", ParamKind.INTEGER, default=1, minimum=0, maximum=100000),),
       extra_args=lambda p: (integer(int(p["count"])),),
       example=_ex(["abcdef"], ["def"], {"count": 3}))

simple("text.substring", "Substring", CATEGORY,
       "Take a run of characters from a starting position. Positions count from 1.",
       "substring",
       synonyms=("mid", "slice", "extract range"),
       params=(
           Param("start", "Start position", ParamKind.INTEGER, default=1, minimum=1, maximum=100000),
           Param("length", "Length", ParamKind.INTEGER, default=1, minimum=0, maximum=100000),
       ),
       extra_args=lambda p: (integer(int(p["start"])), integer(int(p["length"]))),
       example=_ex(["abcdef"], ["bcd"], {"start": 2, "length": 3}))

simple("text.extract_before", "Extract before", CATEGORY,
       "Everything before the first occurrence of a marker.", "extract_before",
       synonyms=("split before", "up to"),
       params=(Param("marker", "Marker", ParamKind.TEXT, placeholder="@"),),
       extra_args=lambda p: (lit(p["marker"]),),
       example=_ex(["ada@example.com"], ["ada"], {"marker": "@"}))

simple("text.extract_after", "Extract after", CATEGORY,
       "Everything after the first occurrence of a marker.", "extract_after",
       synonyms=("split after", "from"),
       params=(Param("marker", "Marker", ParamKind.TEXT, placeholder="@"),),
       extra_args=lambda p: (lit(p["marker"]),),
       example=_ex(["ada@example.com"], ["example.com"], {"marker": "@"}))

simple("text.extract_between", "Extract between", CATEGORY,
       "The text between two markers. Null when either marker is missing.",
       "extract_between",
       synonyms=("inner text", "between delimiters"),
       params=(
           Param("start", "Opening marker", ParamKind.TEXT, placeholder="("),
           Param("end", "Closing marker", ParamKind.TEXT, placeholder=")"),
       ),
       extra_args=lambda p: (lit(p["start"]), lit(p["end"])),
       example=_ex(["Order (A-14) sent"], ["A-14"], {"start": "(", "end": ")"}))

simple("text.split_part", "Take one part", CATEGORY,
       "Split on a delimiter and keep one part. Parts count from 1.", "split_part",
       synonyms=("nth field", "delimiter", "csv part"),
       params=(
           Param("delimiter", "Delimiter", ParamKind.TEXT, default="-"),
           Param("index", "Which part", ParamKind.INTEGER, default=1, minimum=1, maximum=1000),
       ),
       extra_args=lambda p: (lit(p["delimiter"]), integer(int(p["index"]))),
       example=_ex(["2026-08-23"], ["08"], {"delimiter": "-", "index": 2}))

simple("text.char_at", "Character at position", CATEGORY,
       "The single character at a position, counting from 1.", "char_at",
       params=(Param("position", "Position", ParamKind.INTEGER, default=1, minimum=1, maximum=100000),),
       extra_args=lambda p: (integer(int(p["position"])),),
       example=_ex(["abc"], ["b"], {"position": 2}))

# ------------------------------------------------------------------- regex

simple("text.regex_extract", "Extract with a pattern", CATEGORY,
       "The first capture group of a regular expression.", "regex_extract",
       synonyms=("regex", "pattern", "capture"),
       params=(Param("pattern", "Pattern", ParamKind.TEXT, placeholder=r"(\d+)"),),
       extra_args=lambda p: (lit(p["pattern"]),),
       example=_ex(["order 4471"], ["4471"], {"pattern": r"(\d+)"}))

simple("text.regex_replace", "Replace with a pattern", CATEGORY,
       "Replace everything matching a regular expression.", "regex_replace",
       synonyms=("regex replace", "substitute"),
       params=(
           Param("pattern", "Pattern", ParamKind.TEXT, placeholder=r"\s+"),
           Param("replacement", "Replacement", ParamKind.TEXT, required=False, default=""),
       ),
       extra_args=lambda p: (lit(p["pattern"]), lit(p["replacement"] or "")),
       example=_ex(["a1b2"], ["ab"], {"pattern": r"\d", "replacement": ""}))

simple("text.regex_count", "Count pattern matches", CATEGORY,
       "How many times a regular expression matches.", "regex_count",
       accepts=Accepts.TEXTUAL,
       params=(Param("pattern", "Pattern", ParamKind.TEXT, placeholder=r"\d"),),
       extra_args=lambda p: (lit(p["pattern"]),),
       example=_ex(["a1b2c3"], [3], {"pattern": r"\d"}))

# ------------------------------------------------------------ replace & find

simple("text.replace", "Find and replace", CATEGORY,
       "Replace every occurrence of one piece of text with another.", "replace",
       synonyms=("substitute", "swap text"),
       params=(
           Param("find", "Find", ParamKind.TEXT),
           Param("replacement", "Replace with", ParamKind.TEXT, required=False, default=""),
       ),
       extra_args=lambda p: (lit(p["find"]), lit(p["replacement"] or "")),
       example=_ex(["a-b-c"], ["a_b_c"], {"find": "-", "replacement": "_"}))

simple("text.position", "Position of text", CATEGORY,
       "Where a piece of text first appears, counting from 1. Zero when absent.",
       "position",
       synonyms=("find", "index of", "search"),
       params=(Param("needle", "Text to find", ParamKind.TEXT),),
       extra_args=lambda p: (lit(p["needle"]),),
       example=_ex(["abcabc"], [2], {"needle": "b"}))

simple("text.count_occurrences", "Count occurrences", CATEGORY,
       "How many times a piece of text appears.", "count_occurrences",
       params=(Param("needle", "Text to count", ParamKind.TEXT),),
       extra_args=lambda p: (lit(p["needle"]),),
       example=_ex(["banana"], [3], {"needle": "a"}))

simple("text.remove_characters", "Remove characters", CATEGORY,
       "Delete every character in a set.", "remove_characters",
       synonyms=("strip characters", "delete chars"),
       params=(Param("characters", "Characters", ParamKind.TEXT, placeholder="$,"),),
       extra_args=lambda p: (lit(p["characters"]),),
       example=_ex(["$1,200"], ["1200"], {"characters": "$,"}))

simple("text.keep_characters", "Keep only characters", CATEGORY,
       "Delete everything except the characters in a set.", "keep_characters",
       synonyms=("whitelist characters", "digits only"),
       params=(Param("characters", "Characters to keep", ParamKind.TEXT, placeholder="0123456789"),),
       extra_args=lambda p: (lit(p["characters"]),),
       example=_ex(["+1 (555) 123"], ["1555123"], {"characters": "0123456789"}))

simple("text.translate", "Swap characters", CATEGORY,
       "Replace characters one for one, like tr.", "translate_characters",
       params=(
           Param("from_characters", "From", ParamKind.TEXT, placeholder="abc"),
           Param("to_characters", "To", ParamKind.TEXT, placeholder="xyz"),
       ),
       extra_args=lambda p: (lit(p["from_characters"]), lit(p["to_characters"])),
       example=_ex(["abc"], ["xyz"], {"from_characters": "abc", "to_characters": "xyz"}))

# ---------------------------------------------------------------- structure

simple("text.length", "Length", CATEGORY, "How many characters.", "length",
       synonyms=("size", "characters", "len"),
       example=_ex(["hello"], [5]))

simple("text.word_count", "Word count", CATEGORY,
       "How many whitespace-separated words.", "word_count",
       example=_ex(["one two  three"], [3]))

simple("text.reverse", "Reverse", CATEGORY, "Reverse the characters.", "reverse",
       synonyms=("backwards",),
       example=_ex(["abc"], ["cba"]))

simple("text.repeat", "Repeat", CATEGORY, "Repeat the text N times.", "repeat",
       params=(Param("times", "Times", ParamKind.INTEGER, default=2, minimum=0, maximum=1000),),
       extra_args=lambda p: (integer(int(p["times"])),),
       example=_ex(["ab"], ["ababab"], {"times": 3}))

simple("text.camel_to_words", "Split camelCase", CATEGORY,
       "Insert spaces at camel-case boundaries.", "camel_to_words",
       synonyms=("camel case", "split words", "unCamel"),
       example=_ex(["orderLineItem"], ["order Line Item"]))

simple("text.slugify", "Make a slug", CATEGORY,
       "Lower case, accents folded, everything else turned into hyphens.", "slugify",
       synonyms=("url slug", "kebab", "handle"),
       example=_ex(["Crème Brûlée!"], ["creme-brulee"]))

simple("text.remove_accents", "Remove accents", CATEGORY,
       "Fold accented letters to their plain equivalents.", "remove_accents",
       synonyms=("unaccent", "ascii fold", "diacritics"),
       example=_ex(["Zoë"], ["Zoe"]))

simple("text.strip_html", "Strip HTML", CATEGORY,
       "Remove tags and decode entities, leaving the text.", "strip_html",
       synonyms=("remove tags", "html to text"),
       example=_ex(["<b>Hi</b>&amp;bye"], ["Hi&bye"]))

simple("text.normalise_unicode", "Normalise Unicode", CATEGORY,
       "Apply a Unicode normalisation form so equal-looking text compares equal.",
       "normalise_unicode",
       synonyms=("nfc", "nfkc", "unicode"),
       params=(Param("form", "Form", ParamKind.SELECT, default="NFC",
                     options=("NFC", "NFD", "NFKC", "NFKD")),),
       extra_args=lambda p: (lit(p["form"]),),
       example=_ex(["ﬁt"], ["fit"], {"form": "NFKC"}))

simple("text.soundex", "Soundex code", CATEGORY,
       "A four-character phonetic code, for matching names that sound alike.",
       "soundex",
       synonyms=("phonetic", "sounds like", "fuzzy name"),
       example=_ex(["Robert", "Rupert"], ["R163", "R163"]))

# -------------------------------------------------------------- predicates

simple("text.starts_with", "Starts with", CATEGORY,
       "True when the text begins with a given prefix.", "starts_with",
       synonyms=("begins with", "prefix"),
       params=(Param("prefix", "Prefix", ParamKind.TEXT),),
       extra_args=lambda p: (lit(p["prefix"]),),
       example=_ex(["abc", "xbc"], [True, False], {"prefix": "a"}))

simple("text.ends_with", "Ends with", CATEGORY,
       "True when the text ends with a given suffix.", "ends_with",
       synonyms=("suffix",),
       params=(Param("suffix", "Suffix", ParamKind.TEXT),),
       extra_args=lambda p: (lit(p["suffix"]),),
       example=_ex(["abc", "abx"], [True, False], {"suffix": "c"}))

simple("text.contains", "Contains", CATEGORY,
       "True when the text contains a given piece.", "contains",
       synonyms=("includes", "has"),
       params=(Param("needle", "Text", ParamKind.TEXT),),
       extra_args=lambda p: (lit(p["needle"]),),
       example=_ex(["abc", "xyz"], [True, False], {"needle": "b"}))


def _concat_with(column, params):
    """Join this column to others with a separator, skipping nulls.

    Skipping is the point: joining a first and last name where the middle name
    is null must not produce "Ada  Lovelace" with two spaces.
    """
    from service_transformations.ir.expressions import Case, Column

    separator = params["separator"]
    pieces = [column, *[Column(name) for name in params["columns"]]]
    rendered = [call("to_text", piece) for piece in pieces]
    guarded = [
        Case(branches=((call("is_null", piece), lit("")),), default=part)
        for piece, part in zip(pieces, rendered)
    ]
    # Join, then squeeze the separators a null left behind.
    joined = guarded[0]
    for part in guarded[1:]:
        joined = call("concat", joined, lit(separator), part)
    squeezed = (
        call("collapse_whitespace", joined)
        if separator == " "
        else call("trim", call("regex_replace", joined, lit(f"({_escape(separator)})+"), lit(separator)))
    )
    # All inputs null means there was nothing to merge; joining nothing to
    # nothing is empty text, which is a value nobody entered.
    from service_transformations.ir.expressions import Case, Literal
    from shared_python.types import STRING

    return Case(
        branches=((all_null(*pieces), Literal(value=None, type=STRING)),),
        default=squeezed,
    )


def _escape(value: str) -> str:
    import re

    return re.escape(value)


custom("text.merge_columns", "Merge columns", CATEGORY,
       "Join this column to others with a separator, skipping the empty ones.",
       _concat_with,
       synonyms=("concatenate", "combine columns", "join text"),
       params=(
           Param("columns", "Other columns", ParamKind.COLUMNS),
           Param("separator", "Separator", ParamKind.TEXT, required=False, default=" "),
       ),
       example=Example(
           rows=({"first": "Ada", "last": "Lovelace"}, {"first": "Alan", "last": None}),
           params={"columns": ["last"], "separator": " "},
           column="first",
           expect=("Ada Lovelace", "Alan"),
       ))
