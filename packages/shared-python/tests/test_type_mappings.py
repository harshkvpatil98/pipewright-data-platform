"""Per-source type mappings.

The point of these is the awkward cases, not the obvious ones. `bigint -> int64`
needs no test; `tinyint(1)` meaning boolean, MySQL's DATETIME having no timezone
while its TIMESTAMP does, and SQLite's NUMERIC being an affinity rather than a
type are where data actually gets corrupted.
"""

import pytest

from shared_python.types.coercion import cast_loss, is_exact
from shared_python.types.lattice import (
    BOOLEAN,
    BYTES,
    DATE,
    FLOAT32,
    FLOAT64,
    INT16,
    INT32,
    INT64,
    INT8,
    JSON,
    PWType,
    STRING,
    UINT64,
    UINT8,
    UNKNOWN,
    UUID,
    array,
    decimal,
    string,
    timestamp,
)
from shared_python.types.mappings import get, known

POSTGRES = get("postgres")
MYSQL = get("mysql")
SQLITE = get("sqlite")
PANDAS = get("pandas")


class TestRegistry:
    def test_every_usable_connector_has_a_mapping(self) -> None:
        for name in ("postgres", "mysql", "sqlite", "pandas", "parquet"):
            assert get(name) is not None

    def test_aliases_share_one_implementation(self) -> None:
        assert get("postgresql") is get("postgres")
        assert get("mariadb") is get("mysql")

    def test_an_unknown_dialect_is_an_error_not_a_default(self) -> None:
        with pytest.raises(KeyError, match="No type mapping"):
            get("teradata")

    def test_every_mapping_states_its_quirks(self) -> None:
        for name in known():
            assert get(name).caveat, f"{name} should document what bites people"


class TestPostgres:
    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("int4", INT32), ("bigint", INT64), ("smallint", INT16),
            ("numeric(38,10)", decimal(38, 10)),
            ("numeric(10)", decimal(10, 0)),
            ("varchar(80)", string(80)),
            ("text", STRING),
            ("uuid", UUID), ("jsonb", JSON), ("bytea", BYTES),
            ("money", decimal(19, 2)),
        ],
    )
    def test_reads_declared_types(self, declared: str, expected: PWType) -> None:
        assert POSTGRES.to_pw(declared) == expected

    def test_distinguishes_zoned_from_naive_timestamps(self) -> None:
        # The distinction the whole lattice exists to preserve.
        assert POSTGRES.to_pw("timestamptz").tz_aware
        assert not POSTGRES.to_pw("timestamp").tz_aware

    def test_reads_array_types(self) -> None:
        assert POSTGRES.to_pw("int4[]") == array(INT32)

    def test_unsigned_64_bit_becomes_an_exact_decimal(self) -> None:
        # Postgres has no unsigned 64-bit integer; numeric(20,0) is the only
        # type that holds the whole range without overflow.
        assert POSTGRES.from_pw(UINT64) == "numeric(20,0)"
        assert is_exact(UINT64, POSTGRES.to_pw("numeric(20,0)"))

    def test_round_trips_the_types_it_declares(self) -> None:
        for type_ in (INT32, INT64, FLOAT64, decimal(18, 4), string(80), STRING,
                      DATE, UUID, JSON, BYTES, timestamp(tz_aware=True),
                      timestamp(tz_aware=False), array(INT32)):
            emitted = POSTGRES.from_pw(type_)
            recovered = POSTGRES.to_pw(emitted)
            assert is_exact(type_, recovered), f"{type_} -> {emitted} -> {recovered}"


class TestMySQL:
    def test_tinyint_1_is_the_boolean_everyone_uses(self) -> None:
        # MySQL has no boolean; every ORM treats tinyint(1) as one, and reading
        # it as an 8-bit integer produces "1"/"0" in reports instead of yes/no.
        assert MYSQL.to_pw("tinyint(1)") == BOOLEAN
        assert MYSQL.to_pw("tinyint(4)") == INT8

    def test_datetime_has_no_timezone_but_timestamp_does(self) -> None:
        # This asymmetry is the single most common source of shifted reports
        # when moving data out of MySQL.
        assert not MYSQL.to_pw("datetime").tz_aware
        assert MYSQL.to_pw("timestamp").tz_aware

    def test_reads_unsigned_integers(self) -> None:
        assert MYSQL.to_pw("bigint unsigned") == UINT64
        assert MYSQL.to_pw("tinyint unsigned") == UINT8

    def test_enum_and_set_are_text(self) -> None:
        assert MYSQL.to_pw("enum('a','b')") == STRING

    def test_declares_what_it_cannot_store(self) -> None:
        # Arrays and UUIDs have no native type; a pipeline targeting MySQL
        # should learn that while it is being built.
        assert not MYSQL.supports(array(INT64))
        assert not MYSQL.supports(UUID)
        assert MYSQL.supports(decimal(18, 2))


class TestSQLite:
    def test_declared_numeric_is_reported_as_unknown(self) -> None:
        # SQLite has affinity, not types. Reporting NUMERIC as DECIMAL would
        # promise an exactness it does not keep.
        assert SQLITE.to_pw("numeric") == UNKNOWN

    def test_decimal_is_stored_as_text_not_numeric(self) -> None:
        # NUMERIC affinity converts anything that looks numeric to a float.
        # This is the same failure that turned all-digit UUIDs into floats.
        assert SQLITE.from_pw(decimal(18, 2)) == "TEXT"

    def test_caveat_names_the_affinity_trap(self) -> None:
        assert "affinity" in SQLITE.caveat.lower()

    def test_every_integer_width_collapses_to_one_type(self) -> None:
        assert SQLITE.from_pw(INT8) == SQLITE.from_pw(INT64) == "INTEGER"


class TestPandas:
    def test_object_is_unknown_rather_than_string(self) -> None:
        # An object column holds anything. Calling it a string is how one bad
        # row turns a numeric column into text for all downstream time.
        assert PANDAS.to_pw("object") == UNKNOWN

    def test_reads_timezone_aware_dtypes(self) -> None:
        aware = PANDAS.to_pw("datetime64[ns, Europe/London]")
        assert aware.tz_aware and aware.time_precision == 9
        assert not PANDAS.to_pw("datetime64[ns]").tz_aware

    def test_nullable_integers_use_the_extension_dtype(self) -> None:
        # numpy int64 cannot hold NA and silently promotes the whole column to
        # float the moment one appears.
        assert PANDAS.from_pw(INT64) == "Int64"
        assert PANDAS.from_pw(INT64.with_nullable(False)) == "int64"

    def test_decimal_stays_an_object_column(self) -> None:
        # float64 would defeat the purpose of having a DECIMAL type at all.
        assert PANDAS.from_pw(decimal(18, 2)) == "object"


class TestUnrecognisedTypes:
    @pytest.mark.parametrize("mapping", [POSTGRES, MYSQL, SQLITE, PANDAS])
    def test_an_unknown_source_type_is_never_guessed(self, mapping) -> None:
        # Guessing produces a type the pipeline will trust and the data will
        # not honour. UNKNOWN is the honest answer.
        assert mapping.to_pw("some_extension_type") == UNKNOWN


class TestCrossSourceJourneys:
    """The journeys that actually corrupt data in production."""

    def test_postgres_numeric_survives_a_trip_through_pandas(self) -> None:
        source = POSTGRES.to_pw("numeric(38,10)")
        assert source == decimal(38, 10)
        # pandas holds it as object (Decimal), not float64.
        assert PANDAS.from_pw(source) == "object"

    def test_narrowing_a_decimal_between_warehouses_is_reported(self) -> None:
        # The roadmap's worked example: NUMERIC(38,10) into a destination that
        # only keeps 9 decimal places.
        source = POSTGRES.to_pw("numeric(38,10)")
        target = decimal(38, 9)
        losses = cast_loss(source, target)
        assert losses and losses[0].kind == "precision"
        assert "1 will be rounded away" in losses[0].detail

    def test_mysql_datetime_into_postgres_timestamptz_is_blocking(self) -> None:
        # Naive on one side, zoned on the other: there is no offset to use, and
        # assuming the server's local zone is how reports drift by hours.
        source = MYSQL.to_pw("datetime")
        target = POSTGRES.to_pw("timestamptz")
        losses = cast_loss(source, target)
        assert any(loss.severity == "blocking" for loss in losses)
        assert any(loss.kind == "timezone" for loss in losses)

    def test_mysql_datetime_into_postgres_timestamp_is_fine(self) -> None:
        # Both naive: nothing is being assumed, so nothing is lost.
        source = MYSQL.to_pw("datetime")
        target = POSTGRES.to_pw("timestamp")
        assert not any(loss.severity == "blocking" for loss in cast_loss(source, target))

    def test_uuid_into_sqlite_does_not_land_in_a_numeric_column(self) -> None:
        # The historical bug: an all-digit UUID in a NUMERIC-affinity column
        # became a float. TEXT has no affinity conversion.
        assert SQLITE.from_pw(UUID) == "TEXT"

    def test_postgres_array_into_mysql_is_declared_unsupported(self) -> None:
        source = POSTGRES.to_pw("int4[]")
        assert not MYSQL.supports(source)


class TestEveryTypeThroughEveryDialect:
    """Exhaustive coverage of `from_pw`.

    A branch nobody has exercised is a branch nobody has checked, and it will
    be wrong the first time a column of that type appears.
    """

    ALL_TYPES = [
        BOOLEAN, INT8, INT16, INT32, INT64, UINT8, UINT64,
        FLOAT32, FLOAT64, decimal(18, 4), decimal(38, 10),
        STRING, string(80), BYTES, DATE, UUID, JSON,
        timestamp(tz_aware=True), timestamp(tz_aware=False),
        array(INT64), UNKNOWN,
    ]

    @pytest.mark.parametrize("dialect", ["postgres", "mysql", "sqlite", "pandas"])
    @pytest.mark.parametrize("type_", ALL_TYPES, ids=str)
    def test_every_type_emits_something(self, dialect: str, type_: PWType) -> None:
        emitted = get(dialect).from_pw(type_)
        assert isinstance(emitted, str) and emitted, (
            f"{dialect} produced nothing for {type_}"
        )

    @pytest.mark.parametrize("dialect", ["postgres", "mysql", "sqlite", "pandas"])
    def test_unsupported_types_are_declared_not_silently_mangled(self, dialect: str) -> None:
        mapping = get(dialect)
        for type_ in self.ALL_TYPES:
            if not mapping.supports(type_):
                # It must still emit *something* -- a column has to land
                # somewhere -- but `supports` is what warns the pipeline first.
                assert mapping.from_pw(type_)

    @pytest.mark.parametrize("dialect", ["postgres", "mysql"])
    def test_sql_dialects_round_trip_their_own_scalar_output(self, dialect: str) -> None:
        mapping = get(dialect)
        for type_ in [INT16, INT32, INT64, FLOAT32, FLOAT64, decimal(18, 4),
                      string(80), DATE, timestamp(tz_aware=True),
                      timestamp(tz_aware=False)]:
            if not mapping.supports(type_):
                continue
            recovered = mapping.to_pw(mapping.from_pw(type_))
            assert recovered.kind is type_.kind, (
                f"{dialect}: {type_} -> {mapping.from_pw(type_)} -> {recovered}"
            )

    def test_timezone_awareness_survives_a_round_trip(self) -> None:
        # The single most important property to preserve; losing it is silent.
        for dialect in ("postgres", "mysql"):
            mapping = get(dialect)
            for aware in (True, False):
                original = timestamp(tz_aware=aware)
                recovered = mapping.to_pw(mapping.from_pw(original))
                assert recovered.tz_aware is aware, f"{dialect} lost tz_aware={aware}"

    def test_decimal_precision_survives_a_round_trip(self) -> None:
        for dialect in ("postgres", "mysql"):
            mapping = get(dialect)
            original = decimal(38, 10)
            recovered = mapping.to_pw(mapping.from_pw(original))
            assert (recovered.precision, recovered.scale) == (38, 10), dialect
