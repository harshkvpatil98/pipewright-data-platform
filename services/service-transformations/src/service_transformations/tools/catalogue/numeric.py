"""Numeric tools."""

from __future__ import annotations

from service_transformations.ir.expressions import Case
from service_transformations.tools.builders import call, integer, null_safe, number
from service_transformations.tools.declare import Accepts, Example, Param, ParamKind, custom, simple

CATEGORY = "Numeric"
NUM = Accepts.NUMERIC


def _ex(rows, expect, params=None):
    return Example(
        rows=tuple({"value": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column="value",
    )


simple("numeric.round", "Round", CATEGORY, "Round to a number of decimal places.", "round",
       accepts=NUM, synonyms=("decimal places", "2dp"),
       params=(Param("digits", "Decimal places", ParamKind.INTEGER, default=0, minimum=-10, maximum=12),),
       extra_args=lambda p: (integer(int(p["digits"])),),
       example=_ex([1.2345], [1.23], {"digits": 2}))

simple("numeric.round_up", "Round up", CATEGORY, "Round towards positive infinity.", "ceil",
       accepts=NUM, synonyms=("ceiling", "ceil"),
       example=_ex([1.2, -1.2], [2, -1]))

simple("numeric.round_down", "Round down", CATEGORY, "Round towards negative infinity.", "floor",
       accepts=NUM, synonyms=("floor",),
       example=_ex([1.8, -1.2], [1, -2]))

simple("numeric.truncate", "Truncate", CATEGORY,
       "Drop the fractional part, towards zero.", "trunc",
       accepts=NUM, synonyms=("integer part", "chop"),
       example=_ex([1.8, -1.8], [1, -1]))

simple("numeric.round_to_multiple", "Round to a multiple", CATEGORY,
       "Round to the nearest multiple of a step.", "round_to",
       accepts=NUM, synonyms=("nearest", "step", "snap"),
       params=(Param("multiple", "Multiple of", ParamKind.NUMBER, default=1),),
       extra_args=lambda p: (number(p["multiple"]),),
       example=_ex([17], [15], {"multiple": 5}))

simple("numeric.ceil_to_multiple", "Round a multiple up", CATEGORY,
       "Round up to the next multiple of a step.", "ceil_to",
       accepts=NUM,
       params=(Param("multiple", "Multiple of", ParamKind.NUMBER, default=1),),
       extra_args=lambda p: (number(p["multiple"]),),
       example=_ex([16], [20], {"multiple": 5}))

simple("numeric.floor_to_multiple", "Round a multiple down", CATEGORY,
       "Round down to the previous multiple of a step.", "floor_to",
       accepts=NUM,
       params=(Param("multiple", "Multiple of", ParamKind.NUMBER, default=1),),
       extra_args=lambda p: (number(p["multiple"]),),
       example=_ex([19], [15], {"multiple": 5}))

simple("numeric.absolute", "Absolute value", CATEGORY, "Drop the sign.", "abs",
       accepts=NUM, synonyms=("abs", "magnitude", "positive"),
       example=_ex([-3, 3], [3, 3]))

simple("numeric.sign", "Sign", CATEGORY, "-1, 0 or 1.", "sign", accepts=NUM,
       example=_ex([-4, 0, 4], [-1, 0, 1]))

simple("numeric.reciprocal", "Reciprocal", CATEGORY,
       "One divided by the value. Null where the value is zero.", "reciprocal",
       accepts=NUM, synonyms=("inverse", "1/x"),
       example=_ex([4, 0], [0.25, None]))

simple("numeric.square_root", "Square root", CATEGORY, "The square root.", "sqrt",
       accepts=NUM, synonyms=("sqrt", "root"),
       example=_ex([9], [3.0]))

simple("numeric.power", "Raise to a power", CATEGORY, "Raise to an exponent.", "power",
       accepts=NUM, synonyms=("exponent", "squared", "cubed"),
       params=(Param("exponent", "Exponent", ParamKind.NUMBER, default=2),),
       extra_args=lambda p: (number(p["exponent"]),),
       example=_ex([3], [9.0], {"exponent": 2}))

simple("numeric.log", "Logarithm", CATEGORY,
       "Logarithm to a chosen base. Null for values at or below zero.", "log",
       accepts=NUM, synonyms=("log10", "log2", "logarithm"),
       params=(Param("base", "Base", ParamKind.NUMBER, default=10, minimum=0),),
       extra_args=lambda p: (number(p["base"]),),
       example=_ex([100, 0], [2.0, None], {"base": 10}))

simple("numeric.ln", "Natural logarithm", CATEGORY, "Logarithm to base e.", "ln",
       accepts=NUM, example=_ex([1], [0.0]))

simple("numeric.exponential", "Exponential", CATEGORY, "e raised to the value.", "exp",
       accepts=NUM, synonyms=("e^x",), example=_ex([0], [1.0]))

simple("numeric.modulo", "Remainder", CATEGORY, "The remainder after dividing.", "mod",
       accepts=NUM, synonyms=("mod", "modulus", "remainder"),
       params=(Param("divisor", "Divide by", ParamKind.NUMBER, default=2),),
       extra_args=lambda p: (number(p["divisor"]),),
       example=_ex([7], [1], {"divisor": 3}))

simple("numeric.integer_divide", "Integer divide", CATEGORY,
       "Divide and drop the remainder.", "int_div",
       accepts=NUM, synonyms=("floor divide", "quotient"),
       params=(Param("divisor", "Divide by", ParamKind.NUMBER, default=2),),
       extra_args=lambda p: (number(p["divisor"]),),
       example=_ex([7], [3], {"divisor": 2}))

simple("numeric.clamp", "Clamp to a range", CATEGORY,
       "Pull values below the floor up and values above the ceiling down.", "clamp",
       accepts=NUM, synonyms=("limit", "cap", "bound", "winsorise"),
       params=(
           Param("minimum", "Minimum", ParamKind.NUMBER, default=0),
           Param("maximum", "Maximum", ParamKind.NUMBER, default=100),
       ),
       extra_args=lambda p: (number(p["minimum"]), number(p["maximum"])),
       example=_ex([-5, 50, 500], [0, 50, 100], {"minimum": 0, "maximum": 100}))

simple("numeric.is_even", "Is even", CATEGORY, "True for even whole numbers.", "is_even",
       accepts=NUM, example=_ex([2, 3], [True, False]))

simple("numeric.is_odd", "Is odd", CATEGORY, "True for odd whole numbers.", "is_odd",
       accepts=NUM, example=_ex([2, 3], [False, True]))


def _rescale(column, params):
    """Map a known range onto a new one. Rescaling a *column* needs its
    min and max, which is an aggregate; this takes them as parameters so the
    tool stays a pure per-row expression and therefore pushes down."""
    low, high = number(params["from_minimum"]), number(params["from_maximum"])
    target_low, target_high = number(params["to_minimum"]), number(params["to_maximum"])
    span = call("sub", high, low)
    scaled = call("div", call("sub", column, low), span)
    return call("add", target_low, call("mul", scaled, call("sub", target_high, target_low)))


custom("numeric.rescale", "Rescale to a range", CATEGORY,
       "Map a known input range onto a new output range.", _rescale,
       accepts=NUM, synonyms=("normalise", "min max", "scale", "0-1"),
       params=(
           Param("from_minimum", "Input minimum", ParamKind.NUMBER, default=0),
           Param("from_maximum", "Input maximum", ParamKind.NUMBER, default=100),
           Param("to_minimum", "Output minimum", ParamKind.NUMBER, default=0),
           Param("to_maximum", "Output maximum", ParamKind.NUMBER, default=1),
       ),
       example=_ex([50], [0.5],
                   {"from_minimum": 0, "from_maximum": 100, "to_minimum": 0, "to_maximum": 1}))


def _percent_of(column, params):
    return call("mul", call("div", column, number(params["total"])), number(100))


custom("numeric.percent_of", "Percent of a total", CATEGORY,
       "Express as a percentage of a known total.", _percent_of,
       accepts=NUM, synonyms=("percentage", "share", "%"),
       params=(Param("total", "Total", ParamKind.NUMBER, default=100),),
       example=_ex([25], [25.0], {"total": 100}))


def _bin(column, params):
    """Label a value by which fixed-width bucket it falls in.

    Bucket edges are parameters rather than derived from the data, because a
    bucketing that changes when a row arrives is not a bucketing anybody can
    compare across runs.
    """
    from service_transformations.tools.builders import text as lit

    low = float(params["minimum"])
    width = float(params["width"])
    if width <= 0:
        from shared_python.errors import BadRequestError

        raise BadRequestError("Bucket width has to be greater than zero.")
    count = int(params["buckets"])
    branches = []
    for index in range(count):
        edge = low + width * (index + 1)
        label = f"{low + width * index:g} to {edge:g}"
        branches.append((call("lt", column, number(edge)), lit(label)))
    # A row with no value has no bucket; without this guard it lands in the
    # default and reads as the top bucket.
    return null_safe(column, Case(branches=tuple(branches), default=lit(f"{low + width * count:g}+")))


custom("numeric.bin", "Group into buckets", CATEGORY,
       "Label each value by which fixed-width bucket it falls in.", _bin,
       accepts=NUM, synonyms=("bucket", "histogram", "bands", "ranges"),
       params=(
           Param("minimum", "First bucket starts at", ParamKind.NUMBER, default=0),
           Param("width", "Bucket width", ParamKind.NUMBER, default=10),
           Param("buckets", "How many buckets", ParamKind.INTEGER, default=5, minimum=1, maximum=200),
       ),
       example=_ex([5, 15, 95], ["0 to 10", "10 to 20", "50+"],
                   {"minimum": 0, "width": 10, "buckets": 5}))
