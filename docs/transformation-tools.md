# Transformation tools

167 tools across 10 categories. Every one compiles to the
relational IR, so every one gets type inference, column lineage and
pushdown without a second implementation.

Generated from the tool registry. Every example below is executed by the
test suite, so this file cannot describe behaviour the code does not have.

## Contents

- [Cleansing](#cleansing) (15)
- [Columns](#columns) (7)
- [Type & conversion](#type--conversion) (10)
- [Date & time](#date--time) (33)
- [Encoding & privacy](#encoding--privacy) (14)
- [Missing data](#missing-data) (6)
- [Numeric](#numeric) (23)
- [Rows](#rows) (7)
- [Text](#text) (43)
- [Validation](#validation) (9)


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

Also known as: _zip_, _postcode_

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


## Columns

### Move columns

`columns.move`

Move columns to the start or the end, leaving the rest in order.

Also known as: _reorder_, _move to front_, _move to end_, _arrange_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns | columns | yes | — |
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
| Columns to keep | columns | yes | — |

| `a` | `columns` |
|---|---|
| `1` | `a,c` |

### Drop columns

`columns.drop`

Remove one or more columns.

Also known as: _remove columns_, _delete columns_

| Setting | Type | Required | Default |
|---|---|---|---|
| Columns to drop | columns | yes | — |

| `a` | `columns` |
|---|---|
| `1` | `a` |

### Duplicate a column

`columns.duplicate`

Add a copy, so the original survives an experiment.

Also known as: _copy column_, _clone_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | — |

| `a` | `a_copy` |
|---|---|
| `1` | `1` |

### Rename a column

`columns.rename`

Give a column a new name.

Also known as: _rename_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | — |
| New name | text | yes | — |

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
| Find | text | no | — |
| Replace with | text | no | — |

| `Order ID` | `columns` |
|---|---|
| `1` | `order_id,customer_name` |


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
| Path | text | yes | — |

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


## Date & time

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
| Other date column | column | yes | — |

| `when` | `when` |
|---|---|
| `2026-08-01` | `7` |

### Months until

`date.months_between`

Months until another date column, counted from this one.

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | — |

| `when` | `when` |
|---|---|
| `2026-08-01` | `0` |

### Years until

`date.years_between`

Years until another date column, counted from this one.

Offered on **temporal** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Other date column | column | yes | — |

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
| Other date column | column | yes | — |

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
| Other date column | column | yes | — |

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
| Key | text | yes | — |

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
| Salt | text | yes | — |
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


## Missing data

### Fill blanks with a value

`null.fill_constant`

Replace nulls with a fixed value.

Also known as: _fill na_, _replace null_, _default_

| Setting | Type | Required | Default |
|---|---|---|---|
| Value | text | yes | — |

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
| Other column | column | yes | — |

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
| Also treat as missing | text | no | — |
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


## Rows

### Keep or drop matching rows

`rows.filter`

Keep only the rows a test matches, or drop them.

Also known as: _filter_, _where_, _exclude_, _remove rows_

| Setting | Type | Required | Default |
|---|---|---|---|
| Column | column | yes | — |
| Test | `equals` / `not equals` / `greater than` / `at least` / `less than` / `at most` / `contains` / `starts with` / `ends with` / `is empty` / `is not empty` | yes | `equals` |
| Value | text | no | — |
| Then | `keep` / `exclude` | yes | `keep` |

| `region` | `region` |
|---|---|
| `eu` | `eu` |

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
| Sort by | columns | yes | — |
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
| Compare only these columns | columns | no | `[]` |
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
| Look at these columns | columns | no | `[]` |
| | Leave empty to look at every column. | | |
| Drop when | `all` / `any` | yes | `all` |
| | 'all': every named column is blank. 'any': at least one is. | | |

| `a` | `a` |
|---|---|
| `x` | `x` |
| _(empty)_ | `z` |


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

### lowercase

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
| Suffix | text | no | — |

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
| Marker | text | yes | — |

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
| Marker | text | yes | — |

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
| Opening marker | text | yes | — |
| Closing marker | text | yes | — |

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
| Pattern | text | yes | — |

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
| Pattern | text | yes | — |
| Replacement | text | no | — |

| `value` | `value` |
|---|---|
| `a1b2` | `ab` |

### Count pattern matches

`text.regex_count`

How many times a regular expression matches.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Pattern | text | yes | — |

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
| Find | text | yes | — |
| Replace with | text | no | — |

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
| Text to find | text | yes | — |

| `value` | `value` |
|---|---|
| `abcabc` | `2` |

### Count occurrences

`text.count_occurrences`

How many times a piece of text appears.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| Text to count | text | yes | — |

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
| Characters | text | yes | — |

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
| Characters to keep | text | yes | — |

| `value` | `value` |
|---|---|
| `+1 (555) 123` | `1555123` |

### Swap characters

`text.translate`

Replace characters one for one, like tr.

Offered on **textual** columns.

| Setting | Type | Required | Default |
|---|---|---|---|
| From | text | yes | — |
| To | text | yes | — |

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
| Prefix | text | yes | — |

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
| Suffix | text | yes | — |

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
| Text | text | yes | — |

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
| Other columns | columns | yes | — |
| Separator | text | no | ` ` |

| `first` | `first` |
|---|---|
| `Ada` | `Ada Lovelace` |
| `Alan` | `Alan` |


## Validation

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
| Pattern | text | yes | — |

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
| Allowed values | list | yes | — |
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
| Check column | column | yes | — |
| | A true/false column produced by one of the checks above. | | |
| Keep | `passes` / `failures` | yes | `passes` |

| `ok` | `id` |
|---|---|
| `True` | `2` |
| `False` | `3` |
