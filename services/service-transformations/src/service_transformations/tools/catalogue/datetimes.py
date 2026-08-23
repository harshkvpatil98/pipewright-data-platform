"""Date and time tools.

Every extraction here reads a *moment*, so the tools accept temporal columns and
text that parses as one -- which is most date columns in most files, because CSV
has no dates.
"""

from __future__ import annotations

from service_transformations.tools.builders import call, integer, text as lit
from service_transformations.tools.declare import Accepts, Example, Param, ParamKind, custom, simple

CATEGORY = "Date & time"
WHEN = Accepts.TEMPORAL

PERIODS = ("year", "quarter", "month", "week", "day", "hour", "minute", "second")


def _ex(rows, expect, params=None, column="when"):
    return Example(
        rows=tuple({"when": row} for row in rows),
        expect=tuple(expect),
        params=params or {},
        column=column,
    )


# ------------------------------------------------------------------- extract

for _name, _title, _function, _synonyms, _expect in (
    ("year", "Year", "year", ("yyyy",), 2026),
    ("quarter", "Quarter", "quarter", ("q",), 3),
    ("month", "Month number", "month", ("mm",), 8),
    ("week", "ISO week", "week", ("week number",), 34),
    ("day", "Day of month", "day", ("dd",), 23),
    ("day_of_week", "Day of week", "day_of_week", ("weekday",), 7),
    ("day_of_year", "Day of year", "day_of_year", ("ordinal day", "julian"), 235),
    ("hour", "Hour", "hour", (), 14),
    ("minute", "Minute", "minute", (), 30),
    ("second", "Second", "second", (), 0),
):
    _detail = " Monday is 1, Sunday is 7." if _name == "day_of_week" else ""
    simple(f"date.{_name}", _title, CATEGORY, f"Extract the {_title.lower()}.{_detail}", _function,
           accepts=WHEN, synonyms=_synonyms,
           example=_ex(["2026-08-23T14:30:00"], [_expect]))

simple("date.month_name", "Month name", CATEGORY, "The month's name.", "month_name",
       accepts=WHEN, example=_ex(["2026-08-23"], ["August"]))

simple("date.day_name", "Day name", CATEGORY, "The weekday's name.", "day_name",
       accepts=WHEN, example=_ex(["2026-08-23"], ["Sunday"]))

# ------------------------------------------------------------------ periods

simple("date.start_of_period", "Start of period", CATEGORY,
       "The first instant of the containing period.", "start_of_period",
       accepts=WHEN, synonyms=("truncate", "floor date", "month start", "beginning of"),
       params=(Param("period", "Period", ParamKind.SELECT, default="month", options=PERIODS),),
       extra_args=lambda p: (lit(p["period"]),),
       example=_ex(["2026-08-23"], ["2026-08-01 00:00:00"], {"period": "month"}))

simple("date.end_of_period", "End of period", CATEGORY,
       "The last instant of the containing period -- not the start of the next one.",
       "end_of_period",
       accepts=WHEN, synonyms=("month end", "ceiling date", "last day"),
       params=(Param("period", "Period", ParamKind.SELECT, default="month", options=PERIODS),),
       extra_args=lambda p: (lit(p["period"]),),
       example=_ex(["2026-08-23"], ["2026-08-31 23:59:59.999999"], {"period": "month"}))

# ------------------------------------------------------------------ shifting

simple("date.add_days", "Add days", CATEGORY, "Shift by a number of days.", "add_days",
       accepts=WHEN, synonyms=("plus days", "offset", "subtract days"),
       params=(Param("days", "Days (negative to subtract)", ParamKind.INTEGER, default=1,
                     minimum=-500000, maximum=500000),),
       extra_args=lambda p: (integer(int(p["days"])),),
       example=_ex(["2026-08-23"], ["2026-08-30 00:00:00"], {"days": 7}))

simple("date.add_months", "Add months", CATEGORY,
       "Shift by whole months, clamping to the end of a short month.", "add_months",
       accepts=WHEN, synonyms=("plus months",),
       params=(Param("months", "Months (negative to subtract)", ParamKind.INTEGER, default=1,
                     minimum=-12000, maximum=12000),),
       extra_args=lambda p: (integer(int(p["months"])),),
       example=_ex(["2026-01-31"], ["2026-02-28 00:00:00"], {"months": 1}))

simple("date.add_years", "Add years", CATEGORY, "Shift by whole years.", "add_years",
       accepts=WHEN,
       params=(Param("years", "Years (negative to subtract)", ParamKind.INTEGER, default=1,
                     minimum=-1000, maximum=1000),),
       extra_args=lambda p: (integer(int(p["years"])),),
       example=_ex(["2026-08-23"], ["2027-08-23 00:00:00"], {"years": 1}))

simple("date.add_business_days", "Add business days", CATEGORY,
       "Shift by working days, skipping Saturdays and Sundays.", "add_business_days",
       accepts=WHEN, synonyms=("working days", "weekdays"),
       params=(Param("days", "Business days", ParamKind.INTEGER, default=1,
                     minimum=-10000, maximum=10000),),
       extra_args=lambda p: (integer(int(p["days"])),),
       example=_ex(["2026-08-21"], ["2026-08-24"], {"days": 1}))

# --------------------------------------------------------------- differences


def _between(function, other_key="other"):
    def apply(column, params):
        from service_transformations.ir.expressions import Column

        return call(function, column, Column(params[other_key]))

    return apply


for _name, _title, _function, _synonyms in (
    ("days_between", "Days until", "days_between", ("date difference", "day diff")),
    ("months_between", "Months until", "months_between", ()),
    ("years_between", "Years until", "years_between", ()),
    ("seconds_between", "Seconds until", "seconds_between", ("duration",)),
    ("business_days_between", "Business days until", "business_days_between", ("working days between",)),
):
    custom(f"date.{_name}", _title, CATEGORY,
           f"{_title} another date column, counted from this one.",
           _between(_function),
           accepts=WHEN, synonyms=_synonyms,
           params=(Param("other", "Other date column", ParamKind.COLUMN),),
           example=Example(
               rows=({"when": "2026-08-01", "other": "2026-08-08"},),
               params={"other": "other"},
               column="when",
               expect=({"days_between": 7, "months_between": 0, "years_between": 0,
                        "seconds_between": 604800.0, "business_days_between": 5}[_function],),
           ))

simple("date.age_years", "Age in years", CATEGORY,
       "Whole years between this date and today.", "age_years",
       accepts=WHEN, synonyms=("age", "years old", "tenure"),
       example=Example(rows=({"when": "2000-01-01"},), column="when", expect=(),
                       note="The answer depends on today's date, so no fixed value is shown; "
                            "a documented one would be wrong from tomorrow."))

# ------------------------------------------------------------------ calendars

simple("date.is_weekend", "Is a weekend", CATEGORY,
       "True on Saturday and Sunday.", "is_weekend",
       accepts=WHEN, synonyms=("saturday", "sunday", "weekend"),
       example=_ex(["2026-08-22", "2026-08-24"], [True, False]))

simple("date.fiscal_year", "Fiscal year", CATEGORY,
       "The financial year, named for the calendar year it ends in.", "fiscal_year",
       accepts=WHEN, synonyms=("financial year", "fy"),
       params=(Param("start_month", "Fiscal year starts in month", ParamKind.INTEGER,
                     default=4, minimum=1, maximum=12),),
       extra_args=lambda p: (integer(int(p["start_month"])),),
       example=_ex(["2026-08-23", "2026-02-01"], [2027, 2026], {"start_month": 4}))

simple("date.fiscal_quarter", "Fiscal quarter", CATEGORY,
       "Which quarter of the financial year.", "fiscal_quarter",
       accepts=WHEN, synonyms=("financial quarter", "fq"),
       params=(Param("start_month", "Fiscal year starts in month", ParamKind.INTEGER,
                     default=4, minimum=1, maximum=12),),
       extra_args=lambda p: (integer(int(p["start_month"])),),
       example=_ex(["2026-08-23"], [2], {"start_month": 4}))

# ------------------------------------------------------- formats and offsets

simple("date.format", "Format as text", CATEGORY,
       "Render as text with a chosen pattern.", "format_date",
       accepts=WHEN, synonyms=("strftime", "date format", "display date"),
       params=(Param("pattern", "Pattern", ParamKind.TEXT, default="%Y-%m-%d",
                     help="strftime pattern: %Y year, %m month, %d day, %H hour."),),
       extra_args=lambda p: (lit(p["pattern"]),),
       example=_ex(["2026-08-23"], ["23/08/2026"], {"pattern": "%d/%m/%Y"}))

simple("date.parse", "Parse a date", CATEGORY,
       "Read text as a date. Values that cannot be read become null.", "to_date",
       accepts=Accepts.TEXTUAL, synonyms=("to date", "text to date", "convert date"),
       example=Example(rows=({"when": "23 August 2026"}, {"when": "not a date"}),
                       column="when", expect=("2026-08-23", None)))

simple("date.to_timestamp", "Parse a timestamp", CATEGORY,
       "Read text as a date and time.", "to_timestamp",
       accepts=Accepts.TEXTUAL, synonyms=("to datetime", "parse datetime"),
       example=Example(rows=({"when": "2026-08-23 14:30"},), column="when",
                       expect=("2026-08-23 14:30:00",)))

simple("date.to_timezone", "Convert time zone", CATEGORY,
       "Move a moment to another time zone. Naive values are read as UTC.",
       "to_timezone",
       accepts=WHEN, synonyms=("timezone", "tz", "localise"),
       params=(Param("zone", "Time zone", ParamKind.TEXT, default="UTC",
                     placeholder="Europe/London"),),
       extra_args=lambda p: (lit(p["zone"]),),
       example=_ex(["2026-08-23T12:00:00"], ["2026-08-23 13:00:00+01:00"],
                   {"zone": "Europe/London"}))

simple("date.to_epoch", "To epoch seconds", CATEGORY,
       "Seconds since 1970-01-01 UTC.", "epoch_seconds",
       accepts=WHEN, synonyms=("unix time", "timestamp number"),
       example=_ex(["2026-08-23T00:00:00"], [1787443200]))

simple("date.from_epoch", "From epoch", CATEGORY,
       "Read a number of seconds or milliseconds since 1970 as a moment.", "from_epoch",
       accepts=Accepts.NUMERIC, synonyms=("unix to date", "epoch to date"),
       params=(Param("unit", "Unit", ParamKind.SELECT, default="seconds",
                     options=("seconds", "milliseconds")),),
       extra_args=lambda p: (lit(p["unit"]),),
       example=_ex([1787443200], ["2026-08-23 00:00:00"], {"unit": "seconds"}))
