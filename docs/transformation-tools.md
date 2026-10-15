# Transformation tools

379 tools across 22 categories. Every one compiles to the
relational IR, so every one gets type inference, column lineage and
pushdown without a second implementation.

Generated from the tool registry. Every example below is executed by the
test suite, so this file cannot describe behaviour the code does not have.

## Contents

- [Date & time](#date--time) (42)
- [Validation](#validation) (24)
- [Cleansing](#cleansing) (21)
- [Columns](#columns) (13)
- [Join & combine](#join--combine) (6)
- [Type & conversion](#type--conversion) (14)
- [Encoding & privacy](#encoding--privacy) (17)
- [Code & escape hatches](#code--escape-hatches) (6)
- [Geospatial](#geospatial) (17)
- [Enrichment & lookup](#enrichment--lookup) (6)
- [Deduplication & matching](#deduplication--matching) (8)
- [Metadata & documentation](#metadata--documentation) (7)
- [Machine learning](#machine-learning) (18)
- [Nested data](#nested-data) (6)
- [Missing data](#missing-data) (11)
- [Numeric](#numeric) (30)
- [Rows](#rows) (17)
- [Sampling & splitting](#sampling--splitting) (10)
- [Statistics](#statistics) (27)
- [Reshape](#reshape) (3)
- [Text](#text) (45)
- [Window & analytic](#window--analytic) (31)


## Date & time

### Add time

`date.add_interval`

Add an amount of seconds, minutes, hours, days, weeks, months, quarters or years (a month added to 31 January is 28 or 29 February).

Also known as: _add interval_, _plus hours_, _add hours_, _date add_, _shift time_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | number | yes | `1` |
| Of | `seconds` / `minutes` / `hours` / `days` / `weeks` / `months` / `quarters` / `years` | yes | `days` |

| `when` | `when` |
|---|---|
| `2026-01-31 10:00` | `2026-02-28 10:00:00` |
| _(empty)_ | _(empty)_ |

### Subtract time

`date.subtract_interval`

Take away an amount of seconds, minutes, hours, days, weeks, months, quarters or years.

Also known as: _subtract interval_, _minus days_, _go back_, _date sub_, _earlier by_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | number | yes | `1` |
| Of | `seconds` / `minutes` / `hours` / `days` / `weeks` / `months` / `quarters` / `years` | yes | `days` |

| `when` | `when` |
|---|---|
| `2026-03-01 00:30` | `2026-03-01 00:00:00` |

### Read as a time zone

`date.from_timezone`

Say which time zone times without one were written in, so they become exact moments (a time that the clocks skipped, or passed twice, is empty).

Also known as: _from timezone_, _localise_, _set time zone_, _assume time zone_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Time zone | text | yes | `Europe/London` |

| `when` | `when` |
|---|---|
| `2026-07-01 09:00` | `2026-07-01 09:00:00+01:00` |

### Convert to UTC

`date.to_utc`

Write moments in UTC. Times without a zone are read in the zone given (or as UTC already when none is).

Also known as: _to utc_, _utc_, _gmt_, _zulu_, _normalise time zone_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Times without a zone are in | text | no | none |

| `when` | `when` |
|---|---|
| `2026-07-01 09:00` | `2026-07-01 08:00:00+00:00` |

### Is a public holiday

`date.is_holiday`

True on the public holidays of a country (and region), from each country's published rules.

Also known as: _is holiday_, _holiday_, _bank holiday_, _public holiday_, _holiday calendar_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Country | text | yes | `GB` |
| Region | text | no | none |
| | For countries whose holidays differ by region: ENG, SCT, WLS, NIR in GB; a state in US or DE. | | |

| `when` | `when` |
|---|---|
| `2026-12-25` | `True` |
| `2026-12-23` | `False` |

### Name of the public holiday

`date.holiday_name`

The name of the public holiday on that day, or empty.

Also known as: _holiday name_, _which holiday_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Country | text | yes | `GB` |
| Region | text | no | none |
| | For countries whose holidays differ by region: ENG, SCT, WLS, NIR in GB; a state in US or DE. | | |

| `when` | `when` |
|---|---|
| `2026-12-25` | `Christmas Day` |
| `2026-12-23` | _(empty)_ |

### Fiscal month

`date.fiscal_period`

Which month of the financial year (1 to 12), for a year starting in the month given.

Also known as: _fiscal period_, _financial month_, _fiscal month_, _period number_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Fiscal year starts in month | integer | yes | `4` |

| `when` | `when` |
|---|---|
| `2026-04-15` | `1` |
| `2026-03-31` | `12` |

### Make a calendar of dates

`date.spine`

Replace the rows with one row for every day (or week, month, quarter, year) from this column's earliest date to its latest, or between dates you give: a calendar to join other data to, with no day missing.

Also known as: _date spine_, _calendar table_, _all dates_, _date range_, _generate dates_, _date dimension_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Column name | text | yes | `date` |
| One row every | `day` / `week` / `month` / `quarter` / `year` | yes | `day` |
| From | text | no | none |
| To | text | no | none |

| `when` | `day` |
|---|---|
| `2026-01-03` | `2026-01-01` |
| `2026-01-01` | `2026-01-02` |

### Add rows for missing dates

`date.fill_missing`

Add a row for each date a series skipped, between its first and last date (within each group), with the other columns empty; optionally a column saying which rows were added.

Also known as: _fill missing dates_, _complete dates_, _gap fill dates_, _missing days_, _densify_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| One row every | `day` / `week` / `month` / `quarter` / `year` | yes | `day` |
| Within each | columns | no | none |
| Mark added rows in a column | text | no | none |

| `when` | `added` |
|---|---|
| `2026-01-01` | `False` |
| `2026-01-03` | `True` |

### Year

`date.year`

Extract the year.

Also known as: _yyyy_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `2026` |

### Quarter

`date.quarter`

Extract the quarter.

Also known as: _q_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `3` |

### Month number

`date.month`

Extract the month number.

Also known as: _mm_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `8` |

### ISO week

`date.week`

Extract the iso week.

Also known as: _week number_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `34` |

### Day of month

`date.day`

Extract the day of month.

Also known as: _dd_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `23` |

### Day of week

`date.day_of_week`

Extract the day of week. Monday is 1, Sunday is 7.

Also known as: _weekday_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `7` |

### Day of year

`date.day_of_year`

Extract the day of year.

Also known as: _ordinal day_, _julian_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `235` |

### Hour

`date.hour`

Extract the hour.

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `14` |

### Minute

`date.minute`

Extract the minute.

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `30` |

### Second

`date.second`

Extract the second.

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T14:30:00` | `0` |

### Month name

`date.month_name`

The month's name.

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23` | `August` |

### Day name

`date.day_name`

The weekday's name.

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23` | `Sunday` |

### Start of period

`date.start_of_period`

The first instant of the containing period.

Also known as: _truncate_, _floor date_, _month start_, _beginning of_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Period | `year` / `quarter` / `month` / `week` / `day` / `hour` / `minute` / `second` | yes | `month` |

| `when` | `when` |
|---|---|
| `2026-08-23` | `2026-08-01 00:00:00` |

### End of period

`date.end_of_period`

The last instant of the containing period -- not the start of the next one.

Also known as: _month end_, _ceiling date_, _last day_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Period | `year` / `quarter` / `month` / `week` / `day` / `hour` / `minute` / `second` | yes | `month` |

| `when` | `when` |
|---|---|
| `2026-08-23` | `2026-08-31 23:59:59.999999` |

### Add days

`date.add_days`

Shift by a number of days.

Also known as: _plus days_, _offset_, _subtract days_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Days (negative to subtract) | integer | yes | `1` |

| `when` | `when` |
|---|---|
| `2026-08-23` | `2026-08-30 00:00:00` |

### Add months

`date.add_months`

Shift by whole months, clamping to the end of a short month.

Also known as: _plus months_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Months (negative to subtract) | integer | yes | `1` |

| `when` | `when` |
|---|---|
| `2026-01-31` | `2026-02-28 00:00:00` |

### Add years

`date.add_years`

Shift by whole years.

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Years (negative to subtract) | integer | yes | `1` |

| `when` | `when` |
|---|---|
| `2026-08-23` | `2027-08-23 00:00:00` |

### Add business days

`date.add_business_days`

Shift by working days, skipping Saturdays and Sundays.

Also known as: _working days_, _weekdays_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Business days | integer | yes | `1` |

| `when` | `when` |
|---|---|
| `2026-08-21` | `2026-08-24` |

### Days until

`date.days_between`

Days until another date column, counted from this one.

Also known as: _date difference_, _day diff_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | none |

| `when` | `when` |
|---|---|
| `2026-08-01` | `7` |

### Months until

`date.months_between`

Months until another date column, counted from this one.

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | none |

| `when` | `when` |
|---|---|
| `2026-08-01` | `0` |

### Years until

`date.years_between`

Years until another date column, counted from this one.

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | none |

| `when` | `when` |
|---|---|
| `2026-08-01` | `0` |

### Seconds until

`date.seconds_between`

Seconds until another date column, counted from this one.

Also known as: _duration_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | none |

| `when` | `when` |
|---|---|
| `2026-08-01` | `604800.0` |

### Business days until

`date.business_days_between`

Business days until another date column, counted from this one.

Also known as: _working days between_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | none |

| `when` | `when` |
|---|---|
| `2026-08-01` | `5` |

### Age in years

`date.age_years`

Whole years between this date and today.

Also known as: _age_, _years old_, _tenure_

Offered on **temporal** columns.

_The answer depends on today's date, so no fixed value is shown; a documented one would be wrong from tomorrow._

### Is a weekend

`date.is_weekend`

True on Saturday and Sunday.

Also known as: _saturday_, _sunday_, _weekend_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-22` | `True` |
| `2026-08-24` | `False` |

### Fiscal year

`date.fiscal_year`

The financial year, named for the calendar year it ends in.

Also known as: _financial year_, _fy_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Fiscal year starts in month | integer | yes | `4` |

| `when` | `when` |
|---|---|
| `2026-08-23` | `2027` |
| `2026-02-01` | `2026` |

### Fiscal quarter

`date.fiscal_quarter`

Which quarter of the financial year.

Also known as: _financial quarter_, _fq_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Fiscal year starts in month | integer | yes | `4` |

| `when` | `when` |
|---|---|
| `2026-08-23` | `2` |

### Format as text

`date.format`

Render as text with a chosen pattern.

Also known as: _strftime_, _date format_, _display date_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | `%Y-%m-%d` |
| | strftime pattern: %Y year, %m month, %d day, %H hour. | | |

| `when` | `when` |
|---|---|
| `2026-08-23` | `23/08/2026` |

### Parse a date

`date.parse`

Read text as a date. Values that cannot be read become null.

Also known as: _to date_, _text to date_, _convert date_

Offered on **textual** columns.

| `when` | `when` |
|---|---|
| `23 August 2026` | `2026-08-23` |
| `not a date` | _(empty)_ |

### Parse a timestamp

`date.to_timestamp`

Read text as a date and time.

Also known as: _to datetime_, _parse datetime_

Offered on **textual** columns.

| `when` | `when` |
|---|---|
| `2026-08-23 14:30` | `2026-08-23 14:30:00` |

### Convert time zone

`date.to_timezone`

Move a moment to another time zone. Naive values are read as UTC.

Also known as: _timezone_, _tz_, _localise_

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Time zone | text | yes | `UTC` |

| `when` | `when` |
|---|---|
| `2026-08-23T12:00:00` | `2026-08-23 13:00:00+01:00` |

### To epoch seconds

`date.to_epoch`

Seconds since 1970-01-01 UTC.

Also known as: _unix time_, _timestamp number_

Offered on **temporal** columns.

| `when` | `when` |
|---|---|
| `2026-08-23T00:00:00` | `1787443200` |

### From epoch

`date.from_epoch`

Read a number of seconds or milliseconds since 1970 as a moment.

Also known as: _unix to date_, _epoch to date_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Unit | `seconds` / `milliseconds` | yes | `seconds` |

| `when` | `when` |
|---|---|
| `1787443200` | `2026-08-23 00:00:00` |


## Validation

### Check nothing is empty

`assert.not_empty`

Every row has a value in these columns.

Also known as: _assert not null_, _required_, _not empty_, _mandatory_, _no blanks_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | yes | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `email` | `bad` |
|---|---|
| `a@x.com` | `False` |
| ` ` | `True` |

_With on_failure set to mark the rows; the second has no email._

### Check values are from a list

`assert.in_set`

Every value of the column is one of these (empty values pass; check them with Check nothing is empty).

Also known as: _assert in set_, _allowed values_, _accepted values_, _enum check_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Allowed values | list | yes | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `colour` | `bad` |
|---|---|
| `red` | `False` |
| `purple` | `True` |
| _(empty)_ | `False` |

_With on_failure set to mark the rows; purple is not allowed._

### Check numbers are in a range

`assert.in_range`

Every value is a number at least the lowest and at most the highest given.

Also known as: _assert range_, _between_, _bounds_, _min max check_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Lowest | number | no | none |
| Highest | number | no | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `price` | `bad` |
|---|---|
| `3` | `False` |
| `-1` | `True` |

_With on_failure set to mark the rows; a negative price._

### Check values match a pattern

`assert.matches`

Every value matches a regular expression in full.

Also known as: _assert regex_, _pattern check_, _format check_, _matches_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Pattern | text | yes | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `code` | `bad` |
|---|---|
| `AB12` | `False` |
| `A1` | `True` |

_With on_failure set to mark the rows; a code too short._

### Check values are of a type

`assert.type`

Every value reads as a number, a whole number, a date or true or false.

Also known as: _assert type_, _type check_, _is numeric_, _data type check_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Should be | `a number` / `a whole number` / `a date` / `true or false` | yes | `a number` |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `qty` | `bad` |
|---|---|
| `3` | `False` |
| `seven` | `True` |

_With on_failure set to mark the rows; seven is a word._

### Check a formula holds

`assert.formula`

Every row satisfies a formula that is true or false, such as [shipped] >= [ordered]; a row where it is empty fails.

Also known as: _custom assertion_, _assert formula_, _rule_, _business rule_, _invariant_

| Setting | Type | Required | Default |
|---|---|---|---|
| Formula | text | yes | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `ordered` | `bad` |
|---|---|
| `3` | `False` |
| `5` | `True` |

_With on_failure set to mark the rows; shipped before it was ordered._

### Check every key exists elsewhere

`assert.found_in`

Every value of the column appears in another dataset's column (each order's customer is a known customer): referential integrity.

Also known as: _referential integrity_, _foreign key check_, _assert exists_, _orphan rows_, _lookup check_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Other dataset | dataset | yes | none |
| Its column | dataset_column | yes | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `customer` | `bad` |
|---|---|
| `1` | `False` |
| `9` | `True` |

The other dataset in this example:

| `id` |
|---|
| `1` |
| `2` |

_With on_failure set to mark the rows; customer 9 is unknown._

### Check values are unique

`assert.unique`

No two rows have the same values in these columns (a key).

Also known as: _assert unique_, _primary key_, _unique key_, _no duplicate keys_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | yes | none |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `id` | `bad` |
|---|---|
| `1` | `False` |
| `2` | `True` |
| `2` | `True` |

_With on_failure set to mark the rows; two rows share id 2._

### Check no row is repeated

`assert.no_duplicates`

No two rows are the same in every column.

Also known as: _assert no duplicates_, _duplicate rows_, _distinct rows check_

| Setting | Type | Required | Default |
|---|---|---|---|
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `a` | `bad` |
|---|---|
| `1` | `True` |
| `2` | `False` |
| `1` | `True` |

_With on_failure set to mark the rows; the last row repeats the first._

### Check the number of rows

`assert.row_count`

There are at least, or at most, this many rows (an import that brought nothing; a join that multiplied).

Also known as: _assert row count_, _row count_, _volume check_, _not empty dataset_

| Setting | Type | Required | Default |
|---|---|---|---|
| At least | integer | no | none |
| At most | integer | no | none |
| When it does not hold | `stop the run` / `warn` | no | `stop the run` |

| `a` | `a` |
|---|---|
| `1` | `1` |
| `2` | `2` |

_Passes: 2 rows is between 1 and 10._

### Check values only go up

`assert.increasing`

Each value of the column is at least the one before it (or, strictly, more): a sequence, a running total, timestamps in order.

Also known as: _assert monotonic_, _increasing_, _in order_, _sorted check_, _sequence check_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Strictly | boolean | no | `False` |
| When it does not hold | `stop the run` / `warn` / `mark the rows` | no | `stop the run` |
| | Mark adds a true or false column saying which rows fail, for checks about single rows. | | |
| Marking column | text | no | none |

| `t` | `bad` |
|---|---|
| `1` | `False` |
| `2` | `False` |
| `1` | `True` |

_With on_failure set to mark the rows; the third goes back._

### Check a total

`assert.sum_equals`

The column adds up to this, within a tolerance (shares add to 100, debits equal credits).

Also known as: _assert sum_, _total check_, _reconcile_, _balance check_, _control total_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Should add up to | number | yes | none |
| Within | number | no | `0` |
| When it does not hold | `stop the run` / `warn` | no | `stop the run` |

| `share` | `share` |
|---|---|
| `60` | `60` |
| `40` | `40` |

_Passes: 60 and 40 add to 100._

### Check the data is recent

`assert.fresh`

The newest date or time in the column is no older than this many hours when the recipe runs (a replay checks against the moment of the run it repeats).

Also known as: _assert freshness_, _freshness_, _stale data_, _latest date check_, _sla_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| At most this many hours old | number | yes | `24` |
| When it does not hold | `stop the run` / `warn` | no | `stop the run` |

| `at` | `at` |
|---|---|
| `2200-01-01` | `2200-01-01` |

_Passes: the newest value is not old._

### Check the columns

`assert.schema`

The data has these columns (each optionally with a type, as name:number, name:date, name:text, name:true or false), and, if asked, no others.

Also known as: _assert schema_, _schema check_, _expected columns_, _column check_, _schema snapshot_

| Setting | Type | Required | Default |
|---|---|---|---|
| Expected columns | list | yes | none |
| Other columns are fine | boolean | no | `True` |
| When it does not hold | `stop the run` / `warn` | no | `stop the run` |

| `id` | `id` |
|---|---|
| `1` | `1` |

_Passes: id is a number and name is there._

### Check values look as they did

`assert.distribution_stable`

The column's values are distributed as in another dataset, such as this recipe's own output from the run before: by the Kolmogorov-Smirnov distance for numbers and the population stability index for categories, below a threshold.

Also known as: _assert distribution_, _drift check_, _distribution stable_, _psi_, _ks test_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Compared with | dataset | yes | none |
| Its column | dataset_column | no | none |
| Largest change allowed | number | no | `0.2` |
| When it does not hold | `stop the run` / `warn` | no | `stop the run` |

| `v` | `v` |
|---|---|
| `1` | `1` |
| `2` | `2` |
| `3` | `3` |

The other dataset in this example:

| `v` |
|---|
| `1` |
| `2` |
| `3` |

_Passes: the same values as the dataset compared with._

### Looks like an email

`check.is_email`

True for text shaped like an email address.

Also known as: _validate email_, _email check_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a@b.com` | `True` |
| `nope` | `False` |

### Looks like a URL

`check.is_url`

True for text shaped like an http or https URL.

Also known as: _validate url_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `https://a.co` | `True` |
| `a.co` | `False` |

### Reads as a date

`check.is_date`

True where the value can be read as a date.

Also known as: _validate date_, _parseable date_

| `value` | `value` |
|---|---|
| `2026-01-01` | `True` |
| `nope` | `False` |

### Reads as a number

`check.is_number`

True where the value can be read as a number.

Also known as: _validate number_, _numeric check_

| `value` | `value` |
|---|---|
| `12` | `True` |
| `abc` | `False` |

### Within a range

`check.in_range`

True where a number falls between two bounds, inclusive.

Also known as: _between_, _bounds_, _range check_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| At least | number | yes | `0` |
| At most | number | yes | `100` |

| `value` | `value` |
|---|---|
| `5` | `True` |
| `500` | `False` |

### Matches a pattern

`check.matches_pattern`

True where a regular expression matches.

Also known as: _regex check_, _format check_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | none |

| `value` | `value` |
|---|---|
| `AB-1` | `True` |
| `x` | `False` |

### Length within bounds

`check.length_between`

True where the text's length falls between two bounds.

Also known as: _length check_, _too long_, _too short_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| At least | integer | yes | `0` |
| At most | integer | yes | `255` |

| `value` | `value` |
|---|---|
| `abc` | `True` |
| `abcdefgh` | `False` |

### One of a list

`check.in_set`

True where the value is one of an allowed list.

Also known as: _allowed values_, _enum_, _whitelist_, _domain_

| Setting | Type | Required | Default |
|---|---|---|---|
| Allowed values | list | yes | none |
| | One per line. | | |

| `value` | `value` |
|---|---|
| `eu` | `True` |
| `mars` | `False` |

### Split on a check column

`check.quarantine`

Keep only the rows that passed a check, or only the ones that failed.

Also known as: _quarantine_, _split failures_, _bad rows_, _reject_

| Setting | Type | Required | Default |
|---|---|---|---|
| Check column | column | yes | none |
| | A true/false column produced by one of the checks above. | | |
| Keep | `passes` / `failures` | yes | `passes` |

| `ok` | `id` |
|---|---|
| `True` | `2` |
| `False` | `3` |


## Cleansing

### Standardise an email

`clean.email`

Trim and lower case. Empty results become null.

Also known as: _normalise email_, _lowercase email_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| ` Ada@Example.COM ` | `ada@example.com` |

### Email domain

`clean.email_domain`

The part after the @, lower case.

Also known as: _domain_, _company from email_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `ada@Example.com` | `example.com` |
| `not-an-email` | _(empty)_ |

### Standardise a phone number

`clean.phone`

Best-effort E.164. Numbers that cannot be made sense of become null.

Also known as: _e164_, _telephone_, _mobile_, _normalise phone_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Assume this country | `US` / `GB` / `CA` / `DE` / `FR` / `ES` / `IT` / `NL` / `AU` / `IN` / `BR` / `JP` | yes | `US` |
| | Used only when the number has no + prefix of its own. | | |

| `value` | `value` |
|---|---|
| `(555) 123-4567` | `+15551234567` |
| `+44 20 7946 0958` | `+442079460958` |
| `12` | _(empty)_ |

### Standardise a URL

`clean.url`

Add a scheme where one is missing.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `example.com/x` | `https://example.com/x` |
| `http://a.co` | `http://a.co` |

### Part of a URL

`clean.url_part`

Pull out the scheme, host, path, query or fragment.

Also known as: _hostname_, _domain from url_, _path_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Part | `scheme` / `host` / `path` / `query` / `fragment` / `port` | yes | `host` |

| `value` | `value` |
|---|---|
| `https://a.example.com/x?y=1` | `a.example.com` |

### Standardise a postal code

`clean.postal_code`

Apply the country's usual spacing and padding.

Also known as: _zip_, _zip code_, _postcode_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Country | `US` / `GB` / `CA` / `DE` / `FR` / `ES` / `IT` / `NL` / `AU` / `IN` / `BR` / `JP` | yes | `US` |

| `value` | `value` |
|---|---|
| `1234` | `01234` |

### Standardise a country

`clean.country`

Map country names and abbreviations to an ISO code. Unrecognised names become null.

Also known as: _iso country_, _country code_, _nationality_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Output | `alpha2` | yes | `alpha2` |

| `value` | `value` |
|---|---|
| `United States` | `US` |
| `u.s.a.` | `US` |
| `Freedonia` | _(empty)_ |

### Split a full name

`clean.name_part`

Take the first, middle or last name. Particles stay with the surname.

Also known as: _first name_, _surname_, _last name_, _split name_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Part | `first` / `middle` / `last` | yes | `first` |

| `value` | `value` |
|---|---|
| `Ada Lovelace` | `Lovelace` |
| `van der Berg, Jan` | `van der Berg` |
| `Jan van der Berg` | `van der Berg` |

### Standardise yes/no

`clean.boolean_tokens`

Read Y/N, yes/no, 1/0, on/off as true and false.

Also known as: _yes no_, _y n_, _true false_

| `value` | `value` |
|---|---|
| `Y` | `True` |
| `off` | `False` |
| `maybe` | _(empty)_ |

### Standardise line endings

`clean.line_endings`

Turn Windows and old-Mac line endings into plain newlines.

Also known as: _crlf_, _newlines_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a\r\nb` | `a\nb` |

### Remove control characters

`clean.control_characters`

Strip the invisible characters that break exports.

Also known as: _non printable_, _invisible_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a\0b` | `ab` |

### Fix mangled characters

`clean.mojibake`

Repair text where UTF-8 was read as Latin-1 -- the Â£ and â€™ problem.

Also known as: _encoding_, _garbled_, _utf8_, _latin1_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `Â£5` | `£5` |

### Trim surrounding quotes

`clean.trim_quotes`

Remove quote marks left by a bad export.

Also known as: _unquote_, _strip quotes_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `"hello"` | `hello` |

### Unescape

`clean.unescape`

Turn backslash escapes back into the characters they stand for.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a\\tb` | `a\tb` |

### Tidy up text

`clean.standardise`

Collapse whitespace and apply a consistent case, in one step.

Also known as: _clean_, _tidy_, _normalise text_, _standardise_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Case | `none` / `lower` / `upper` / `title` | yes | `none` |

| `value` | `value` |
|---|---|
| `  ADA   lovelace ` | `Ada Lovelace` |

### Standardise an address

`clean.address`

Tidy spacing and capitals and write street words one way: in full (Street, Road) or abbreviated (St, Rd), as UK and US addresses use them.

Also known as: _standardise address_, _normalise address_, _clean address_, _address format_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Street words | `expand` / `abbreviate` | no | `expand` |

| `value` | `value` |
|---|---|
| `12  high st.` | `12 High Street` |
| `4 elm AVENUE` | `4 Elm Avenue` |

### Take part of an address

`clean.address_part`

Take the house number, street, unit, city, region, postcode or country from an address written on one line with commas, by UK and US rules (a UK postcode, a US state and ZIP code). A part it cannot find is empty; other countries' addresses mostly give the street and city only.

Also known as: _parse address_, _address components_, _postcode from address_, _city from address_, _zip code from address_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Part | `house number` / `street` / `unit` / `city` / `region` / `postcode` / `country` | yes | `postcode` |

| `value` | `value` |
|---|---|
| `10 Downing Street, London, SW1A 2AA` | `SW1A 2AA` |
| `350 Fifth Avenue, New York, NY 10118` | `10118` |

### Standardise a currency

`clean.currency_code`

Write a currency as its ISO 4217 code from a symbol or a name (£ or pounds to GBP, € to EUR); 33 currencies.

Also known as: _currency code_, _iso 4217_, _standardise currency_, _currency symbol_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `£` | `GBP` |
| `euros` | `EUR` |
| `US Dollars` | `USD` |
| `Usd` | `USD` |
| `???` | _(empty)_ |

### Standardise a person's name

`clean.person_name`

Write a name with the capitals people expect (McDonald, O'Brien, Smith-Jones, Ludwig van Beethoven), tidy spaces, and optionally drop titles such as Mr and Dr.

Also known as: _standardise name_, _proper case name_, _name case_, _clean name_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Drop titles | boolean | no | `False` |

| `value` | `value` |
|---|---|
| `JOHN  MCDONALD` | `John McDonald` |
| `mary o'brien` | `Mary O'Brien` |
| `Dr. jan van der berg` | `Jan van der Berg` |

### Fix values in the wrong column

`clean.fix_swapped`

Swap two columns' values on the rows where this one does not look like what it should hold and the other does (a phone number typed in the name box). The run says how many rows it swapped.

Also known as: _swapped columns_, _wrong column_, _fix swapped values_, _misplaced values_

| Setting | Type | Required | Default |
|---|---|---|---|
| The other column | column | yes | none |
| This column should hold | `a number` / `a date` / `an email` / `text` | yes | `a number` |

| `name` | `name` |
|---|---|
| `Ana` | `Ana` |
| `0456` | `Ben` |

### Standardise measurements

`clean.units`

Read measurements written with their units ("5 kg", "5000g", "11 lbs") as numbers in one unit; a value without a unit, or in another kind of unit, is empty.

Also known as: _standardise units_, _parse measurements_, _units in text_, _normalise units_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| In | `mm` / `cm` / `m` / `km` / `in` / `ft` / `yd` / `mi` / `nmi` / `mg` / `g` / `kg` / `t` / `oz` / `lb` / `st` / `ml` / `cl` / `l` / `m3` / `tsp` / `tbsp` / `fl_oz_us` / `fl_oz_uk` / `cup_us` / `pint_us` / `pint_uk` / `gal_us` / `gal_uk` / `mm2` / `cm2` / `m2` / `ha` / `km2` / `ft2` / `acre` / `mi2` / `m/s` / `km/h` / `mph` / `kn` / `ms` / `s` / `min` / `h` / `day` / `week` / `bit` / `B` / `KB` / `MB` / `GB` / `TB` / `KiB` / `MiB` / `GiB` / `TiB` / `J` / `kJ` / `cal` / `kcal` / `Wh` / `kWh` / `Pa` / `kPa` / `bar` / `psi` / `atm` / `mmHg` / `C` / `F` / `K` | yes | none |

| `value` | `value` |
|---|---|
| `5 kg` | `5.0` |
| `5000g` | `5.0` |
| `2.2 lbs` | `0.997903` |
| `tall` | _(empty)_ |


## Columns

### Move columns

`columns.move`

Move columns to the start or the end, leaving the rest in order.

Also known as: _reorder_, _move to front_, _move to end_, _arrange_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | yes | none |
| Move to | `start` / `end` | yes | `start` |

| `a` | `columns` |
|---|---|
| `1` | `c,a,b` |

### Sort columns by name

`columns.sort`

Put the columns in alphabetical order.

Also known as: _alphabetical_, _order columns_

| Setting | Type | Required | Default |
|---|---|---|---|
| Reverse | boolean | no | `False` |

| `c` | `columns` |
|---|---|
| `1` | `a,b,c` |

### Keep only these columns

`columns.keep_only`

Drop everything else, in the dataset's own order.

Also known as: _select_, _subset_, _choose columns_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns to keep | columns | yes | none |

| `a` | `columns` |
|---|---|
| `1` | `a,c` |

### Drop columns

`columns.drop`

Remove one or more columns.

Also known as: _remove columns_, _delete columns_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns to drop | columns | yes | none |

| `a` | `columns` |
|---|---|
| `1` | `a` |

### Duplicate a column

`columns.duplicate`

Add a copy, so the original survives an experiment.

Also known as: _copy column_, _clone_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |

| `a` | `a_copy` |
|---|---|
| `1` | `1` |

### Rename a column

`columns.rename`

Give a column a new name.

Also known as: _rename_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| New name | text | yes | none |

| `a` | `columns` |
|---|---|
| `1` | `b` |

### Rename many columns

`columns.bulk_rename`

Apply one renaming rule to every column at once.

Also known as: _rename all_, _clean headers_, _snake case_, _prefix_, _suffix_

| Setting | Type | Required | Default |
|---|---|---|---|
| Rule | `snake_case` / `lower` / `upper` / `prefix` / `suffix` / `replace` / `regex` | yes | `snake_case` |
| Find | text | no | none |
| Replace with | text | no | none |

| `Order ID` | `columns` |
|---|---|
| `1` | `order_id,customer_name` |

### Add a column with one value

`columns.add`

Add a column holding the same value on every row: a source label, a default, a flag to fill in later.

Also known as: _add column_, _new column_, _constant column_, _literal column_, _insert column_

| Setting | Type | Required | Default |
|---|---|---|---|
| New column | text | yes | none |
| Value | text | no | none |
| Kind of value | `text` / `number` / `whole number` / `true or false` / `date` | no | `text` |

| `id` | `source` |
|---|---|
| `1` | `web` |
| `2` | `web` |

### Split at fixed positions

`columns.split_by_position`

Cut text into pieces after given numbers of characters (fixed-width records, codes with parts).

Also known as: _split by position_, _fixed width_, _split at character_, _substring columns_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Cut after these characters | list | yes | none |
| Drop the original | boolean | no | `False` |

| `code` | `code_2` |
|---|---|
| `GB12345` | `12` |
| `FR9` | `9` |

### Split by a pattern

`columns.split_by_pattern`

Split text into columns wherever a regular expression matches: any run of spaces, a dash or a slash, a comma with or without a space.

Also known as: _split by regex_, _regex split_, _split on pattern_, _tokenise_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | none |
| Most columns | integer | yes | `2` |
| Drop the original | boolean | no | `False` |

| `v` | `v_2` |
|---|---|
| `a - b/c` | `b` |
| `d` | _(empty)_ |

### Split into rows

`columns.split_to_rows`

Give each value in a list ("red, green, blue") its own row, repeating the other columns.

Also known as: _split to rows_, _explode_, _unnest_, _one row per value_, _split rows_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Separated by | text | yes | `,` |
| Trim spaces around each | boolean | no | `True` |

| `tags` | `tags` |
|---|---|
| `red, green` | `red` |
| `blue` | `green` |

### Use the first row as column names

`columns.promote_headers`

Take the column names from the first row and drop it, for a file whose header was read as data. A blank name becomes column_N.

Also known as: _promote headers_, _first row as header_, _rename from first row_, _header row_, _use row 1_

| `a` | `columns` |
|---|---|
| `name` | `name,age` |

### Turn column names into the first row

`columns.demote_headers`

Move the column names into a first row and name the columns column_1, column_2: for data that has to be read without a header.

Also known as: _demote headers_, _header to row_, _headers as data_

| `name` | `column_1` |
|---|---|
| `Ana` | `name` |


## Join & combine

### Join to the nearest earlier row

`join.as_of`

Bring columns from the other dataset's row that comes just before (or after, or nearest) this row's date or number, optionally matching other columns first: the exchange rate in force on the day, the price at the time of the order.

Also known as: _as of join_, _asof_, _point in time join_, _temporal join_, _nearest earlier_, _rate in force_, _effective date_, _slowly changing_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other dataset | dataset | yes | none |
| This dataset's date or number | column | yes | none |
| The other dataset's date or number | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |
| | Columns of the other dataset to add to each row. | | |
| Which row | `earlier` / `later` / `nearest` | no | `earlier` |
| At most this far (days for dates) | number | no | none |
| Match first on | columns | no | none |
| Their columns to match | dataset_columns | no | none |
| Ending for a name already taken | text | no | `_right` |

| `day` | `rate` |
|---|---|
| `2026-01-03` | `1.1` |
| `2026-01-05` | `1.2` |
| `2025-12-30` | _(empty)_ |

The other dataset in this example:

| `at` | `rate` |
|---|---|
| `2026-01-01` | `1.1` |
| `2026-01-05` | `1.2` |
| `2026-01-09` | `1.15` |

### Join where a value is in a range

`join.range`

Bring columns from the other dataset's rows whose range (from a low to a high column, both included) holds this row's value: a price band, an age group, a fiscal period, a block of IP addresses.

Also known as: _range join_, _between join_, _band_, _bucket lookup_, _interval join_, _ip range_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other dataset | dataset | yes | none |
| This dataset's value | column | yes | none |
| Their range starts at | dataset_column | yes | none |
| Their range ends at | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |
| | Columns of the other dataset to add to each row. | | |
| When several ranges hold it | `every match` / `first match` | no | `every match` |
| Rows in no range | `keep` / `drop` | no | `keep` |
| Ending for a name already taken | text | no | `_right` |

| `age` | `band` |
|---|---|
| `9` | `child` |
| `40` | `adult` |
| `70` | `senior` |
| _(empty)_ | _(empty)_ |

The other dataset in this example:

| `from` | `to` | `band` |
|---|---|---|
| `0` | `17` | `child` |
| `18` | `64` | `adult` |
| `65` | `130` | `senior` |

### Join on similar text

`join.fuzzy`

Bring columns from the other dataset's row whose text is most alike, at or above how alike you ask, with the score of the match: names typed differently, spelling mistakes, words in another order. The same matching the Assistant uses to find duplicates.

Also known as: _fuzzy join_, _fuzzy match_, _approximate join_, _similar names_, _fuzzy merge_, _match names_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other dataset | dataset | yes | none |
| Their text column | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |
| | Columns of the other dataset to add to each row. | | |
| Alike by | `letters` / `edits` / `tokens` / `jaro_winkler` / `sound` | no | `letters` |
| | letters: shared letters in order; edits: few typing changes apart; tokens: the same words in any order; jaro_winkler: alike from the start; sound: sounds alike (English names). | | |
| How alike, from 0 to 1 | number | no | `0.86` |
| Ignore company endings (Ltd, Inc) | boolean | no | `True` |
| Rows that match nothing | `keep` / `drop` | no | `keep` |
| Name of the score column | text | no | none |
| Ending for a name already taken | text | no | `_right` |

| `customer` | `id` |
|---|---|
| `ACME Ltd` | `1` |
| `Globex Corp.` | `2` |
| `Initech` | _(empty)_ |

The other dataset in this example:

| `company` | `id` |
|---|---|
| `Acme Limited` | `1` |
| `Globex Corporation` | `2` |

### Put columns side by side

`combine.merge_by_position`

Add the other dataset's columns row by row: its first row beside this one's first, and so on, as pasting columns next to each other does. This dataset keeps its rows; the run says when the other is longer or shorter.

Also known as: _merge by position_, _side by side_, _paste columns_, _zip_, _horizontal concat_, _cbind_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other dataset | dataset | yes | none |
| Columns to bring | dataset_columns | yes | none |
| | Columns of the other dataset to add to each row. | | |
| Ending for a name already taken | text | no | `_right` |

| `name` | `score` |
|---|---|
| `a` | `10` |
| `b` | `20` |

The other dataset in this example:

| `score` |
|---|
| `10` |
| `20` |

### Keep rows the other dataset also has

`combine.intersect`

Keep the rows whose values (in every column, or the ones chosen) the other dataset has too (INTERSECT).

Also known as: _intersect_, _in both_, _common rows_, _overlap_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other dataset | dataset | yes | none |
| Compare on | columns | no | none |
| | Leave empty to compare every column; the other dataset must have them. | | |
| Repeated rows | `remove` / `keep` | no | `remove` |
| | Remove gives each row once, as SQL's INTERSECT and EXCEPT do. | | |

| `id` | `id` |
|---|---|
| `1` | `2` |
| `2` | `3` |

The other dataset in this example:

| `id` |
|---|
| `2` |
| `3` |
| `4` |

### Keep rows the other dataset does not have

`combine.except`

Keep the rows whose values (in every column, or the ones chosen) the other dataset does not have (EXCEPT).

Also known as: _except_, _minus_, _difference_, _not in_, _missing from_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other dataset | dataset | yes | none |
| Compare on | columns | no | none |
| | Leave empty to compare every column; the other dataset must have them. | | |
| Repeated rows | `remove` / `keep` | no | `remove` |
| | Remove gives each row once, as SQL's INTERSECT and EXCEPT do. | | |

| `id` | `id` |
|---|---|
| `1` | `1` |

The other dataset in this example:

| `id` |
|---|
| `2` |


## Type & conversion

### To text

`type.to_text`

Render as text without inventing decimals.

Also known as: _to string_, _stringify_, _as text_

| `value` | `value` |
|---|---|
| `10` | `10` |
| _(empty)_ | _(empty)_ |

### To number

`type.to_number`

Read as a number. Values that will not parse become null.

Also known as: _to float_, _parse number_, _numeric_

| `value` | `value` |
|---|---|
| `12.5` | `12.5` |
| `abc` | _(empty)_ |

### To whole number

`type.to_integer`

Read as a whole number, dropping any fraction.

Also known as: _to int_, _integer_, _whole_

| `value` | `value` |
|---|---|
| `12.7` | `12` |
| `abc` | _(empty)_ |

### To true/false

`type.to_boolean`

Read yes/no/1/0/true/false. Anything else becomes null.

Also known as: _to bool_, _yes no_, _flag_

| `value` | `value` |
|---|---|
| `yes` | `True` |
| `0` | `False` |
| `maybe` | _(empty)_ |

### Detect the type

`type.detect`

Report what each value looks like, without changing it.

Also known as: _what type_, _guess type_, _profile_

| `value` | `value` |
|---|---|
| `12` | `integer` |
| `abc` | `text` |
| `2026-01-01` | `timestamp` |

### Strip currency symbols

`type.strip_currency`

Remove symbols and grouping, leaving text a number parser can read.

Also known as: _remove dollar_, _currency_, _money_, _thousands separator_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Written as | `us` / `european` | yes | `us` |
| | US: 1,234.56. European: 1.234,56. | | |

| `value` | `value` |
|---|---|
| `$1,200.50` | `1200.50` |
| `€1.200,50` | `1.20050` |

_The second row shows why the style matters: read as US, a European amount comes out a thousand times too small._

### Parse a localised number

`type.parse_number_locale`

Read a number written with European or US grouping.

Also known as: _comma decimal_, _thousands separator_, _european number_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Written as | `us` / `european` | yes | `us` |
| | US: 1,234.56. European: 1.234,56. | | |

| `value` | `value` |
|---|---|
| `1.234,56` | `1234.56` |

### Read a JSON field

`type.json_path`

Pull one value out of JSON by dotted path. Missing paths become null.

Also known as: _json_, _extract json_, _nested field_

| Setting | Type | Required | Default |
|---|---|---|---|
| Path | text | yes | none |

| `value` | `value` |
|---|---|
| `{"customer": {"id": "C-1"}}` | `C-1` |
| `{}` | _(empty)_ |

### Change the type

`type.cast`

Declare a column's type. Values that do not fit become null.

Also known as: _convert_, _retype_, _change type_

| Setting | Type | Required | Default |
|---|---|---|---|
| New type | `text` / `int32` / `int64` / `float64` / `decimal(18,2)` / `boolean` / `date` / `timestamp` / `uuid` / `json` | yes | `text` |

| `value` | `value` |
|---|---|
| `12` | `12` |
| `x` | _(empty)_ |

### Convert with a fallback

`type.coerce_with_fallback`

Read as a number, using a fixed value where it will not parse.

Also known as: _default value_, _on error_, _safe convert_

| Setting | Type | Required | Default |
|---|---|---|---|
| Use instead | text | yes | `0` |

| `value` | `value` |
|---|---|
| `12` | `12.0` |
| `abc` | `0` |

### Change to an exact decimal

`type.to_decimal`

Read as a number with this many decimal places, kept exact rather than as a float and rounded half up from the value as written (1.005 is 1.01): money, quantities that must add up.

Also known as: _to decimal_, _numeric_, _exact number_, _money type_

| Setting | Type | Required | Default |
|---|---|---|---|
| Decimal places | integer | yes | `2` |

| `value` | `value` |
|---|---|
| `1.005` | `1.01` |
| `2` | `2.00` |
| `x` | _(empty)_ |
| _(empty)_ | _(empty)_ |

### Write as JSON

`type.to_json`

Write each value as JSON text: text quoted, numbers as numbers, JSON already there kept as it is.

Also known as: _to json_, _json encode_, _serialise_, _stringify_

| `value` | `value` |
|---|---|
| `a` | `"a"` |
| `3` | `3` |
| _(empty)_ | _(empty)_ |

### Split into a list

`type.to_list`

Turn text like "red, green" into a JSON list (["red", "green"]), to explode or count later.

Also known as: _to array_, _to list_, _split to array_, _make list_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Separated by | text | yes | `,` |

| `value` | `value` |
|---|---|
| `red, green` | `["red", "green"]` |
| _(empty)_ | _(empty)_ |

### Remove thousands separators

`type.strip_thousands`

Read numbers written with thousands separators (1,234,567 or 1.234.567,89) as numbers.

Also known as: _strip thousands_, _remove commas_, _thousands separator_, _grouping_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Thousands separator | `,` / `.` / ` ` / `'` | yes | `,` |

| `value` | `value` |
|---|---|
| `1,234,567` | `1234567.0` |
| `12` | `12.0` |
| `n/a` | _(empty)_ |
| _(empty)_ | _(empty)_ |


## Encoding & privacy

### MD5

`hash.md5`

MD5 digest, in hex. Fast and broken -- fine for change detection, never for secrets.

Also known as: _checksum_, _digest_, _fingerprint_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `abc` | `900150983cd24fb0d6963f7d28e17f72` |

### SHA-1

`hash.sha1`

SHA-1 digest, in hex.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `abc` | `a9993e364706816aba3e25717850c26c9cd0d89d` |

### SHA-256

`hash.sha256`

SHA-256 digest, in hex.

Also known as: _hash_, _sha_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `abc` | `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad` |

### SHA-512

`hash.sha512`

SHA-512 digest, in hex.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `abc` | `ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f` |

### HMAC SHA-256

`hash.hmac_sha256`

Keyed digest, so the same value hashes differently under a different key.

Also known as: _keyed hash_, _signature_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Key | text | yes | none |

| `value` | `value` |
|---|---|
| `abc` | `342e519ce0ad6c03a36b98eeb3f1d130db4813b9df4d1160eda488d712dc78ee` |

### Pseudonymise

`privacy.pseudonymise`

A short, stable token per value, salted so it cannot be looked up elsewhere.

Also known as: _anonymise_, _token_, _de-identify_, _surrogate_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Salt | text | yes | none |
| | Use a different salt per project. The same value maps to the same token under one salt and a different one under another. | | |

| `value` | `value` |
|---|---|
| `ada@example.com` | `f2cead3438378b04` |

### Mask, keeping the ends

`privacy.mask_partial`

Hide the middle, leaving a few characters visible for recognition.

Also known as: _redact_, _hide_, _last four_, _pii_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Keep at the end | integer | yes | `4` |
| Keep at the start | integer | yes | `0` |
| Mask character | text | no | `*` |

| `value` | `value` |
|---|---|
| `4111111111111111` | `************1111` |

### Mask completely

`privacy.mask_full`

Replace every character, keeping the length.

Also known as: _redact fully_, _blank out_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Mask character | text | no | `*` |

| `value` | `value` |
|---|---|
| `secret` | `******` |

### Base64 encode

`encode.base64`

Encode as base64.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `abc` | `YWJj` |

### Base64 decode

`encode.base64_decode`

Decode base64. Values that are not valid base64 become null.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `YWJj` | `abc` |
| `!!` | _(empty)_ |

### URL encode

`encode.url`

Percent-encode for use in a URL.

Also known as: _percent encode_, _escape url_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a b&c` | `a%20b%26c` |

### URL decode

`encode.url_decode`

Decode percent-encoding.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a%20b` | `a b` |

### HTML escape

`encode.html`

Escape characters that would otherwise be markup.

Also known as: _escape html_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `<b>` | `&lt;b&gt;` |

### HTML unescape

`encode.html_unescape`

Turn HTML entities back into characters.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `&amp;` | `&` |

### Replace with a reversible token

`privacy.tokenise`

Replace each value with a token that stays the same for the same value (so it still joins and groups) and that only an administrator can turn back, in Administration, each time recorded in the audit log.

Also known as: _tokenise_, _tokenize_, _reversible_, _encrypt value_, _detokenise_

| Setting | Type | Required | Default |
|---|---|---|---|
| Key name | text | yes | `default` |
| | Values tokenised under one key name reveal only under it. | | |

_Each value becomes a token beginning tok_, the same every run under the same key name._

### Make a key from columns

`key.surrogate`

Make one short key from several columns that is the same whenever they are (a hash of the values): a key for a table that has none.

Also known as: _surrogate key_, _hash key_, _composite key_, _row key_

| Setting | Type | Required | Default |
|---|---|---|---|
| From columns | columns | yes | none |

| `a` | `key` |
|---|---|
| `x` | `5f4c03d55ba8f40f` |
| `x` | `5f4c03d55ba8f40f` |
| `y` | `e2247c49f6d590a5` |

### Make an ID for each row

`key.uuid`

Give each row a UUID: made from columns you choose (the same values always give the same ID), or random but the same every run for the same seed.

Also known as: _uuid_, _guid_, _generate id_, _unique id_, _row id_

| Setting | Type | Required | Default |
|---|---|---|---|
| From columns | columns | no | none |
| Seed, when random | integer | no | `1` |

| `email` | `id` |
|---|---|
| `a@x.com` | `f0a85006-e7b0-5ef7-82fc-c74a2f8ecb05` |


## Code & escape hatches

### Transform with SQL

`code.sql`

Write a SELECT over the data at this step, called input: filters, new columns, groups, joins of input with itself and window functions. It is checked and pushed down like any step, and its columns are known before it runs.

Also known as: _sql step_, _sql_, _query_, _select_, _custom sql_, _write sql_

| Setting | Type | Required | Default |
|---|---|---|---|
| SELECT | text | yes | none |

| `region` | `sales` |
|---|---|
| `n` | `11` |
| `s` | `5` |

### Transform with Python

`code.python`

Run Python on the rows, as a pandas DataFrame called data; what it leaves in result (or data) goes on. It runs in the notebook's sandbox, with its limits on memory, time, imports and the network, and is turned off where those limits cannot be held.

Also known as: _python step_, _python_, _pandas_, _custom code_, _script_

| Setting | Type | Required | Default |
|---|---|---|---|
| Python | text | yes | none |

_Adds a column double from v. Runs only where the sandbox is usable._

### Query JSON (jq)

`code.json_query`

Take values out of JSON text with a jq-style query: paths (.customer.id), positions (.items[0]), every element (.items[]), pipes, and length, keys, values, first, last, join(", "), map(.name) and tostring. Several answers come back as a JSON list.

Also known as: _jq_, _json query_, _json path_, _extract json_, _jmespath_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Query | text | yes | none |

| `j` | `j` |
|---|---|
| `{"items": [{"sku": "a"}, {"sku": "b"}]}` | `a, b` |
| `{}` | _(empty)_ |

### Look up in a small table

`code.lookup_table`

Replace values from a table written here, value=replacement on each line (codes to names), keeping or emptying what is not listed, or writing a default. Pushes down.

Also known as: _lookup table inline_, _map values_, _code to name_, _translate codes_, _mapping table_

| Setting | Type | Required | Default |
|---|---|---|---|
| Table | list | yes | none |
| For anything else | text | no | none |
| Keep values not listed | boolean | no | `True` |

| `c` | `c` |
|---|---|
| `GB` | `United Kingdom` |
| `FR` | `France` |
| `XX` | `Other` |

### Write text from a template

`code.template`

Write a new text column from a template with {column} where each column's value goes (an empty value writes nothing; {{ and }} write braces): an email greeting, a label, a URL.

Also known as: _template render_, _mail merge_, _format string_, _string template_, _build text_

| Setting | Type | Required | Default |
|---|---|---|---|
| Template | text | yes | none |
| New column | text | no | none |

| `first` | `text` |
|---|---|
| `Ana` | `Dear Ana of Leeds` |
| `Ben` | `Dear Ben of ` |

### Look up each value in a web service

`code.http_enrich`

Call a web service once for each different value (GET with {value} in the address, or POST a JSON body) and keep part of its JSON answer, picked with a jq-style query. Only hosts an administrator allows; a secret comes from the server's own settings, never the recipe. The run says how many calls it made.

Also known as: _http enrich_, _api lookup_, _call api_, _web service_, _rest lookup_, _enrich from api_

| Setting | Type | Required | Default |
|---|---|---|---|
| Address | text | yes | none |
| Method | `GET` / `POST` | no | `GET` |
| Body for POST | text | no | none |
| Keep from the answer | text | no | `.` |
| Secret to send | text | no | none |
| | The name of a secret in the server's ENRICHMENT_SECRETS. | | |
| Send it in the header | text | no | `Authorization` |
| New column | text | no | none |

_Each different sku is fetched once and its name kept._


## Geospatial

### Find places from addresses

`geo.geocode`

The latitude and longitude of each address, from the Nominatim-style geocoding service an administrator sets (GEOCODER_URL), one call per different address, at most one a second to OpenStreetMap's own server as it asks.

Also known as: _geocode_, _address to coordinates_, _lat long from address_, _find location_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Only in country | text | no | none |
| Start the new names with | text | no | none |

_Latitude and longitude columns, from the configured geocoder._

### Find addresses from places

`geo.reverse_geocode`

The address (or its city, postcode or country) of each latitude and longitude, from the configured geocoding service.

Also known as: _reverse geocode_, _coordinates to address_, _address from lat long_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| Give | `address` / `city` / `postcode` / `country` / `country code` | no | `address` |
| New column | text | no | none |

_An address column, from the configured geocoder._

### Distance between two places

`geo.distance`

The distance between two latitude and longitude pairs: haversine on a sphere (within about 0.5%, and it runs in the database) or on the WGS84 ellipsoid by Vincenty's method (to the millimetre).

Also known as: _distance between_, _haversine_, _great circle_, _how far_, _vincenty_, _geodesic_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| To latitude | column | yes | none |
| To longitude | column | yes | none |
| In | `metres` / `kilometres` / `miles` / `nautical miles` | no | `kilometres` |
| Measured | `haversine` / `ellipsoid` | no | `haversine` |
| New column | text | no | none |

| `lat` | `distance` |
|---|---|
| `51.5074` | `343.556535` |
| `40.7128` | `3935.751691` |

### Direction to another place

`geo.bearing`

The initial compass bearing, in degrees from north (0 to 360), from one place towards another along the great circle.

Also known as: _bearing_, _heading_, _direction_, _azimuth_, _compass_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| To latitude | column | yes | none |
| To longitude | column | yes | none |
| New column | text | no | none |

| `lat` | `bearing` |
|---|---|
| `51.5074` | `148.115617` |

### Within a distance of a place

`geo.within_radius`

True for places within a distance (haversine) of a centre you give: customers within 10 km of a shop.

Also known as: _within radius_, _nearby_, _geofence_, _within distance_, _radius search_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| Centre latitude | number | yes | none |
| Centre longitude | number | yes | none |
| Distance | number | yes | none |
| In | `metres` / `kilometres` / `miles` / `nautical miles` | no | `kilometres` |
| New column | text | no | none |

| `lat` | `within_radius` |
|---|---|
| `51.51` | `True` |
| `53.48` | `False` |

### Read coordinates

`geo.parse_coordinates`

Read a place written as text into latitude and longitude columns: "51.5, -0.12", degrees, minutes and seconds such as 51°30'26"N 0°7'39"W, or WKT POINT (lon lat). Anything out of range is empty.

Also known as: _parse coordinates_, _lat long_, _dms_, _degrees minutes seconds_, _geocoordinates_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Start the new names with | text | no | none |

| `where` | `latitude` |
|---|---|
| `51°30'26"N 0°7'39"W` | `51.5072222` |
| `48.8566, 2.3522` | `48.8566` |
| `nowhere` | _(empty)_ |

### Make a point from coordinates

`geo.make_point`

Write a latitude and longitude as one WKT point (POINT (lon lat)) in a geography column.

Also known as: _make point_, _to wkt_, _point from lat long_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| New column | text | no | none |

| `lat` | `place` |
|---|---|
| `51.5` | `POINT (-0.12 51.5)` |

### Inside an area

`geo.point_in_polygon`

True for places inside an area you give as WKT or GeoJSON (a delivery zone, a region), by longitude and latitude on the map.

Also known as: _point in polygon_, _inside area_, _geofence_, _within region_, _contains point_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| Area | text | yes | none |
| New column | text | no | none |

| `lat` | `inside` |
|---|---|
| `51.5` | `True` |
| `53` | `False` |

### Which region a place is in

`geo.region`

Bring columns from the shape (in another dataset of named areas, as WKT or GeoJSON) that contains each place: its country, sales territory, or time zone from a time zone boundary file such as timezone-boundary-builder's.

Also known as: _region lookup_, _timezone from coordinates_, _spatial join_, _which country_, _territory_, _reverse geocode offline_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| Areas in | dataset | yes | none |
| Their shape | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |

| `lat` | `name` |
|---|---|
| `51.5` | `South` |
| `60` | _(empty)_ |

The other dataset in this example:

| `shape` | `name` |
|---|---|
| `POLYGON ((-1 51, 1 51, 1 52, -1 52, -1 51))` | `South` |

### Nearest place in another dataset

`geo.nearest`

Bring columns from the nearest place in another dataset (each customer's nearest store), with the distance to it in kilometres.

Also known as: _nearest neighbour_, _closest_, _nearest store_, _knn spatial_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| Places in | dataset | yes | none |
| Their latitude | dataset_column | yes | none |
| Their longitude | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |
| Distance column | text | no | `distance_km` |

| `lat` | `store` |
|---|---|
| `51.6` | `London` |
| `53.5` | `Leeds` |

The other dataset in this example:

| `store` | `slat` | `slon` |
|---|---|---|
| `Leeds` | `53.8` | `-1.55` |
| `London` | `51.5` | `-0.13` |

### Bounding box of a shape

`geo.bounding_box`

The smallest box around a shape, as JSON with min_lon, min_lat, max_lon and max_lat.

Also known as: _bounding box_, _bbox_, _extent_, _envelope_

| `s` | `s` |
|---|---|
| `POLYGON ((-1 51, 1 51, 1 52, -1 52, -1 51))` | `{"min_lon": -1.0, "min_lat": 51.0, "max_lon": 1.0, "max_lat": 52.0}` |

### Centre of a shape

`geo.centroid`

The centre of a shape as a WKT point (its centre of mass on the map, which for shapes the size of a country is close to, not exactly, the centre on the globe).

Also known as: _centroid_, _centre_, _center_, _middle of shape_

| `s` | `s` |
|---|---|
| `POLYGON ((-1 51, 1 51, 1 52, -1 52, -1 51))` | `POINT (0 51.5)` |

### Area of a shape

`geo.area`

The area of a polygon on the earth, on a sphere of the earth's mean radius (holes taken away), in square metres, hectares or square kilometres.

Also known as: _area_, _surface area_, _size of polygon_, _hectares_

| Setting | Type | Required | Default |
|---|---|---|---|
| In | `square metres` / `hectares` / `square kilometres` | no | `square metres` |

| `s` | `s` |
|---|---|
| `POLYGON ((0 0, 0.01 0, 0.01 0.01, 0 0.01, 0 0))` | `123.643458` |

### Grow a shape by a distance

`geo.buffer`

A shape grown outwards by a distance in metres (a circle around a point), measured on a map centred on the shape so the distance holds in every direction.

Also known as: _buffer_, _radius polygon_, _catchment_, _expand shape_

| Setting | Type | Required | Default |
|---|---|---|---|
| Metres | number | yes | `100` |

_A 64-sided polygon whose edge is 100 m from the point._

### Write a shape as GeoJSON

`geo.to_geojson`

Write a WKT shape as GeoJSON, for a map or an API.

Also known as: _to geojson_, _geojson_, _wkt to json_

| `s` | `s` |
|---|---|
| `POINT (1 2)` | `{"type": "Point", "coordinates": [1.0, 2.0]}` |

### Geohash of a place

`geo.geohash_encode`

The geohash of a latitude and longitude: a short code for a cell on the map, longer for a smaller cell (7 characters is about 150 m), shared by places near each other.

Also known as: _geohash encode_, _geohash_, _grid cell_, _spatial index_

| Setting | Type | Required | Default |
|---|---|---|---|
| Latitude | column | yes | none |
| Longitude | column | yes | none |
| Characters | integer | yes | `7` |
| New column | text | no | none |

| `lat` | `geohash` |
|---|---|
| `57.64911` | `u4pruydqqvj` |

### Place of a geohash

`geo.geohash_decode`

The latitude and longitude of the centre of a geohash's cell.

Also known as: _geohash decode_, _from geohash_, _decode geohash_

Offered on **textual** columns.

| `g` | `g_latitude` |
|---|---|
| `u4pruydqqvj` | `57.649111` |


## Enrichment & lookup

### Look up values

`lookup.from_dataset`

Bring columns from the first row of another dataset whose key columns match this row's, or a default; never more rows than before (a VLOOKUP). Look up a key by a value just as well: match on any column.

Also known as: _lookup_, _vlookup_, _xlookup_, _lookup from dataset_, _lookup with default_, _reverse lookup_, _lookup multiple columns_, _map values_, _calendar join_, _lookup from file_, _enrich_

| Setting | Type | Required | Default |
|---|---|---|---|
| Look up in | dataset | yes | none |
| Match on | columns | yes | none |
| Their columns | dataset_columns | yes | none |
| Columns to bring | dataset_columns | yes | none |
| When nothing matches | text | no | none |
| | Leave empty to leave the brought columns empty; or give a value such as Unknown. | | |
| Ending for a name already taken | text | no | `_right` |

| `area` | `region` |
|---|---|
| `N` | `North` |
| `W` | `Unknown` |
| _(empty)_ | `Unknown` |

The other dataset in this example:

| `code` | `region` |
|---|---|
| `N` | `North` |
| `S` | `South` |
| `N` | `Other` |

### Look up in a hierarchy

`lookup.hierarchy`

From a table of items and their parents (a category tree, an org chart), give each row its path from the top, its level, its top ancestor or its parent.

Also known as: _hierarchy lookup_, _parent child_, _tree path_, _ancestors_, _org chart_, _category path_

| Setting | Type | Required | Default |
|---|---|---|---|
| Look up in | dataset | yes | none |
| Their item | dataset_column | yes | none |
| Their item's parent | dataset_column | yes | none |
| Their item's name | dataset_column | no | none |
| Give | `path` / `level` / `top` / `parent` | yes | `path` |
| Path separator | text | no | ` > ` |
| New column | text | no | none |

| `category` | `category_path` |
|---|---|
| `3` | `All > Food > Fruit` |
| `1` | `All` |
| `9` | _(empty)_ |

The other dataset in this example:

| `id` | `parent` | `name` |
|---|---|---|
| `1` | _(empty)_ | `All` |
| `2` | `1` | `Food` |
| `3` | `2` | `Fruit` |

### Add calendar columns

`lookup.date_dimension`

Add the year, quarter, month and its name, ISO week, day of the week and its name, day of the year, weekend, fiscal year and quarter (and, given a country, public holidays) for a date: a date dimension without a table to join.

Also known as: _date dimension_, _calendar columns_, _date parts_, _date dimension join_, _time dimension_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | list | no | none |
| | One per line, from: year, quarter, month, month name, week, day of week, day name, day of year, is weekend, fiscal year, fiscal quarter, is holiday. Empty gives all but holidays. | | |
| Start each new name with | text | no | none |
| Fiscal year starts in month | integer | no | `4` |
| Holidays of country | text | no | none |
| Holidays of region | text | no | none |

| `day` | `day_month_name` |
|---|---|
| `2026-08-23` | `August` |

### Convert at historical rates

`lookup.currency_rate`

Convert an amount using the rate for its currency that was in force on its date, from a table of rates (currency, from date, rate): each row takes the latest rate on or before its date.

Also known as: _currency rate join_, _historical exchange rate_, _fx conversion_, _convert currency by date_

| Setting | Type | Required | Default |
|---|---|---|---|
| Look up in | dataset | yes | none |
| Its currency | column | yes | none |
| Its date | column | yes | none |
| Their currency | dataset_column | yes | none |
| Their rate's start date | dataset_column | yes | none |
| Their rate | dataset_column | yes | none |
| Use the rate to | `multiply` / `divide` | no | `multiply` |
| New column | text | no | none |

| `amount` | `amount_converted` |
|---|---|
| `100` | `85.0` |
| `100` | `87.0` |
| `10` | _(empty)_ |

The other dataset in this example:

| `currency` | `from` | `rate` |
|---|---|---|
| `EUR` | `2026-01-01` | `0.85` |
| `EUR` | `2026-02-01` | `0.87` |
| `USD` | `2026-01-01` | `0.79` |

### Company from a web domain

`lookup.company_from_domain`

Bring the company for an email address, a web address or a domain, from a dataset of domains and companies you provide (subdomains find their parent: mail.acme.com is acme.com's).

Also known as: _company from domain_, _firmographics_, _email to company_, _domain lookup_

| Setting | Type | Required | Default |
|---|---|---|---|
| Look up in | dataset | yes | none |
| Their domain | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |
| When nothing matches | text | no | none |
| | Leave empty to leave the brought columns empty; or give a value such as Unknown. | | |
| Ending for a name already taken | text | no | `_right` |

| `email` | `company` |
|---|---|
| `ana@sales.acme.com` | `Acme` |
| `ben@gmail.com` | _(empty)_ |

The other dataset in this example:

| `domain` | `company` |
|---|---|
| `https://www.acme.com` | `Acme` |

### Country from an IP address

`lookup.country_from_ip`

Bring the country (or any column) for an IPv4 or IPv6 address from a dataset of address ranges you provide, such as DB-IP's free country file (start, end, country), whose ranges do not overlap.

Also known as: _country from ip_, _ip geolocation_, _geoip_, _ip lookup_, _ip to country_

| Setting | Type | Required | Default |
|---|---|---|---|
| Look up in | dataset | yes | none |
| Their range starts at | dataset_column | yes | none |
| Their range ends at | dataset_column | yes | none |
| Columns to bring | dataset_columns | yes | none |
| When nothing matches | text | no | none |
| | Leave empty to leave the brought columns empty; or give a value such as Unknown. | | |
| Ending for a name already taken | text | no | `_right` |

| `ip` | `country` |
|---|---|
| `81.2.69.160` | `GB` |
| `8.8.8.8` | `US` |
| `nope` | _(empty)_ |

The other dataset in this example:

| `start` | `end` | `country` |
|---|---|---|
| `81.2.69.0` | `81.2.69.255` | `GB` |
| `8.8.8.0` | `8.8.8.255` | `US` |


## Deduplication & matching

### Keep the most complete of repeats

`dedupe.keep_most_complete`

Of rows that share these columns, keep the one with the fewest empty values (the first of those that tie).

Also known as: _keep most complete_, _best record_, _dedupe keep fullest_, _most filled_

| Setting | Type | Required | Default |
|---|---|---|---|
| Repeats share | columns | no | none |
| | The columns that make two rows the same thing; leave empty for every column. | | |

| `id` | `phone` |
|---|---|
| `1` | `0123` |
| `1` | _(empty)_ |

### Mark repeats

`dedupe.mark`

Add a true or false column that is true on each row repeating an earlier one in these columns, to look at before removing.

Also known as: _mark duplicates_, _flag duplicates_, _is duplicate_

| Setting | Type | Required | Default |
|---|---|---|---|
| Repeats share | columns | no | none |
| | The columns that make two rows the same thing; leave empty for every column. | | |
| New column | text | no | none |

| `id` | `is_repeat` |
|---|---|
| `1` | `False` |
| `2` | `False` |
| `1` | `True` |

### Count repeats

`dedupe.count`

Add how many rows share each row's values in these columns (1 for a row seen once).

Also known as: _count duplicates_, _duplicate count_, _how many times_

| Setting | Type | Required | Default |
|---|---|---|---|
| Repeats share | columns | no | none |
| | The columns that make two rows the same thing; leave empty for every column. | | |
| New column | text | no | none |

| `id` | `repeats` |
|---|---|
| `1` | `2` |
| `2` | `1` |
| `1` | `2` |

### Remove near repeats

`dedupe.fuzzy`

Remove rows whose value is alike an earlier row's (spelling mistakes, capitals, Ltd and Limited), keeping the first; the run says how many went.

Also known as: _fuzzy dedupe_, _fuzzy deduplicate_, _near duplicates_, _edit distance dedupe_, _phonetic dedupe_, _token dedupe_, _soundex dedupe_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Alike by | `letters` / `edits` / `tokens` / `jaro_winkler` / `sound` | no | `letters` |
| | letters: shared letters in order; edits: few typing changes apart; tokens: the same words in any order; jaro_winkler: alike from the start; sound: sounds alike (English names). | | |
| How alike, from 0 to 1 | number | no | `0.86` |
| Ignore company endings (Ltd, Inc) | boolean | no | `True` |

| `name` | `name` |
|---|---|
| `Acme Ltd` | `Acme Ltd` |
| `ACME Limited` | `Globex` |

### Group alike values

`match.cluster`

Number groups of values that are alike, so rows written differently share a number (empty values have none).

Also known as: _cluster similar values_, _group similar_, _fuzzy group_, _clustering_

| Setting | Type | Required | Default |
|---|---|---|---|
| Alike by | `letters` / `edits` / `tokens` / `jaro_winkler` / `sound` | no | `letters` |
| | letters: shared letters in order; edits: few typing changes apart; tokens: the same words in any order; jaro_winkler: alike from the start; sound: sounds alike (English names). | | |
| How alike, from 0 to 1 | number | no | `0.86` |
| Ignore company endings (Ltd, Inc) | boolean | no | `True` |
| New column | text | no | none |

| `name` | `name_group` |
|---|---|
| `Acme Ltd` | `1` |
| `ACME Limited` | `1` |
| `Globex` | `2` |
| `Acme Ltd` | `1` |

### Replace alike values with one spelling

`match.canonical`

Write every value of a group of alike values the way most rows write it (the first in order when they tie).

Also known as: _merge cluster to canonical_, _canonicalise_, _standard spelling_, _normalise variants_

| Setting | Type | Required | Default |
|---|---|---|---|
| Alike by | `letters` / `edits` / `tokens` / `jaro_winkler` / `sound` | no | `letters` |
| | letters: shared letters in order; edits: few typing changes apart; tokens: the same words in any order; jaro_winkler: alike from the start; sound: sounds alike (English names). | | |
| How alike, from 0 to 1 | number | no | `0.86` |
| Ignore company endings (Ltd, Inc) | boolean | no | `True` |
| New column | text | no | none |

| `name` | `name` |
|---|---|
| `Acme Ltd` | `Acme Ltd` |
| `ACME Limited` | `Acme Ltd` |
| `Globex` | `Globex` |
| `Acme Ltd` | `Acme Ltd` |

### Merge repeats into one row

`match.survivorship`

Make one row from each group of rows that share these columns, taking every column's value by a rule: from the most complete row, the most recent, the most common value, the longest, the first or the last (empty values are passed over).

Also known as: _survivorship rules_, _merge records_, _consolidate_, _coalesce duplicates_, _collapse rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| One row for each | columns | yes | none |
| Keep each column's value from | `most complete` / `most recent` / `most common` / `longest` / `first` / `last` | no | `most complete` |
| | most complete: the row with fewest empty values; most recent: the latest by the date column; most common: the value most rows have; longest: the longest text. | | |
| Most recent by | column | no | none |
| | The date column that decides the most recent, for that rule. | | |

| `id` | `email` |
|---|---|
| `1` | `a@x.com` |
| `1` | `b@x.com` |

### Make one record per real thing

`match.golden_record`

Group rows whose column is alike (the same matching as Remove near repeats), then make one row per group by a survivorship rule, numbered so each golden record can be traced.

Also known as: _golden record_, _master record_, _single customer view_, _entity resolution_, _mdm_

| Setting | Type | Required | Default |
|---|---|---|---|
| Alike by | `letters` / `edits` / `tokens` / `jaro_winkler` / `sound` | no | `letters` |
| | letters: shared letters in order; edits: few typing changes apart; tokens: the same words in any order; jaro_winkler: alike from the start; sound: sounds alike (English names). | | |
| How alike, from 0 to 1 | number | no | `0.86` |
| Ignore company endings (Ltd, Inc) | boolean | no | `True` |
| Keep each column's value from | `most complete` / `most recent` / `most common` / `longest` / `first` / `last` | no | `most complete` |
| | most complete: the row with fewest empty values; most recent: the latest by the date column; most common: the value most rows have; longest: the longest text. | | |
| Most recent by | column | no | none |
| | The date column that decides the most recent, for that rule. | | |
| New column | text | no | none |

| `name` | `city` |
|---|---|
| `Acme Ltd` | `Leeds` |
| `ACME Limited` | `York` |


## Metadata & documentation

### Describe a column

`meta.describe_column`

Say what a column of the output means; each run writes it to the dataset's catalogue entry.

Also known as: _set column description_, _document column_, _column comment_, _describe field_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Description | text | yes | none |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the description goes on the output's catalogue entry._

### Tag a column

`meta.tag_column`

Give a column of the output tags (finance, gdpr, kpi), written to its catalogue entry each run.

Also known as: _set column tags_, _label column_, _tag field_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Tags | list | yes | none |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the tags go on the column in the catalogue._

### Classify a column

`meta.classify_column`

Say how sensitive a column of the output is: public, internal, confidential or restricted.

Also known as: _set column classification_, _sensitivity_, _data classification_, _confidential_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Classification | `public` / `internal` / `confidential` / `restricted` | yes | `internal` |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the classification goes on the column in the catalogue._

### Mark personal data

`meta.mark_personal`

Say a column of the output holds personal data, and of what kind, for the catalogue, retention and erasure requests to find; who may see it is set by policies.

Also known as: _mark column pii_, _pii_, _gdpr_, _personal data_, _sensitive personal_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Kind | `email address` / `phone number` / `name` / `postal address` / `date of birth` / `government id` / `financial account` / `location` / `online identifier` / `other personal data` | yes | `email address` |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the marking goes on the column in the catalogue._

### Link a column to a glossary term

`meta.glossary_term`

Bind a column of the output to a term in the project's glossary (revenue, active customer), so the term knows where its data is.

Also known as: _link to glossary term_, _business glossary_, _definition_, _semantic term_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Glossary term | text | yes | none |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the term is bound to the output's column._

### Set the dataset's owner

`meta.owner`

Name the person who answers for the output dataset, by their username; written to its catalogue entry each run.

Also known as: _set dataset owner_, _data owner_, _steward_, _responsible person_

| Setting | Type | Required | Default |
|---|---|---|---|
| Owner's username | text | yes | none |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the owner goes on the output's catalogue entry._

### Describe the dataset

`meta.describe_dataset`

Say what the output dataset is for; written to its catalogue entry each run.

Also known as: _dataset description_, _document dataset_, _readme_

| Setting | Type | Required | Default |
|---|---|---|---|
| Description | text | yes | none |

| `email` | `email` |
|---|---|
| `a@x.com` | `a@x.com` |

_The rows pass through; the description goes on the output's catalogue entry._


## Machine learning

### Group rows by k-means

`ml.kmeans`

Put rows into k clusters of rows alike in the number columns chosen; the run gives the silhouette (how well separated they are).

Also known as: _k means_, _kmeans_, _clustering_, _segmentation_, _segment customers_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Clusters | integer | yes | `3` |
| Put columns on one scale first | boolean | no | `True` |
| Seed | integer | no | `1` |
| New column | text | no | none |

| `x` | `cluster` |
|---|---|
| `1` | `1` |
| `1.2` | `1` |
| `0.8` | `1` |
| `8` | `2` |
| `8.2` | `2` |
| `7.9` | `2` |

### Group rows by merging nearest

`ml.hierarchical`

Build clusters by merging the nearest rows and groups step by step (agglomerative), cut at k clusters.

Also known as: _hierarchical clustering_, _agglomerative_, _dendrogram_, _linkage_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Clusters | integer | yes | `3` |
| Linkage | `ward` / `average` / `complete` / `single` | no | `ward` |
| Put columns on one scale first | boolean | no | `True` |
| New column | text | no | none |

| `x` | `cluster` |
|---|---|
| `1` | `1` |
| `1.2` | `1` |
| `0.8` | `1` |
| `8` | `2` |
| `8.2` | `2` |
| `7.9` | `2` |

### Group rows by density

`ml.dbscan`

Find clusters of any shape as crowded regions (DBSCAN); rows in no crowd are left without a cluster.

Also known as: _dbscan_, _density clustering_, _noise detection_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Neighbourhood size | number | yes | `0.5` |
| Rows to make a crowd | integer | yes | `5` |
| Put columns on one scale first | boolean | no | `True` |
| New column | text | no | none |

| `x` | `cluster` |
|---|---|
| `1` | `1` |
| `1.2` | `1` |
| `0.8` | `1` |
| `8` | `2` |
| `8.2` | `2` |
| `7.9` | `2` |
| `30` | _(empty)_ |

### Reduce to principal components

`ml.pca`

Replace many correlated number columns with a few components that keep most of their variation (PCA); the run says how much each keeps.

Also known as: _pca_, _principal component analysis_, _dimensionality reduction_, _reduce dimensions_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Components | integer | yes | `2` |
| Put columns on one scale first | boolean | no | `True` |

| `a` | `component_1` |
|---|---|
| `1` | `-1.897367` |
| `2` | `-0.632456` |
| `3` | `0.632456` |
| `4` | `1.897367` |

### Score how unusual each row is

`ml.anomaly_score`

A score from 0 (the most ordinary row) to 1 (the most unusual) from an isolation forest over the number columns.

Also known as: _anomaly score_, _anomaly detection_, _outlier score_, _novelty_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Seed | integer | no | `1` |
| New column | text | no | none |

_The last row, far from the others, scores 1._

### Forecast with ARIMA

`ml.forecast_arima`

Forecast the next periods of a series with an ARIMA model of the order given (p,d,q), with an interval from the model.

Also known as: _arima_, _forecast arima_, _time series forecast_, _box jenkins_, _forecast_, _predict future_, _projection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Time column | column | yes | none |
| Periods ahead | integer | yes | `6` |
| Interval | number | no | `0.95` |
| Step between periods | `` / `day` / `week` / `month` / `quarter` / `year` | no | none |
| | Leave empty to take it from the data. | | |
| Order p,d,q | text | no | `1,1,1` |

| `sales` | `is_forecast` |
|---|---|
| `110` | `False` |
| `120` | `False` |
| `130` | `False` |
| `140` | `False` |
| `150` | `False` |
| `160` | `False` |
| `170` | `False` |
| `180` | `False` |

### Forecast with exponential smoothing

`ml.forecast_smoothing`

Forecast with Holt-Winters exponential smoothing: a level, a trend and (given its length) a season.

Also known as: _exponential smoothing_, _holt winters_, _ets_, _forecast smoothing_, _forecast_, _predict future_, _projection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Time column | column | yes | none |
| Periods ahead | integer | yes | `6` |
| Interval | number | no | `0.95` |
| Step between periods | `` / `day` / `week` / `month` / `quarter` / `year` | no | none |
| | Leave empty to take it from the data. | | |
| Trend | `add` / `none` | no | `add` |
| Season | `add` / `mul` / `none` | no | `add` |
| Season length in rows | integer | no | `0` |

| `sales` | `is_forecast` |
|---|---|
| `110` | `False` |
| `120` | `False` |
| `130` | `False` |
| `140` | `False` |
| `150` | `False` |
| `160` | `False` |
| `170` | `False` |
| `180` | `False` |

### Forecast a trend and a season

`ml.forecast_trend_season`

Forecast with a straight-line trend plus a repeating season (sines and cosines of its length), fitted by least squares: the additive model Prophet popularised, without its changepoints.

Also known as: _prophet_, _prophet style_, _trend and seasonality_, _forecast trend_, _forecast_, _predict future_, _projection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Time column | column | yes | none |
| Periods ahead | integer | yes | `6` |
| Interval | number | no | `0.95` |
| Step between periods | `` / `day` / `week` / `month` / `quarter` / `year` | no | none |
| | Leave empty to take it from the data. | | |
| Season length in rows | integer | no | `0` |

| `sales` | `is_forecast` |
|---|---|
| `110` | `False` |
| `120` | `False` |
| `130` | `False` |
| `140` | `False` |
| `150` | `False` |
| `160` | `False` |
| `170` | `False` |
| `180` | `False` |

### Fill gaps from alike rows

`ml.impute_knn`

Fill an empty number with the average of the rows most alike in the other columns (k nearest neighbours).

Also known as: _knn impute_, _nearest neighbour imputation_, _fill missing knn_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Rows to average | integer | yes | `5` |

| `a` | `b` |
|---|---|
| `1.0` | `2.0` |
| `2.0` | `4.0` |
| `3.0` | `6.0` |
| `4.0` | `8.0` |

### Fill gaps by regression

`ml.impute_iterative`

Fill empty numbers by predicting each column from the others, round after round until the answers settle (iterative imputation).

Also known as: _iterative impute_, _mice_, _regression imputation_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| | Number columns to use; leave empty for every number column. | | |
| Seed | integer | no | `1` |

_The empty b is predicted from a, about 6._

### Predict a label (naive Bayes)

`ml.naive_bayes`

Learn a label from the rows that have it, using number columns, and predict it for every row, with how sure (Gaussian naive Bayes); the run gives the cross-validated accuracy.

Also known as: _naive bayes_, _classify_, _classification_, _predict category_

| Setting | Type | Required | Default |
|---|---|---|---|
| Predict | column | yes | none |
| | Rows that have it teach the model; every row is predicted. | | |
| Using | columns | no | none |
| New column | text | no | none |

| `size` | `kind_predicted` |
|---|---|
| `1` | `small` |
| `1.2` | `small` |
| `0.9` | `small` |
| `5` | `big` |
| `5.5` | `big` |
| `4.9` | `big` |
| `1.1` | `small` |
| `5.1` | `big` |

### Predict a label (decision tree)

`ml.decision_tree`

Learn a label from the rows that have it with a decision tree of limited depth, predict it for every row, and say which columns it relies on.

Also known as: _decision tree_, _classification tree_, _cart_, _predict label_

| Setting | Type | Required | Default |
|---|---|---|---|
| Predict | column | yes | none |
| | Rows that have it teach the model; every row is predicted. | | |
| Using | columns | no | none |
| Most levels | integer | no | `4` |
| Seed | integer | no | `1` |
| New column | text | no | none |

| `size` | `kind_predicted` |
|---|---|
| `1` | `small` |
| `1.2` | `small` |
| `0.9` | `small` |
| `5` | `big` |
| `5.5` | `big` |
| `4.9` | `big` |
| `1.1` | `small` |
| `5.1` | `big` |

### Which columns matter most

`ml.feature_importance`

How much each column helps predict another: how much worse a random forest does when that column is shuffled (permutation importance).

Also known as: _feature importance_, _drivers_, _what matters_, _variable importance_, _key drivers_

| Setting | Type | Required | Default |
|---|---|---|---|
| Predict | column | yes | none |
| Using | columns | no | none |
| Seed | integer | no | `1` |

| `y` | `feature` |
|---|---|
| `0` | `a` |
| `3` | `noise` |

### One column per value (one-hot)

`ml.one_hot`

Turn a column of categories into one 0-or-1 column for each value, for a model that needs numbers.

Also known as: _one hot encode_, _dummy variables_, _indicator columns_, _get dummies_

| Setting | Type | Required | Default |
|---|---|---|---|
| At most this many columns | integer | no | `100` |
| Drop the original | boolean | no | `False` |

| `c` | `c_red` |
|---|---|
| `red` | `1` |
| `blue` | `0` |
| `red` | `1` |

### Number the categories

`ml.ordinal`

Give each category a number: in the order you list, or alphabetical (for a model that needs numbers and an order that means something).

Also known as: _ordinal encode_, _label encode_, _category codes_, _rank categories_

| Setting | Type | Required | Default |
|---|---|---|---|
| In order | list | no | none |

| `size` | `size` |
|---|---|
| `M` | `2` |
| `S` | `1` |
| `L` | `3` |

### Replace categories with their average outcome

`ml.target_encode`

Replace each category with the average of a target column for it, pulled towards the overall average when it has few rows (smoothing), for a model that needs numbers.

Also known as: _target encode_, _mean encoding_, _likelihood encoding_

| Setting | Type | Required | Default |
|---|---|---|---|
| Outcome | column | yes | none |
| Smoothing | number | no | `10` |

| `c` | `c` |
|---|---|
| `a` | `2.0` |
| `a` | `2.0` |
| `b` | `10.0` |

### Key words of each text (TF-IDF)

`ml.tfidf`

For each text, the words that set it apart from the rest (term frequency times inverse document frequency), as a JSON object of word to weight.

Also known as: _tfidf_, _tf idf_, _text vectorise_, _keywords_, _bag of words_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Words per text | integer | yes | `5` |

| `t` | `t` |
|---|---|
| `red apple` | `{"red": 0.8148}` |
| `green apple` | `{"green": 0.8148}` |

### Most alike rows

`ml.similarity_matrix`

For each row, the rows most alike it by cosine similarity: of number columns, or of one text column's words (TF-IDF). Rows are counted from 1.

Also known as: _similarity matrix_, _cosine similarity_, _similar items_, _nearest rows_, _recommend_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | yes | none |
| Most alike per row | integer | yes | `3` |

| `t` | `other_row` |
|---|---|
| `red apple` | `2` |
| `red apples` | `1` |
| `blue sky` | `1` |


## Nested data

### Flatten object into columns

`nested.flatten`

Turn a column holding an object into one column per field, named by their path.

Also known as: _unnest object_, _expand object_, _json to columns_, _normalize object_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Fields | columns | yes | none |
| | Dotted paths, e.g. address.city. Use 'Describe a JSON column's shape' to list what is there. | | |
| Prefix | text | no | none |
| Remove the original column | boolean | no | `True` |

| `who` | `address.city` |
|---|---|
| `{"name": "Ada", "address": {"city": "London"}}` | `London` |

_Nested objects keep their path, so `address.city` is one column._

### Explode array into rows

`nested.explode`

Turn a column holding an array into one row per element, repeating the other columns.

Also known as: _unnest array_, _array to rows_, _expand rows_, _flatten array_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Keep rows with an empty array | boolean | no | `True` |

| `items` | `items` |
|---|---|
| `[1, 2, 3]` | `1` |

_One row becomes three. Every other column repeats._

### Extract a value by path

`nested.json_extract`

Pull one value out of a JSON column by its dotted path, e.g. `address.city` or `items.0.sku`.

Also known as: _json path_, _jsonpath_, _get nested value_, _pluck_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Path | text | yes | none |
| New column | text | no | none |

| `payload` | `city` |
|---|---|
| `{"address": {"city": "Oslo"}}` | `Oslo` |

### Collect rows into an array

`nested.collect`

The inverse of explode: gather a column's values into one array per group.

Also known as: _group into array_, _array_agg_, _implode_, _nest_, _unexplode_

| Setting | Type | Required | Default |
|---|---|---|---|
| Group by | columns | yes | none |
| Collect | column | yes | none |
| New column | text | no | none |

| `sku` | `skus` |
|---|---|
| `x` | `["x", "y"]` |
| `y` | `["z"]` |

### Describe a JSON column's shape

`nested.infer_json_schema`

Replace the table with one row per field found in a JSON column: its path, the types seen there, and how many documents actually have it.

Also known as: _json schema_, _describe json_, _what is in this column_, _shape_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |

| `payload` | `path` |
|---|---|
| `{"id": 1, "tags": ["a"]}` | `id` |
| `{"id": 2}` | `tags` |

_`id` is in both documents and `tags` is in one, which is the useful part: a pipeline built on `tags` breaks on half the rows. `tags[]` describes what is inside the array._

### Split a nested array into its own table

`nested.normalise`

Turn one document with a repeated section into a child table, carrying the parent's key so the two can be joined back together.

Also known as: _child table_, _split out_, _one to many_, _relational_, _shred_

| Setting | Type | Required | Default |
|---|---|---|---|
| Nested column | column | yes | none |
| Parent key | column | yes | none |
| Fields to keep | columns | yes | none |
| | Dotted paths inside each element, e.g. sku or product.name. | | |
| Child column prefix | text | no | none |

| `lines` | `sku` |
|---|---|
| `[{"sku": "x", "qty": 2}]` | `x` |

_The result is the child table. `order_id` travels with it so a join puts the two back together._


## Missing data

### Fill blanks with a value

`null.fill_constant`

Replace nulls with a fixed value.

Also known as: _fill na_, _replace null_, _default_

| Setting | Type | Required | Default |
|---|---|---|---|
| Value | text | yes | none |

| `value` | `value` |
|---|---|
| `a` | `a` |
| _(empty)_ | `unknown` |

### Fill blanks from another column

`null.fill_from_column`

Where this column is null, take the value from another.

Also known as: _coalesce_, _fallback column_

| Setting | Type | Required | Default |
|---|---|---|---|
| Other column | column | yes | none |

| `value` | `value` |
|---|---|
| `a` | `a` |
| _(empty)_ | `y` |

### Treat blanks as missing

`null.empty_to_null`

Turn empty and whitespace-only text into a real null.

Also known as: _empty string_, _blank to null_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a` | `a` |
| `   ` | _(empty)_ |
| _(blank)_ | _(empty)_ |

### Treat missing as blank

`null.null_to_empty`

Turn nulls into empty text, for systems that cannot express null.

Also known as: _null to empty string_

| `value` | `value` |
|---|---|
| `a` | `a` |
| _(empty)_ | _(blank)_ |

### Recognise 'NA' as missing

`null.normalise_tokens`

Turn the strings exports use for nothing -- NA, N/A, NULL, -, unknown -- into real nulls.

Also known as: _na_, _n/a_, _placeholder_, _sentinel_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Also treat as missing | text | no | none |
| | A comma-separated list, on top of the built-in ones. | | |

| `value` | `value` |
|---|---|
| `a` | `a` |
| `N/A` | _(empty)_ |
| `TBD` | _(empty)_ |

### Flag blanks

`null.is_blank`

True where the value is missing or only whitespace.

Also known as: _flag nulls_, _is empty_, _missing_

| `value` | `value` |
|---|---|
| `a` | `False` |
| _(empty)_ | `True` |
| `  ` | `True` |

### Fill gaps along a straight line

`null.interpolate_linear`

Fill an empty value between two known ones by drawing a straight line between them, spaced by a date or number column. Gaps before the first or after the last known value stay empty.

Also known as: _interpolate_, _linear interpolation_, _fill gaps_, _estimate missing_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| In the order of | columns | no | none |
| | A date or number to space the points by; leave empty to take the rows as evenly spaced. | | |
| Within each | columns | no | none |

| `value` | `value` |
|---|---|
| `1` | `1.0` |
| _(empty)_ | `2.0` |
| `3` | `3.0` |
| _(empty)_ | _(empty)_ |

### Fill gaps along a smooth curve

`null.interpolate_spline`

Fill an empty value between known ones with a smooth curve through them (a cubic spline), needing at least three known values.

Also known as: _spline_, _cubic interpolation_, _smooth fill_, _curve fill_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| In the order of | columns | no | none |
| | A date or number to space the points by; leave empty to take the rows as evenly spaced. | | |
| Within each | columns | no | none |

| `value` | `value` |
|---|---|
| `1` | `1.0` |
| `4` | `4.0` |
| _(empty)_ | `9.0` |
| `16` | `16.0` |

### Drop mostly empty columns

`null.drop_mostly_empty`

Drop every column whose share of empty values is above this (0.5 drops columns more than half empty). The first column stays if every one would go.

Also known as: _drop empty columns_, _remove sparse columns_, _mostly null_, _drop null columns_

| Setting | Type | Required | Default |
|---|---|---|---|
| Drop when more than this share is empty | number | yes | `0.5` |

| `a` | `columns` |
|---|---|
| `1` | `a` |

### Fill down

`null.fill_forward`

Fill an empty value with the last value above it in the group (merged cells, sparse readings).

Also known as: _fill forward_, _fill down_, _carry forward_, _last observation carried forward_, _ffill_, _merged cells_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `v` | `v_filled` |
|---|---|
| `1.0` | `1.0` |
| _(empty)_ | `1.0` |
| _(empty)_ | _(empty)_ |
| `3.0` | `3.0` |

### Fill up

`null.fill_backward`

Fill an empty value with the next value below it in the group.

Also known as: _fill backward_, _fill up_, _back fill_, _bfill_, _next observation carried backward_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `v` | `v_filled` |
|---|---|
| _(empty)_ | `2.0` |
| `2.0` | `2.0` |
| _(empty)_ | _(empty)_ |
| `3.0` | `3.0` |


## Numeric

### Round

`numeric.round`

Round to a number of decimal places.

Also known as: _decimal places_, _2dp_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Decimal places | integer | yes | `0` |

| `value` | `value` |
|---|---|
| `1.2345` | `1.23` |

### Round up

`numeric.round_up`

Round towards positive infinity.

Also known as: _ceiling_, _ceil_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `1.2` | `2` |
| `-1.2` | `-1` |

### Round down

`numeric.round_down`

Round towards negative infinity.

Also known as: _floor_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `1.8` | `1` |
| `-1.2` | `-2` |

### Truncate

`numeric.truncate`

Drop the fractional part, towards zero.

Also known as: _integer part_, _chop_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `1.8` | `1` |
| `-1.8` | `-1` |

### Round to a multiple

`numeric.round_to_multiple`

Round to the nearest multiple of a step.

Also known as: _nearest_, _step_, _snap_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Multiple of | number | yes | `1` |

| `value` | `value` |
|---|---|
| `17` | `15` |

### Round a multiple up

`numeric.ceil_to_multiple`

Round up to the next multiple of a step.

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Multiple of | number | yes | `1` |

| `value` | `value` |
|---|---|
| `16` | `20` |

### Round a multiple down

`numeric.floor_to_multiple`

Round down to the previous multiple of a step.

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Multiple of | number | yes | `1` |

| `value` | `value` |
|---|---|
| `19` | `15` |

### Absolute value

`numeric.absolute`

Drop the sign.

Also known as: _abs_, _magnitude_, _positive_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `-3` | `3` |
| `3` | `3` |

### Sign

`numeric.sign`

-1, 0 or 1.

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `-4` | `-1` |
| `0` | `0` |
| `4` | `1` |

### Reciprocal

`numeric.reciprocal`

One divided by the value. Null where the value is zero.

Also known as: _inverse_, _1/x_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `4` | `0.25` |
| `0` | _(empty)_ |

### Square root

`numeric.square_root`

The square root.

Also known as: _sqrt_, _root_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `9` | `3.0` |

### Raise to a power

`numeric.power`

Raise to an exponent.

Also known as: _exponent_, _squared_, _cubed_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Exponent | number | yes | `2` |

| `value` | `value` |
|---|---|
| `3` | `9.0` |

### Logarithm

`numeric.log`

Logarithm to a chosen base. Null for values at or below zero.

Also known as: _log10_, _log2_, _logarithm_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Base | number | yes | `10` |

| `value` | `value` |
|---|---|
| `100` | `2.0` |
| `0` | _(empty)_ |

### Natural logarithm

`numeric.ln`

Logarithm to base e.

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `1` | `0.0` |

### Exponential

`numeric.exponential`

e raised to the value.

Also known as: _e^x_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `0` | `1.0` |

### Remainder

`numeric.modulo`

The remainder after dividing.

Also known as: _mod_, _modulus_, _remainder_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Divide by | number | yes | `2` |

| `value` | `value` |
|---|---|
| `7` | `1` |

### Integer divide

`numeric.integer_divide`

Divide and drop the remainder.

Also known as: _floor divide_, _quotient_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Divide by | number | yes | `2` |

| `value` | `value` |
|---|---|
| `7` | `3` |

### Clamp to a range

`numeric.clamp`

Pull values below the floor up and values above the ceiling down.

Also known as: _limit_, _cap_, _bound_, _winsorise_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Minimum | number | yes | `0` |
| Maximum | number | yes | `100` |

| `value` | `value` |
|---|---|
| `-5` | `0` |
| `50` | `50` |
| `500` | `100` |

### Is even

`numeric.is_even`

True for even whole numbers.

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `2` | `True` |
| `3` | `False` |

### Is odd

`numeric.is_odd`

True for odd whole numbers.

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `2` | `False` |
| `3` | `True` |

### Rescale to a range

`numeric.rescale`

Map a known input range onto a new output range.

Also known as: _normalise_, _min max_, _scale_, _0-1_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Input minimum | number | yes | `0` |
| Input maximum | number | yes | `100` |
| Output minimum | number | yes | `0` |
| Output maximum | number | yes | `1` |

| `value` | `value` |
|---|---|
| `50` | `0.5` |

### Percent of a total

`numeric.percent_of`

Express as a percentage of a known total.

Also known as: _percentage_, _share_, _%_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Total | number | yes | `100` |

| `value` | `value` |
|---|---|
| `25` | `25.0` |

### Group into buckets

`numeric.bin`

Label each value by which fixed-width bucket it falls in.

Also known as: _bucket_, _histogram_, _bands_, _ranges_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| First bucket starts at | number | yes | `0` |
| Bucket width | number | yes | `10` |
| How many buckets | integer | yes | `5` |

| `value` | `value` |
|---|---|
| `5` | `0 to 10` |
| `15` | `10 to 20` |
| `95` | `50+` |

### Flip the sign

`numeric.negate`

Turn positive into negative and back (credits into debits).

Also known as: _negate_, _minus_, _flip sign_, _invert sign_, _opposite_

Offered on **numeric** columns.

| `value` | `value` |
|---|---|
| `5` | `-5` |
| `-2.5` | `2.5` |
| _(empty)_ | _(empty)_ |

### Divide by another column

`numeric.ratio`

This column divided by another, row by row (empty where the other is 0 or empty): a conversion rate, a share, a margin.

Also known as: _ratio_, _divide by column_, _per_, _rate_, _share of_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Divided by | column | yes | none |

| `a` | `r` |
|---|---|
| `6` | `2.0` |
| `1` | _(empty)_ |
| `2` | _(empty)_ |

### Convert at a fixed rate

`numeric.convert_currency`

Multiply by an exchange rate you give (for a rate that changes by day, join to a table of rates with Join to the nearest earlier row).

Also known as: _currency convert_, _exchange rate_, _fx_, _convert money_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Rate | number | yes | none |

| `value` | `value` |
|---|---|
| `100` | `125.0` |
| _(empty)_ | _(empty)_ |

### Convert units

`numeric.convert_units`

Convert between units of length, mass, volume, area, speed, time, data, energy, pressure and temperature (kilometres to miles, °F to °C, MiB to GB).

Also known as: _unit convert_, _units_, _metric to imperial_, _celsius_, _fahrenheit_, _miles_, _kilograms_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| From | `mm` / `cm` / `m` / `km` / `in` / `ft` / `yd` / `mi` / `nmi` / `mg` / `g` / `kg` / `t` / `oz` / `lb` / `st` / `ml` / `cl` / `l` / `m3` / `tsp` / `tbsp` / `fl_oz_us` / `fl_oz_uk` / `cup_us` / `pint_us` / `pint_uk` / `gal_us` / `gal_uk` / `mm2` / `cm2` / `m2` / `ha` / `km2` / `ft2` / `acre` / `mi2` / `m/s` / `km/h` / `mph` / `kn` / `ms` / `s` / `min` / `h` / `day` / `week` / `bit` / `B` / `KB` / `MB` / `GB` / `TB` / `KiB` / `MiB` / `GiB` / `TiB` / `J` / `kJ` / `cal` / `kcal` / `Wh` / `kWh` / `Pa` / `kPa` / `bar` / `psi` / `atm` / `mmHg` / `C` / `F` / `K` | yes | none |
| To | `mm` / `cm` / `m` / `km` / `in` / `ft` / `yd` / `mi` / `nmi` / `mg` / `g` / `kg` / `t` / `oz` / `lb` / `st` / `ml` / `cl` / `l` / `m3` / `tsp` / `tbsp` / `fl_oz_us` / `fl_oz_uk` / `cup_us` / `pint_us` / `pint_uk` / `gal_us` / `gal_uk` / `mm2` / `cm2` / `m2` / `ha` / `km2` / `ft2` / `acre` / `mi2` / `m/s` / `km/h` / `mph` / `kn` / `ms` / `s` / `min` / `h` / `day` / `week` / `bit` / `B` / `KB` / `MB` / `GB` / `TB` / `KiB` / `MiB` / `GiB` / `TiB` / `J` / `kJ` / `cal` / `kcal` / `Wh` / `kWh` / `Pa` / `kPa` / `bar` / `psi` / `atm` / `mmHg` / `C` / `F` / `K` | yes | none |

| `value` | `value` |
|---|---|
| `10` | `6.213712` |
| `0` | `0.0` |
| _(empty)_ | _(empty)_ |

### Group into chosen ranges

`numeric.bin_custom`

Label each value by the range it falls in, from edges you choose (0, 18, 65, 120 gives 0 to 18, 18 to 65, 65 to 120), with your own labels if you like. A value outside every range is empty.

Also known as: _custom bins_, _bands_, _ranges_, _age groups_, _bucket by edges_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Edges | list | yes | none |
| Labels | list | no | none |

| `value` | `value` |
|---|---|
| `5` | `child` |
| `30` | `adult` |
| `70` | `senior` |
| `200` | _(empty)_ |
| _(empty)_ | _(empty)_ |

### Scale by the median and spread

`numeric.robust_scale`

Subtract the median and divide by the spread of the middle half (the interquartile range), so outliers do not stretch the scale.

Also known as: _robust scale_, _robust scaling_, _median scale_, _iqr scale_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |

| `value` | `value` |
|---|---|
| `1` | `-1.0` |
| `2` | `-0.5` |
| `3` | `0.0` |
| `4` | `0.5` |
| `100` | `48.5` |

### Group into equal-size groups

`numeric.bin_equal_frequency`

Split the values into this many groups holding about the same number of rows each, labelled by the range each covers.

Also known as: _equal frequency bins_, _quantile bins_, _quantiles_, _equal size buckets_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Groups | integer | yes | `4` |
| Within each | columns | no | none |

| `value` | `value` |
|---|---|
| `1` | `1 to 2` |
| `2` | `1 to 2` |
| `3` | `3 to 4` |
| `4` | `3 to 4` |
| `5` | `5 to 6` |
| `6` | `5 to 6` |


## Rows

### Keep or drop matching rows

`rows.filter`

Keep only the rows a test matches, or drop them.

Also known as: _filter_, _where_, _exclude_, _remove rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Test | `equals` / `not equals` / `greater than` / `at least` / `less than` / `at most` / `contains` / `starts with` / `ends with` / `is empty` / `is not empty` | yes | `equals` |
| Value | text | no | none |
| Then | `keep` / `exclude` | yes | `keep` |

| `region` | `region` |
|---|---|
| `eu` | `eu` |

### Keep rows where a formula holds

`rows.filter_formula`

Keep, or drop, the rows where a formula is true, such as AND([amount] > 100, [region] = "eu"); a row where it is empty is not kept.

Also known as: _filter formula_, _filter by formula_, _where clause_, _custom filter_, _filter expression_

| Setting | Type | Required | Default |
|---|---|---|---|
| Formula | text | yes | none |
| Then | `keep` / `exclude` | yes | `keep` |

| `amount` | `amount` |
|---|---|
| `50` | `150` |

### Keep the first rows

`rows.keep_top`

Keep the first N rows in the dataset's current order.

Also known as: _top n_, _head_, _limit_, _first rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | integer | yes | `100` |

| `n` | `n` |
|---|---|
| `1` | `1` |
| `2` | `2` |

### Skip the first rows

`rows.skip`

Drop the first N rows -- the usual fix for a file with a banner above the data.

Also known as: _offset_, _drop first_, _skip header_

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | integer | yes | `1` |

| `n` | `n` |
|---|---|
| `1` | `2` |
| `2` | `3` |

### Keep a range of rows

`rows.keep_range`

Keep N rows starting from a position, counting from zero.

Also known as: _slice rows_, _page_, _middle_

| Setting | Type | Required | Default |
|---|---|---|---|
| Start at row | integer | yes | `0` |
| How many | integer | yes | `10` |

| `n` | `n` |
|---|---|
| `1` | `2` |
| `2` | `3` |

### Sort rows

`rows.sort`

Order by one or more columns. Where nulls go is stated, not left to the engine.

Also known as: _order by_, _sort_, _arrange_, _rank_

| Setting | Type | Required | Default |
|---|---|---|---|
| Sort by | columns | yes | none |
| Largest first | boolean | no | `False` |
| Blanks first | boolean | no | `False` |

| `n` | `n` |
|---|---|
| `3` | `1` |
| `1` | `2` |
| `2` | `3` |

### Remove duplicate rows

`rows.deduplicate`

Keep one row per distinct combination -- of every column, or of the ones you name.

Also known as: _dedupe_, _distinct_, _unique_, _remove duplicates_

| Setting | Type | Required | Default |
|---|---|---|---|
| Compare only these columns | columns | no | none |
| | Leave empty to compare whole rows. | | |
| Which to keep | `first` / `last` | yes | `first` |

| `n` | `n` |
|---|---|
| `1` | `1` |
| `1` | `2` |

### Drop blank rows

`rows.drop_blank`

Remove rows that are empty -- in every column, or in any of the ones you name.

Also known as: _remove empty_, _drop nulls_, _blank rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Look at these columns | columns | no | none |
| | Leave empty to look at every column. | | |
| Drop when | `all` / `any` | yes | `all` |
| | 'all': every named column is blank. 'any': at least one is. | | |

| `a` | `a` |
|---|---|
| `x` | `x` |
| _(empty)_ | `z` |

### Keep the last rows

`rows.keep_last`

Keep this many rows from the end, in their order.

Also known as: _tail_, _last n_, _keep bottom_, _bottom rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | integer | yes | `10` |

| `n` | `n` |
|---|---|
| `1` | `4` |
| `2` | `5` |

### Skip the last rows

`rows.skip_last`

Drop this many rows from the end (a totals line, a footer).

Also known as: _drop last_, _remove footer_, _skip bottom_, _drop trailing rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | integer | yes | `10` |

| `n` | `n` |
|---|---|
| `1` | `1` |
| `2` | `2` |
| `3` | `3` |

### Reverse the rows

`rows.reverse`

Put the rows in the opposite order.

Also known as: _reverse order_, _flip_, _upside down_, _invert rows_

| `n` | `n` |
|---|---|
| `1` | `3` |
| `2` | `2` |
| `3` | `1` |

### Shuffle the rows

`rows.shuffle`

Put the rows in a random order that is the same every run for the same seed.

Also known as: _shuffle_, _randomise order_, _random order_, _permute_

| Setting | Type | Required | Default |
|---|---|---|---|
| Seed | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `5` |
| `2` | `1` |
| `3` | `2` |
| `4` | `3` |
| `5` | `4` |

### Delete rows by number

`rows.delete`

Delete the rows at these positions, counted from 1 in the order the rows are in.

Also known as: _delete row_, _remove row_, _drop row number_

| Setting | Type | Required | Default |
|---|---|---|---|
| Row numbers | list | yes | none |

| `n` | `n` |
|---|---|
| `1` | `1` |
| `2` | `3` |
| `3` | `5` |

### Add a row

`rows.insert`

Add one row with the values given, at the start or the end; columns not named are empty.

Also known as: _insert row_, _add row_, _append row_, _new row_

| Setting | Type | Required | Default |
|---|---|---|---|
| Values | list | yes | none |
| Where | `at the end` / `at the start` | no | `at the end` |

| `item` | `item` |
|---|---|
| `tea` | `tea` |

### Sort in a chosen order

`rows.custom_order`

Put rows in the order of a list of values (Low, Medium, High; Mon to Sun); values not in the list come after.

Also known as: _custom sort_, _sort by list_, _manual order_, _ordinal sort_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Values in order | list | yes | none |

| `size` | `size` |
|---|---|
| `M` | `S` |
| `XL` | `M` |
| `S` | `L` |
| `L` | `XL` |

### Keep rows that do not convert

`rows.keep_errors`

Keep only the rows whose value cannot be read as a number, a date or true or false, to see what is wrong.

Also known as: _keep errors_, _show bad values_, _invalid rows_, _rows that fail_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Should be | `a number` / `a whole number` / `a date` / `true or false` | no | `a number` |

| `v` | `v` |
|---|---|
| `12` | `twelve` |

### Drop rows that do not convert

`rows.remove_errors`

Drop the rows whose value cannot be read as a number, a date or true or false; empty values stay.

Also known as: _remove errors_, _drop bad values_, _drop invalid rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Should be | `a number` / `a whole number` / `a date` / `true or false` | no | `a number` |

| `v` | `v` |
|---|---|
| `12` | `12` |
| `twelve` | _(empty)_ |


## Sampling & splitting

### Random sample

`sample.random`

Keep a random share (or number) of the rows, the same ones every run for the same seed.

Also known as: _random sample_, _sample_, _subset_, _random rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Share of rows | number | no | none |
| | From 0 to 1 (0.1 is a tenth). Give this or a number of rows. | | |
| Or this many rows | integer | no | none |
| Seed | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `4` |
| `2` | `5` |
| `3` | `8` |

### Sample each group alike

`sample.stratified`

Keep the same share (or number) of rows from every group, so small groups are not lost from the sample.

Also known as: _stratified sample_, _stratify_, _proportional sample_, _sample by group_

| Setting | Type | Required | Default |
|---|---|---|---|
| Groups in | column | yes | none |
| Share of rows | number | no | none |
| | From 0 to 1 (0.1 is a tenth). Give this or a number of rows. | | |
| Or this many rows | integer | no | none |
| Seed | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `2` |
| `2` | `3` |
| `3` | `5` |
| `4` | `7` |
| `5` | `10` |

### Every nth row

`sample.systematic`

Keep every nth row, starting from a given row.

Also known as: _systematic sample_, _every nth row_, _every other row_, _interval sample_

| Setting | Type | Required | Default |
|---|---|---|---|
| Every | integer | yes | `10` |
| Starting at row | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `2` |
| `2` | `5` |
| `3` | `8` |

### Sample whole groups

`sample.cluster`

Choose some groups at random and keep all their rows (cluster sampling: a few shops, every sale in each).

Also known as: _cluster sample_, _sample groups_, _random groups_

| Setting | Type | Required | Default |
|---|---|---|---|
| Groups in | column | yes | none |
| Groups to keep | integer | yes | `1` |
| Seed | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `1` |
| `2` | `2` |
| `3` | `3` |
| `4` | `4` |
| `5` | `5` |
| `6` | `6` |

### Sample a fixed number in one pass

`sample.reservoir`

Keep exactly this many rows, each row as likely as any other, in one pass over the data (reservoir sampling, for when the total is not known first).

Also known as: _reservoir sample_, _fixed size sample_, _streaming sample_, _algorithm r_

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows | integer | yes | `100` |
| Seed | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `5` |
| `2` | `8` |
| `3` | `9` |

### Balance the groups

`sample.balanced`

Keep the same number of rows of every value of a column, as many as the smallest group has (for a model that would otherwise learn the commonest answer).

Also known as: _balanced sample_, _undersample_, _class balance_, _equal groups_

| Setting | Type | Required | Default |
|---|---|---|---|
| Balance | column | yes | none |
| Seed | integer | no | `1` |

| `n` | `n` |
|---|---|
| `1` | `2` |
| `2` | `3` |
| `3` | `4` |
| `4` | `6` |
| `5` | `7` |
| `6` | `8` |
| `7` | `9` |
| `8` | `10` |

### Split into training and test rows

`sample.train_test`

Label each row train or test at random, a share in test, optionally the same share within each value of a column (stratified).

Also known as: _train test split_, _holdout_, _validation split_, _split data_

| Setting | Type | Required | Default |
|---|---|---|---|
| Share for testing | number | yes | `0.2` |
| Keep the share in each | column | no | none |
| Seed | integer | no | `1` |
| New column | text | no | none |

| `n` | `split` |
|---|---|
| `1` | `train` |
| `2` | `test` |
| `3` | `test` |
| `4` | `train` |
| `5` | `train` |

### Split by time

`sample.time_split`

Label rows after a date (or the latest share of them) test and the rest train, so a model is judged on data from after what it learnt from.

Also known as: _time based split_, _temporal split_, _out of time_, _backtest split_

| Setting | Type | Required | Default |
|---|---|---|---|
| Date column | column | yes | none |
| After | text | no | none |
| Or the latest share | number | no | `0.2` |
| New column | text | no | none |

| `d` | `split` |
|---|---|
| `2026-01-01` | `train` |
| `2026-01-02` | `train` |
| `2026-01-03` | `train` |
| `2026-01-04` | `test` |
| `2026-01-05` | `test` |

### Label rows by a condition

`sample.split_by_condition`

Label each row by whether a formula holds for it, with words of your choosing (big and small orders), to filter or deliver each part separately.

Also known as: _split by condition_, _partition by rule_, _label rows_, _segment by rule_

| Setting | Type | Required | Default |
|---|---|---|---|
| Condition | text | yes | none |
| When it holds | text | no | `yes` |
| Otherwise | text | no | `no` |
| New column | text | no | none |

| `amount` | `part` |
|---|---|
| `5` | `small` |
| `50` | `big` |

### Number the rows into parts

`sample.split_into_parts`

Number each row 1 to N to split the data into N parts: in order (the first rows are part 1) or in turn (1, 2, 3, 1, 2, 3).

Also known as: _split into n parts_, _chunks_, _batches_, _partition rows_, _round robin_

| Setting | Type | Required | Default |
|---|---|---|---|
| Parts | integer | yes | `2` |
| Rows go | `in order` / `in turn` | no | `in order` |
| New column | text | no | none |

| `n` | `part` |
|---|---|
| `1` | `1` |
| `2` | `2` |
| `3` | `3` |
| `4` | `1` |
| `5` | `2` |
| `6` | `3` |


## Statistics

### Describe the columns

`stats.describe`

One row per column: how many values and empty ones, how many different, and for numbers the mean, spread, lowest, quartiles, median and highest; the commonest value for every column.

Also known as: _describe_, _summary statistics_, _profile_, _mean median_, _statistics summary_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |

| `v` | `median` |
|---|---|
| `1` | `2.0` |

### Correlation matrix

`stats.correlation_matrix`

How closely every pair of number columns moves together, from -1 to 1, by Pearson (straight-line), Spearman (rank) or Kendall's tau.

Also known as: _correlation matrix_, _correlations_, _pearson_, _spearman_, _corr_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| Method | `pearson` / `spearman` / `kendall` | no | `pearson` |

| `a` | `b` |
|---|---|
| `1` | `1.0` |
| `2` | `1.0` |

### Covariance matrix

`stats.covariance_matrix`

The covariance of every pair of number columns (sample, n - 1).

Also known as: _covariance matrix_, _covariances_, _cov_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |

| `a` | `a` |
|---|---|
| `1` | `1.0` |
| `2` | `2.0` |

### Histogram

`stats.histogram`

Count the values in equal-width bins between the lowest and highest (the last bin includes the highest).

Also known as: _histogram_, _distribution_, _bins_, _frequency distribution_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Bins | integer | yes | `10` |

| `v` | `count` |
|---|---|
| `1` | `1` |
| `2` | `2` |
| `2` | `2` |

### Frequency table

`stats.frequency`

How often each value appears, commonest first, with its share and the running share.

Also known as: _frequency table_, _value counts_, _counts_, _tally_, _pareto_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |

| `v` | `count` |
|---|---|
| `a` | `2` |
| `b` | `1` |
| `a` | `1` |

### Find outliers by the middle half

`stats.outliers_iqr`

True for values more than 1.5 times the interquartile range below the lower quartile or above the upper (Tukey's fences).

Also known as: _outliers iqr_, _tukey_, _box plot outliers_, _anomalies_, _outlier detection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Factor | number | no | `1.5` |
| New column | text | no | none |

| `v` | `v_outlier` |
|---|---|
| `10` | `False` |
| `11` | `False` |
| `12` | `False` |
| `11` | `False` |
| `10` | `False` |
| `12` | `False` |
| `11` | `False` |
| `95` | `True` |

### Find outliers by standard deviations

`stats.outliers_zscore`

True for values more than 3 standard deviations from the mean (suits values that are roughly normal).

Also known as: _outliers z score_, _z score outliers_, _3 sigma_, _anomalies_, _outlier detection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Factor | number | no | `3.0` |
| New column | text | no | none |

| `v` | `v_outlier` |
|---|---|
| `10` | `False` |
| `11` | `False` |
| `12` | `False` |
| `11` | `False` |
| `10` | `False` |
| `12` | `False` |
| `11` | `False` |
| `95` | `False` |

### Find outliers by median deviation

`stats.outliers_mad`

True for values whose modified z-score, from the median absolute deviation, is above 3.5 (robust to the outliers themselves).

Also known as: _outliers mad_, _robust outliers_, _median absolute deviation_, _anomalies_, _outlier detection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Factor | number | no | `3.5` |
| New column | text | no | none |

| `v` | `v_outlier` |
|---|---|
| `10` | `False` |
| `11` | `False` |
| `12` | `False` |
| `11` | `False` |
| `10` | `False` |
| `12` | `False` |
| `11` | `False` |
| `95` | `True` |

### Find unusual rows

`stats.outliers_isolation_forest`

True for rows that an isolation forest separates from the rest quickly, looking at several number columns at once; a score says how unusual each is.

Also known as: _isolation forest_, _anomaly detection_, _multivariate outliers_, _unusual rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | no | none |
| Share expected to be unusual | number | no | none |
| Seed | integer | no | `1` |
| New column | text | no | none |

| `a` | `outlier` |
|---|---|
| `1` | `False` |
| `1.1` | `False` |
| `0.9` | `False` |
| `1` | `False` |
| `9` | `True` |

### Test for a normal distribution

`stats.normality`

Test whether the values could come from a normal distribution: Shapiro-Wilk, or D'Agostino-Pearson past 5,000 values.

Also known as: _normality test_, _shapiro wilk_, _is it normal_, _gaussian test_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `v` | `test` |
|---|---|
| `2.1` | `Shapiro-Wilk` |

### Compare means (t-test)

`stats.t_test`

Test whether the mean differs from a value (one-sample), or between two groups (Welch's two-sample, not assuming equal spreads).

Also known as: _t test_, _ttest_, _compare means_, _student t_, _welch_, _significance test_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Groups in | column | no | none |
| | A column with two groups to compare; leave empty to compare with a value. | | |
| Or compare with | number | no | `0` |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `v` | `test` |
|---|---|
| `5` | `Welch's two-sample t-test` |

### Compare before and after (paired t-test)

`stats.paired_t_test`

Test whether two columns measured on the same rows (before and after) differ on average.

Also known as: _paired t test_, _before after_, _dependent t test_, _repeated measures_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Paired with | column | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `before` | `test` |
|---|---|
| `10` | `paired t-test` |

### Compare means of several groups (ANOVA)

`stats.anova`

Test whether the mean is the same in every group (one-way analysis of variance).

Also known as: _anova_, _f test_, _analysis of variance_, _compare groups_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Groups in | column | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `v` | `test` |
|---|---|
| `1` | `one-way ANOVA` |

### Test whether two categories are related (chi-square)

`stats.chi_square`

Test whether two columns of categories are independent, or one tells you something about the other.

Also known as: _chi square_, _chi2_, _independence test_, _contingency test_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| And | column | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `a` | `test` |
|---|---|
| `x` | `chi-square test of independence` |

### Compare two groups without assuming normal (Mann-Whitney)

`stats.mann_whitney`

Test whether values in one group tend to be larger than in the other, by ranks.

Also known as: _mann whitney_, _wilcoxon rank sum_, _u test_, _non parametric_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Groups in | column | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `v` | `test` |
|---|---|
| `1` | `Mann-Whitney U` |

### Compare distributions (Kolmogorov-Smirnov)

`stats.ks_test`

Test whether two groups are distributed alike, or one column like a normal distribution with its own mean and spread.

Also known as: _kolmogorov smirnov_, _ks test_, _compare distributions_, _goodness of fit_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| Groups in | column | no | none |
| | A column with two groups to compare; leave empty to compare with a value. | | |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `v` | `test` |
|---|---|
| `1` | `two-sample Kolmogorov-Smirnov` |

### Fit a straight line

`stats.linear_regression`

How one number column moves with another: the intercept and slope by least squares, their standard errors and p-values, and R².

Also known as: _linear regression_, _line of best fit_, _trend line_, _slope_, _ols_

| Setting | Type | Required | Default |
|---|---|---|---|
| Explain | column | yes | none |
| By | column | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `x` | `term` |
|---|---|
| `1` | `intercept` |
| `2` | `x` |
| `3` | `fit` |

### Fit several columns at once

`stats.multiple_regression`

How one number column moves with several others together (ordinary least squares), with each one's estimate, standard error and p-value.

Also known as: _multiple regression_, _multivariate regression_, _ols_, _drivers_

| Setting | Type | Required | Default |
|---|---|---|---|
| Explain | column | yes | none |
| By | columns | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `y` | `term` |
|---|---|
| `8` | `intercept` |
| `7` | `a` |
| `21` | `b` |
| `17` | `fit` |

### Fit a yes-or-no outcome

`stats.logistic_regression`

How several columns change the odds of a 0-or-1 outcome (logistic regression by maximum likelihood), with each one's estimate and p-value.

Also known as: _logistic regression_, _logit_, _classification model_, _odds ratio_

| Setting | Type | Required | Default |
|---|---|---|---|
| Outcome (0 or 1) | column | yes | none |
| By | columns | yes | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `x` | `term` |
|---|---|
| `1` | `intercept` |
| `2` | `x` |
| `3` | `fit` |

### Add fitted values and residuals

`stats.residuals`

Fit the column by least squares on others and add, on every row, the fitted value and the residual (what the fit misses), to look for what it does not explain.

Also known as: _residual analysis_, _residuals_, _fitted values_, _prediction error_

| Setting | Type | Required | Default |
|---|---|---|---|
| Explain | column | yes | none |
| By | columns | yes | none |

| `y` | `y_residual` |
|---|---|
| `2` | `0.166667` |
| `4` | `-0.333333` |
| `7` | `0.166667` |

### Confidence interval for the mean

`stats.confidence_interval`

The range the true mean is likely in, by Student's t, overall or for each group.

Also known as: _confidence interval_, _margin of error_, _error bars_, _ci_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| For each | column | no | none |
| Confidence | number | no | `0.95` |

| `v` | `mean` |
|---|---|
| `10` | `11.0` |

### How many to sample

`stats.sample_size`

How many responses a survey needs for a margin of error at a confidence, for a share near the one expected (0.5 when unknown), optionally in a finite population. Uses no data.

Also known as: _sample size calculator_, _survey size_, _how many respondents_, _power_

| Setting | Type | Required | Default |
|---|---|---|---|
| Confidence | number | yes | `0.95` |
| Margin of error | number | yes | `0.05` |
| Expected share | number | no | `0.5` |
| Population | integer | no | none |

| `x` | `sample_size` |
|---|---|
| `1` | `385` |

### Split into trend and season

`stats.seasonal_decompose`

Separate a series, in time order, into its trend (a centred moving average), its repeating seasonal pattern of the period given, and what is left (classical decomposition, additive or multiplicative).

Also known as: _seasonal decompose_, _seasonality_, _trend_, _stl_, _decomposition_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| In the order of | column | no | none |
| Season length in rows | integer | yes | `7` |
| Season | `additive` / `multiplicative` | no | `additive` |

| `v` | `v_seasonal` |
|---|---|
| `7` | `-3.0` |
| `14` | `3.0` |
| `9` | `-3.0` |
| `16` | `3.0` |
| `11` | `-3.0` |
| `18` | `3.0` |
| `13` | `-3.0` |
| `20` | `3.0` |

### Autocorrelation by lag

`stats.autocorrelation`

How much a series, in time order, resembles itself this many rows earlier, for each lag, with the 95% band chance alone stays inside.

Also known as: _autocorrelation_, _acf_, _serial correlation_, _lag correlation_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| In the order of | column | no | none |
| Lags | integer | yes | `10` |

| `v` | `lag` |
|---|---|
| `1` | `1` |
| `3` | `2` |

### Test for a trend

`stats.trend_test`

Is a series, in time order, rising or falling beyond chance? The Mann-Kendall test, with Sen's slope for how fast.

Also known as: _trend test_, _mann kendall_, _is it increasing_, _sen slope_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |
| In the order of | column | no | none |
| Significance level | number | no | `0.05` |
| | 0.05 means 5%: how unlikely a result must be by chance to count. | | |

| `v` | `test` |
|---|---|
| `1` | `Mann-Kendall` |

### Find where the level changes

`stats.changepoints`

Number the stretches of a series, in time order, between points where its average shifts (binary segmentation with a penalty so noise does not count), 1 for the first stretch.

Also known as: _changepoint detection_, _change point_, _level shift_, _regime change_, _break detection_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| In the order of | column | no | none |
| Most change points | integer | no | `5` |
| New column | text | no | none |

| `v` | `v_segment` |
|---|---|
| `1` | `1` |
| `1.1` | `1` |
| `0.9` | `1` |
| `1` | `1` |
| `5` | `2` |
| `5.1` | `2` |
| `4.9` | `2` |
| `5` | `2` |

### Fit a distribution

`stats.distribution_fit`

Which of the normal, uniform, exponential and (for positive values) lognormal, gamma and Weibull distributions describes the values best, by maximum likelihood, ranked by AIC, each with a Kolmogorov-Smirnov check.

Also known as: _distribution fit_, _fit distribution_, _which distribution_, _maximum likelihood_, _aic_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | none |

_One row per distribution that fits, best (lowest AIC) first._


## Reshape

### Swap rows and columns

`reshape.transpose`

Turn each column into a row and each row into a column, naming the new columns from a column of your choice (or row_1, row_2).

Also known as: _transpose_, _flip rows and columns_, _rotate_, _swap axes_

| Setting | Type | Required | Default |
|---|---|---|---|
| Name the new columns from | column | no | none |

| `metric` | `sales` |
|---|---|
| `sales` | `10` |
| `costs` | `12` |

### Combine columns into one

`reshape.nest`

Put several columns into one JSON column, for an API that wants an object or a document store.

Also known as: _nest columns_, _to struct_, _combine into json_, _pack columns_, _object column_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | yes | none |
| New column | text | yes | `details` |
| Drop the originals | boolean | no | `True` |

| `id` | `address` |
|---|---|
| `1` | `{"city": "Leeds", "zip": "LS1"}` |

### Cross-tab two columns

`reshape.crosstab`

Count (or total) rows by two columns at once: one row per value of the first, one column per value of the second.

Also known as: _cross tab_, _crosstab_, _contingency table_, _two way table_, _matrix count_

| Setting | Type | Required | Default |
|---|---|---|---|
| One row per | column | yes | none |
| One column per | column | yes | none |
| Show | `count` / `sum` / `average` / `lowest` / `highest` | no | `count` |
| Of column | column | no | none |

| `shop` | `mon` |
|---|---|
| `a` | `1` |
| `a` | `1` |


## Text

### Trim whitespace

`text.trim`

Remove spaces, tabs and newlines from both ends.

Also known as: _strip_, _whitespace_, _clean spaces_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `  hello  ` | `hello` |
| `x` | `x` |

### Trim leading whitespace

`text.trim_start`

Remove whitespace from the start only.

Also known as: _left trim_, _lstrip_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `  hello  ` | `hello  ` |

### Trim trailing whitespace

`text.trim_end`

Remove whitespace from the end only.

Also known as: _right trim_, _rstrip_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `  hello  ` | `  hello` |

### Collapse whitespace

`text.collapse_whitespace`

Replace every run of whitespace with a single space, and trim the ends.

Also known as: _squeeze spaces_, _normalise spaces_, _double spaces_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `a   b \t c ` | `a b c` |

### UPPERCASE

`text.upper`

Convert to upper case.

Also known as: _capitals_, _caps_, _uppercase_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `hello` | `HELLO` |

### Lowercase

`text.lower`

Convert to lower case.

Also known as: _lowercase_, _small_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `HELLO` | `hello` |

### Title Case

`text.title_case`

Capitalise the first letter of every word.

Also known as: _capitalise each word_, _proper case_, _initcap_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `hello world` | `Hello World` |

### Sentence case

`text.sentence_case`

Capitalise the first letter and lower the rest.

Also known as: _first letter capital_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `hELLO WORLD` | `Hello world` |

### Swap case

`text.swap_case`

Turn upper case into lower and lower into upper.

Also known as: _invert case_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `Hello` | `hELLO` |

### Pad left

`text.pad_left`

Pad to a fixed width by adding characters on the left.

Also known as: _zero pad_, _leading zeros_, _fixed width_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Total length | integer | yes | `10` |
| Fill character | text | no | `0` |

| `value` | `value` |
|---|---|
| `42` | `00042` |

### Pad right

`text.pad_right`

Pad to a fixed width by adding characters on the right.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Total length | integer | yes | `10` |
| Fill character | text | no | ` ` |

| `value` | `value` |
|---|---|
| `42` | `42...` |

### Truncate

`text.truncate`

Shorten to a maximum length, optionally ending with a suffix.

Also known as: _shorten_, _cut_, _limit length_, _ellipsis_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Maximum length | integer | yes | `50` |
| Suffix | text | no | none |

| `value` | `value` |
|---|---|
| `abcdefgh` | `abc…` |

### First characters

`text.left`

Keep the first N characters.

Also known as: _first n_, _prefix_, _head_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | integer | yes | `1` |

| `value` | `value` |
|---|---|
| `abcdef` | `abc` |

### Last characters

`text.right`

Keep the last N characters.

Also known as: _last n_, _suffix_, _tail_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| How many | integer | yes | `1` |

| `value` | `value` |
|---|---|
| `abcdef` | `def` |

### Substring

`text.substring`

Take a run of characters from a starting position. Positions count from 1.

Also known as: _mid_, _slice_, _extract range_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Start position | integer | yes | `1` |
| Length | integer | yes | `1` |

| `value` | `value` |
|---|---|
| `abcdef` | `bcd` |

### Extract before

`text.extract_before`

Everything before the first occurrence of a marker.

Also known as: _split before_, _up to_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Marker | text | yes | none |

| `value` | `value` |
|---|---|
| `ada@example.com` | `ada` |

### Extract after

`text.extract_after`

Everything after the first occurrence of a marker.

Also known as: _split after_, _from_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Marker | text | yes | none |

| `value` | `value` |
|---|---|
| `ada@example.com` | `example.com` |

### Extract between

`text.extract_between`

The text between two markers. Null when either marker is missing.

Also known as: _inner text_, _between delimiters_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Opening marker | text | yes | none |
| Closing marker | text | yes | none |

| `value` | `value` |
|---|---|
| `Order (A-14) sent` | `A-14` |

### Take one part

`text.split_part`

Split on a delimiter and keep one part. Parts count from 1.

Also known as: _nth field_, _delimiter_, _csv part_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Delimiter | text | yes | `-` |
| Which part | integer | yes | `1` |

| `value` | `value` |
|---|---|
| `2026-08-23` | `08` |

### Character at position

`text.char_at`

The single character at a position, counting from 1.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Position | integer | yes | `1` |

| `value` | `value` |
|---|---|
| `abc` | `b` |

### Extract with a pattern

`text.regex_extract`

The first capture group of a regular expression.

Also known as: _regex_, _pattern_, _capture_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | none |

| `value` | `value` |
|---|---|
| `order 4471` | `4471` |

### Replace with a pattern

`text.regex_replace`

Replace everything matching a regular expression.

Also known as: _regex replace_, _substitute_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | none |
| Replacement | text | no | none |

| `value` | `value` |
|---|---|
| `a1b2` | `ab` |

### Count pattern matches

`text.regex_count`

How many times a regular expression matches.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | none |

| `value` | `value` |
|---|---|
| `a1b2c3` | `3` |

### Find and replace

`text.replace`

Replace every occurrence of one piece of text with another.

Also known as: _substitute_, _swap text_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Find | text | yes | none |
| Replace with | text | no | none |

| `value` | `value` |
|---|---|
| `a-b-c` | `a_b_c` |

### Position of text

`text.position`

Where a piece of text first appears, counting from 1. Zero when absent.

Also known as: _find_, _index of_, _search_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Text to find | text | yes | none |

| `value` | `value` |
|---|---|
| `abcabc` | `2` |

### Count occurrences

`text.count_occurrences`

How many times a piece of text appears.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Text to count | text | yes | none |

| `value` | `value` |
|---|---|
| `banana` | `3` |

### Remove characters

`text.remove_characters`

Delete every character in a set.

Also known as: _strip characters_, _delete chars_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Characters | text | yes | none |

| `value` | `value` |
|---|---|
| `$1,200` | `1200` |

### Keep only characters

`text.keep_characters`

Delete everything except the characters in a set.

Also known as: _whitelist characters_, _digits only_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Characters to keep | text | yes | none |

| `value` | `value` |
|---|---|
| `+1 (555) 123` | `1555123` |

### Swap characters

`text.translate`

Replace characters one for one, like tr.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| From | text | yes | none |
| To | text | yes | none |

| `value` | `value` |
|---|---|
| `abc` | `xyz` |

### Length

`text.length`

How many characters.

Also known as: _size_, _characters_, _len_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `hello` | `5` |

### Word count

`text.word_count`

How many whitespace-separated words.

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `one two  three` | `3` |

### Reverse

`text.reverse`

Reverse the characters.

Also known as: _backwards_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `abc` | `cba` |

### Repeat

`text.repeat`

Repeat the text N times.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Times | integer | yes | `2` |

| `value` | `value` |
|---|---|
| `ab` | `ababab` |

### Split camelCase

`text.camel_to_words`

Insert spaces at camel-case boundaries.

Also known as: _camel case_, _split words_, _unCamel_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `orderLineItem` | `order Line Item` |

### Make a slug

`text.slugify`

Lower case, accents folded, everything else turned into hyphens.

Also known as: _url slug_, _kebab_, _handle_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `Crème Brûlée!` | `creme-brulee` |

### Remove accents

`text.remove_accents`

Fold accented letters to their plain equivalents.

Also known as: _unaccent_, _ascii fold_, _diacritics_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `Zoë` | `Zoe` |

### Strip HTML

`text.strip_html`

Remove tags and decode entities, leaving the text.

Also known as: _remove tags_, _html to text_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `<b>Hi</b>&amp;bye` | `Hi&bye` |

### Normalise Unicode

`text.normalise_unicode`

Apply a Unicode normalisation form so equal-looking text compares equal.

Also known as: _nfc_, _nfkc_, _unicode_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Form | `NFC` / `NFD` / `NFKC` / `NFKD` | yes | `NFC` |

| `value` | `value` |
|---|---|
| `ﬁt` | `fit` |

### Soundex code

`text.soundex`

A four-character phonetic code, for matching names that sound alike.

Also known as: _phonetic_, _sounds like_, _fuzzy name_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `Robert` | `R163` |
| `Rupert` | `R163` |

### Starts with

`text.starts_with`

True when the text begins with a given prefix.

Also known as: _begins with_, _prefix_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Prefix | text | yes | none |

| `value` | `value` |
|---|---|
| `abc` | `True` |
| `xbc` | `False` |

### Ends with

`text.ends_with`

True when the text ends with a given suffix.

Also known as: _suffix_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Suffix | text | yes | none |

| `value` | `value` |
|---|---|
| `abc` | `True` |
| `abx` | `False` |

### Contains

`text.contains`

True when the text contains a given piece.

Also known as: _includes_, _has_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Text | text | yes | none |

| `value` | `value` |
|---|---|
| `abc` | `True` |
| `xyz` | `False` |

### Merge columns

`text.merge_columns`

Join this column to others with a separator, skipping the empty ones.

Also known as: _concatenate_, _combine columns_, _join text_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other columns | columns | yes | none |
| Separator | text | no | ` ` |

| `first` | `first` |
|---|---|
| `Ada` | `Ada Lovelace` |
| `Alan` | `Alan` |

### Write in Latin letters

`text.transliterate`

Write Cyrillic and Greek in Latin letters and drop accents (Москва to Moskva, Αθήνα to Athina, Øresund to Oresund), for matching and for systems that take plain letters only.

Also known as: _transliterate_, _romanise_, _romanize_, _latinise_, _to ascii_, _cyrillic to latin_

Offered on **textual** columns.

| `value` | `value` |
|---|---|
| `Москва` | `Moskva` |
| `Αθήνα` | `Athina` |
| `Straße` | `Strasse` |
| _(empty)_ | _(empty)_ |

### Detect the language

`text.detect_language`

Say which language text is written in, as a two-letter code: by its alphabet where that settles it, otherwise by which of 17 languages' commonest words it uses. Texts under three words are not guessed; with confidence on, a second column says how sure (0 to 1).

Also known as: _detect language_, _language detection_, _which language_, _identify language_

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Add how sure | boolean | no | `False` |

| `v` | `v_language` |
|---|---|
| `the cat is on the mat` | `en` |
| `le chat est sur le tapis` | `fr` |
| `Привет, мир` | `ru` |
| `ok` | _(empty)_ |


## Window & analytic

### Row number

`window.row_number`

Number the rows 1, 2, 3 within each group, in order.

Also known as: _row id_, _sequence_, _index_, _position_, _number rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `region` | `row_number` |
|---|---|
| `north` | `1` |
| `north` | `2` |
| `south` | `1` |
| `north` | `3` |
| `south` | `2` |

### Rank

`window.rank`

Rank rows by this column, with ties sharing a rank and the next rank skipped (1, 2, 2, 4).

Also known as: _position_, _standing_, _order_, _league table_, _top_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_rank` |
|---|---|
| `10.0` | `3` |
| `20.0` | `2` |
| `5.0` | `2` |
| `30.0` | `1` |
| `15.0` | `1` |

### Dense rank

`window.dense_rank`

Rank rows by this column with no gaps after ties (1, 2, 2, 3).

Also known as: _rank without gaps_, _dense_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_dense_rank` |
|---|---|
| `10.0` | `3` |
| `20.0` | `2` |
| `5.0` | `2` |
| `30.0` | `1` |
| `15.0` | `1` |

### Percent rank

`window.percent_rank`

Where a row sits in its group, from 0 (first) to 1 (last).

Also known as: _percentile rank_, _percentile_, _relative rank_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_percent_rank` |
|---|---|
| `10.0` | `0.0` |
| `20.0` | `0.5` |
| `5.0` | `0.0` |
| `30.0` | `1.0` |
| `15.0` | `1.0` |

### Cumulative distribution

`window.cume_dist`

The share of the group's rows at or before this one, from just above 0 to 1.

Also known as: _cdf_, _cumulative share_, _percentile position_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_cume_dist` |
|---|---|
| `10.0` | `0.3333333333333333` |
| `20.0` | `0.6666666666666666` |
| `5.0` | `0.5` |
| `30.0` | `1.0` |
| `15.0` | `1.0` |

### Split into equal groups

`window.ntile`

Number the rows 1 to N in order, so each number has as near an equal share of the rows as possible (quartiles, deciles).

Also known as: _ntile_, _quartile_, _decile_, _quintile_, _bucket_, _tercile_

| Setting | Type | Required | Default |
|---|---|---|---|
| Number of groups | integer | yes | `4` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_group` |
|---|---|
| `10.0` | `1` |
| `20.0` | `1` |
| `5.0` | `1` |
| `30.0` | `2` |
| `15.0` | `2` |

### Value from an earlier row

`window.lag`

The value this many rows before, within the group (empty before the first).

Also known as: _lag_, _previous row_, _prior value_, _last value before_, _shift_

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows back | integer | yes | `1` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_previous` |
|---|---|
| `10.0` | _(empty)_ |
| `20.0` | `10.0` |
| `5.0` | _(empty)_ |
| `30.0` | `20.0` |
| `15.0` | `5.0` |

### Value from a later row

`window.lead`

The value this many rows after, within the group (empty after the last).

Also known as: _lead_, _next row_, _following value_, _shift_

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows ahead | integer | yes | `1` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_next` |
|---|---|
| `10.0` | `20.0` |
| `20.0` | `30.0` |
| `5.0` | `15.0` |
| `30.0` | _(empty)_ |
| `15.0` | _(empty)_ |

### First value in the group

`window.first_value`

The group's first value, in order, on every row.

Also known as: _first value_, _opening value_, _earliest_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_first` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `10.0` |
| `5.0` | `5.0` |
| `30.0` | `10.0` |
| `15.0` | `5.0` |

### Last value in the group

`window.last_value`

The group's last value, in order, on every row.

Also known as: _last value_, _closing value_, _latest_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_last` |
|---|---|
| `10.0` | `30.0` |
| `20.0` | `30.0` |
| `5.0` | `15.0` |
| `30.0` | `30.0` |
| `15.0` | `15.0` |

### Nth value in the group

`window.nth_value`

The group's value at this position, in order, on every row (empty when the group is shorter).

Also known as: _nth value_, _second value_, _value at position_

| Setting | Type | Required | Default |
|---|---|---|---|
| Position | integer | yes | `2` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_nth` |
|---|---|
| `10.0` | `20.0` |
| `20.0` | `20.0` |
| `5.0` | `15.0` |
| `30.0` | `20.0` |
| `15.0` | `15.0` |

### Running total

`window.cumulative_sum`

Add each row's value to the total so far, within the group.

Also known as: _cumulative sum_, _running sum_, _year to date_, _cumsum_, _accumulate_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |
| Rows that tie in the order | `each in turn` / `together` | no | `each in turn` |
| | Each in turn counts tied rows one after another, as a spreadsheet does. Together gives tied rows the same answer, which a database can work out too. | | |

| `sales` | `sales_running_total` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `30.0` |
| `5.0` | `5.0` |
| `30.0` | `60.0` |
| `15.0` | `20.0` |

### Running product

`window.cumulative_product`

Multiply each row's value into the product so far.

Also known as: _cumulative product_, _compound_, _cumprod_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |
| Rows that tie in the order | `each in turn` / `together` | no | `each in turn` |
| | Each in turn counts tied rows one after another, as a spreadsheet does. Together gives tied rows the same answer, which a database can work out too. | | |

| `sales` | `sales_running_product` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `200.0` |
| `5.0` | `5.0` |
| `30.0` | `6000.0` |
| `15.0` | `75.0` |

### Running highest

`window.cumulative_max`

The highest value so far, within the group.

Also known as: _cumulative max_, _high water mark_, _peak so far_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |
| Rows that tie in the order | `each in turn` / `together` | no | `each in turn` |
| | Each in turn counts tied rows one after another, as a spreadsheet does. Together gives tied rows the same answer, which a database can work out too. | | |

| `sales` | `sales_running_max` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `20.0` |
| `5.0` | `5.0` |
| `30.0` | `30.0` |
| `15.0` | `15.0` |

### Running lowest

`window.cumulative_min`

The lowest value so far, within the group.

Also known as: _cumulative min_, _low water mark_, _lowest so far_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |
| Rows that tie in the order | `each in turn` / `together` | no | `each in turn` |
| | Each in turn counts tied rows one after another, as a spreadsheet does. Together gives tied rows the same answer, which a database can work out too. | | |

| `sales` | `sales_running_min` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `10.0` |
| `5.0` | `5.0` |
| `30.0` | `10.0` |
| `15.0` | `5.0` |

### Running count

`window.cumulative_count`

How many values so far, within the group.

Also known as: _cumulative count_, _count so far_

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |
| Rows that tie in the order | `each in turn` / `together` | no | `each in turn` |
| | Each in turn counts tied rows one after another, as a spreadsheet does. Together gives tied rows the same answer, which a database can work out too. | | |

| `sales` | `sales_running_count` |
|---|---|
| `10.0` | `1` |
| `20.0` | `2` |
| `5.0` | `1` |
| `30.0` | `3` |
| `15.0` | `2` |

### Running average

`window.running_average`

The average of the values so far, within the group.

Also known as: _cumulative average_, _running mean_, _expanding mean_, _average so far_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |
| Rows that tie in the order | `each in turn` / `together` | no | `each in turn` |
| | Each in turn counts tied rows one after another, as a spreadsheet does. Together gives tied rows the same answer, which a database can work out too. | | |

| `sales` | `sales_running_average` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `15.0` |
| `5.0` | `5.0` |
| `30.0` | `20.0` |
| `15.0` | `10.0` |

### Moving average

`window.moving_average`

The average of this row and the rows just before it.

Also known as: _rolling average_, _rolling mean_, _sma_, _trailing average_, _smooth_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows in the window | integer | yes | `3` |
| | How many rows, counting this one, the value is worked out over. | | |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_moving_average` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `15.0` |
| `5.0` | `5.0` |
| `30.0` | `25.0` |
| `15.0` | `10.0` |

### Moving total

`window.moving_sum`

The total of this row and the rows just before it.

Also known as: _rolling sum_, _rolling total_, _trailing total_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows in the window | integer | yes | `3` |
| | How many rows, counting this one, the value is worked out over. | | |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_moving_total` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `30.0` |
| `5.0` | `5.0` |
| `30.0` | `50.0` |
| `15.0` | `20.0` |

### Moving highest

`window.moving_max`

The highest of this row and the rows just before it.

Also known as: _rolling max_, _rolling highest_

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows in the window | integer | yes | `3` |
| | How many rows, counting this one, the value is worked out over. | | |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_moving_max` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `20.0` |
| `5.0` | `5.0` |
| `30.0` | `30.0` |
| `15.0` | `15.0` |

### Moving lowest

`window.moving_min`

The lowest of this row and the rows just before it.

Also known as: _rolling min_, _rolling lowest_

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows in the window | integer | yes | `3` |
| | How many rows, counting this one, the value is worked out over. | | |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_moving_min` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `10.0` |
| `5.0` | `5.0` |
| `30.0` | `20.0` |
| `15.0` | `5.0` |

### Moving standard deviation

`window.rolling_stdev`

How spread out this row and the rows just before it are (empty with only one value).

Also known as: _rolling standard deviation_, _volatility_, _rolling std_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Rows in the window | integer | yes | `3` |
| | How many rows, counting this one, the value is worked out over. | | |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_moving_stdev` |
|---|---|
| `10.0` | _(empty)_ |
| `20.0` | `7.071068` |
| `5.0` | _(empty)_ |
| `30.0` | `7.071068` |
| `15.0` | `7.071068` |

### Exponential moving average

`window.ema`

A moving average that weighs recent rows more; the span sets how quickly older rows fade.

Also known as: _ewma_, _exponentially weighted_, _smoothing_, _ema_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Span in rows | number | yes | `10` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_ema` |
|---|---|
| `10.0` | `10.0` |
| `20.0` | `16.666667` |
| `5.0` | `5.0` |
| `30.0` | `25.555556` |
| `15.0` | `11.666667` |

### Moving correlation

`window.rolling_correlation`

How closely this column moves with another over the last rows: 1 together, -1 opposite, 0 unrelated.

Also known as: _rolling correlation_, _moving correlation_, _co-movement_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| With column | column | yes | none |
| Rows in the window | integer | yes | `3` |
| | How many rows, counting this one, the value is worked out over. | | |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `a` | `a_b_correlation` |
|---|---|
| `1.0` | _(empty)_ |
| `2.0` | `1.0` |
| `3.0` | `0.981981` |
| `4.0` | `-0.5` |

### Number the sessions

`window.session`

Group events into sessions: a new session starts after a gap longer than this many minutes, counted 1, 2, 3 within each group.

Also known as: _sessionise_, _sessionize_, _visits_, _session window_, _activity gap_

| Setting | Type | Required | Default |
|---|---|---|---|
| Gap that ends a session, in minutes | number | yes | `30` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |

| `at` | `session` |
|---|---|
| `2026-01-01 09:00` | `1` |
| `2026-01-01 09:10` | `1` |
| `2026-01-01 11:00` | `2` |
| `2026-01-01 09:05` | `1` |

### Difference from the row before

`window.difference`

This row's value minus the one before it in the group (empty for the first).

Also known as: _difference_, _delta_, _change_, _diff_, _increase_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_change` |
|---|---|
| `10.0` | _(empty)_ |
| `20.0` | `10.0` |
| `5.0` | _(empty)_ |
| `30.0` | `10.0` |
| `15.0` | `10.0` |

### Percent change from the row before

`window.percent_change`

How much this row's value changed from the one before, as a share of it (0.5 is half as much again).

Also known as: _percent change_, _growth_, _pct change_, _rate of change_, _relative change_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| In the order of | columns | no | none |
| | Put each group in this order first. Leave empty to keep the order the rows are in. | | |
| Largest first | boolean | no | `False` |

| `sales` | `sales_pct_change` |
|---|---|
| `10.0` | _(empty)_ |
| `20.0` | `1.0` |
| `5.0` | _(empty)_ |
| `30.0` | `0.5` |
| `15.0` | `2.0` |

### Percent of the group's total

`window.percent_of_total`

This row's value as a percentage of its group's total.

Also known as: _percent of total_, _share of total_, _proportion_, _contribution_, _mix_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |

| `sales` | `sales_pct_of_total` |
|---|---|
| `10.0` | `16.666666666666668` |
| `20.0` | `33.333333333333336` |
| `5.0` | `25.0` |
| `30.0` | `50.0` |
| `15.0` | `75.0` |

### Scale from 0 to 1

`window.normalise`

Rescale so the group's lowest value is 0 and its highest 1 (empty when every value is the same).

Also known as: _normalise_, _normalize_, _min max scale_, _0 to 1_, _rescale to range_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |

| `sales` | `sales_scaled` |
|---|---|
| `10.0` | `0.0` |
| `20.0` | `0.5` |
| `5.0` | `0.0` |
| `30.0` | `1.0` |
| `15.0` | `1.0` |

### Standard score

`window.z_score`

How many standard deviations a value is from its group's average (a z-score).

Also known as: _z score_, _standardise_, _standardize_, _standard score_, _zscore_

Offered on **numeric** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |

| `sales` | `sales_z_score` |
|---|---|
| `10.0` | `-1.0` |
| `20.0` | `0.0` |
| `5.0` | `-0.707107` |
| `30.0` | `1.0` |
| `15.0` | `0.707107` |

### Keep the top rows of each group

`window.top_n_per_group`

Keep the rows with the highest (or lowest) values of a column within each group.

Also known as: _top n per group_, _best per group_, _highest per category_, _top 3_

| Setting | Type | Required | Default |
|---|---|---|---|
| By column | column | yes | none |
| Rows per group | integer | yes | `3` |
| Within each | columns | no | none |
| | Start again for each combination of these columns. Leave empty for one group of every row. | | |
| Smallest instead | boolean | no | `False` |
| When rows tie | `keep exactly that many` / `keep every tie` | no | `keep exactly that many` |

| `region` | `sales` |
|---|---|
| `north` | `30.0` |
| `north` | `15.0` |
