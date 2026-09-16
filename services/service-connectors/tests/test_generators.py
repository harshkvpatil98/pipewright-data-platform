"""The three generators, and the honesty rules they have to keep.

Phase 04 built one connector and a conformance suite; Phase 10 multiplies that
by a hundred. The risk is not that a generated connector fails loudly -- the
suite catches that -- but that the catalogue quietly starts claiming things.
So most of what follows is about claims: tier, availability, capabilities, and
what happens when a declaration and reality disagree.
"""

from __future__ import annotations

import pathlib
from dataclasses import replace

import pytest
import yaml

import service_connectors  # noqa: F401  -- assembles the catalogue
from service_connectors import registry
from service_connectors.adapters import REPORT
from service_connectors.adapters.dialect_sql import DialectConnector
from service_connectors.adapters.manifest_rest import ManifestConnector
from service_connectors.conformance import check_spec
from service_connectors.dialects import Dialect, all_dialects
from service_connectors.manifest import (
    MANIFEST_DIR,
    ManifestError,
    load_all,
    load_file,
    parse,
    to_spec,
)
from service_connectors.protocol import Tier
from service_connectors.stores import S3_COMPATIBLE, Store, all_stores, combinations

MINIMAL = {
    "key": "example_api",
    "label": "Example",
    "description": "Read things from Example.",
    "base_url": "https://api.example.com",
    "streams": [{"name": "things", "path": "/things", "records_path": "data"}],
}


class TestTheCatalogueIsAssembled:
    def test_all_three_generators_produced_connectors(self) -> None:
        made = REPORT.generated
        assert made["manifest"] > 80, made
        assert made["dialect"] > 40, made
        assert made["matrix"] > 10, made

    def test_the_catalogue_did_not_silently_shrink(self) -> None:
        """A floor, not a target.

        The number is here to catch a refactor that drops a generator -- which
        would otherwise look like a smaller picker nobody investigates. It is
        deliberately not set to whatever today's count happens to be, because a
        test that has to be edited every time a connector is added stops being
        read.
        """
        assert len(registry.known_types()) >= 170

    def test_every_connector_passes_conformance_unchanged(self) -> None:
        """The acceptance criterion, stated in the roadmap.

        The suite was written in Phase 04 for hand-written connectors and has
        not been relaxed: a generated connector that cannot pass it is a
        generator bug, not a reason to change the suite.
        """
        failures = {
            spec.type: check_spec(registry.get(spec.type)).failures
            for spec in registry.specs()
            if not check_spec(registry.get(spec.type)).ok
        }
        assert failures == {}

    def test_a_handwritten_connector_is_never_shadowed(self) -> None:
        # PostgreSQL is in the dialect table *and* has a hand-written adapter
        # the extraction service drives. The tested one has to win.
        assert registry.get("postgresql").spec.origin == "handwritten"
        assert any("already covers it" in note for note in REPORT.skipped)

    def test_every_type_is_unique(self) -> None:
        types = registry.known_types()
        assert len(types) == len(set(types))


class TestTiersAreHonest:
    def test_every_connector_declares_a_tier(self) -> None:
        for spec in registry.specs():
            assert isinstance(spec.tier, Tier)

    def test_the_default_is_the_weakest_claim(self) -> None:
        # A connector that forgets to say is described as unverified rather
        # than silently promoted.
        assert to_spec(parse(MINIMAL)).tier is Tier.SPEC_ONLY

    def test_a_tier_above_four_must_say_what_verified_it(self) -> None:
        with pytest.raises(ManifestError, match="does not say what verified it"):
            parse({**MINIMAL, "tier": 2})
        # And with the evidence, it is accepted.
        assert parse({**MINIMAL, "tier": 2, "verified_by": "Runs against WireMock in CI."}).tier == 2

    def test_a_dialect_cannot_claim_a_tier_without_evidence(self) -> None:
        with pytest.raises(ValueError, match="without saying what verified it"):
            Dialect(key="x", label="X", driver="sqlite", package="", builtin=True, tier=Tier.LIVE)

    def test_a_store_cannot_either(self) -> None:
        with pytest.raises(ValueError, match="without saying why"):
            Store(key="x", label="X", kind=S3_COMPATIBLE, description="d",
                  endpoint_template="https://x", tier=Tier.LIVE)

    def test_the_tier_travels_to_the_api_shape(self) -> None:
        # Workday rather than a connector `test_vendor_contracts.py` promotes:
        # this is the shape of the *unverified* claim, which is the default and
        # still describes most of the catalogue.
        rendered = registry.get("workday").spec.to_dict()
        assert rendered["tier"] == 4
        assert rendered["tier_label"] == "Unverified"
        assert rendered["verified"] is False
        assert "Never executed" in rendered["tier_explanation"]

    def test_verified_means_something_actually_ran_it(self) -> None:
        assert Tier.SPEC_ONLY.verified is False
        for tier in (Tier.LIVE, Tier.CONTAINER, Tier.RECORDED):
            assert tier.verified is True

    def test_an_unverified_read_says_so_in_its_warnings(self, monkeypatch) -> None:
        """A run whose source is Tier 4 says so in its output.

        Straight from the roadmap, and the reason the warning is attached at
        read time rather than only shown in the picker: by the time somebody is
        looking at the numbers, the picker is long gone.

        Only the network is replaced -- the connector itself runs.
        """
        import pandas as pd

        from service_connectors.adapters.rest import RestConnector
        from service_connectors.protocol import ReadResult

        monkeypatch.setattr(
            RestConnector,
            "read",
            lambda self, config, stream=None, **kwargs: ReadResult(
                dataframe=pd.DataFrame({"id": [1]}), row_count=1
            ),
        )

        connector = registry.get("workday")
        assert not connector.spec.tier.verified
        result = connector.read(
            {"auth_secret": "x", "tenant_host": "acme", "tenant_name": "acme"},
            connector.discover({})[0],
        )
        assert any("unverified" in warning.lower() for warning in result.warnings)
        assert any("Never executed" in warning for warning in result.warnings)

    def test_a_verified_read_carries_no_such_warning(self, monkeypatch) -> None:
        # The warning has to mean something, which it stops doing if it is on
        # every read regardless.
        import pandas as pd

        from service_connectors.adapters.rest import RestConnector
        from service_connectors.protocol import ReadResult

        monkeypatch.setattr(
            RestConnector,
            "read",
            lambda self, config, stream=None, **kwargs: ReadResult(
                dataframe=pd.DataFrame({"id": [1]}), row_count=1
            ),
        )
        connector = registry.get("klaviyo")
        # On the instance: `ManifestConnector` sets `spec` in `__init__`, so a
        # class attribute would be shadowed and the patch would do nothing.
        monkeypatch.setattr(
            connector,
            "spec",
            replace(connector.spec, tier=Tier.CONTAINER, verified_by="test_generators.py"),
        )
        result = connector.read({"auth_secret": "x"}, connector.discover({})[0])
        assert not any("unverified" in warning.lower() for warning in result.warnings)


class TestManifestValidation:
    def test_every_shipped_manifest_loads(self) -> None:
        """This is the build check. A malformed manifest cannot ship."""
        manifests = load_all()
        assert len(manifests) > 80
        assert len({m.key for m in manifests}) == len(manifests)

    def test_a_malformed_manifest_is_refused_with_the_reason(self) -> None:
        with pytest.raises(ManifestError, match="streams"):
            parse({**MINIMAL, "streams": []})

    def test_an_unknown_key_is_refused_rather_than_ignored(self) -> None:
        # A typo that silently does nothing is the failure this prevents: the
        # connector ships, looks fine, and paginates only the first page.
        with pytest.raises(ManifestError, match="paginaton"):
            parse({**MINIMAL, "paginaton": "cursor"})

    def test_an_unknown_type_names_the_ones_that_exist(self) -> None:
        bad = {**MINIMAL, "streams": [{"name": "t", "path": "/t", "schema": {"a": {"type": "MONEY"}}}]}
        with pytest.raises(ManifestError, match="not a type a manifest can declare"):
            parse(bad)

    def test_cursor_pagination_needs_a_path(self) -> None:
        bad = {**MINIMAL, "streams": [{"name": "t", "path": "/t", "pagination": {"kind": "cursor"}}]}
        with pytest.raises(ManifestError, match="cursor_path"):
            parse(bad)

    def test_an_auth_template_has_to_say_where_the_token_goes(self) -> None:
        with pytest.raises(ManifestError, match=r"\{token\}"):
            parse({**MINIMAL, "auth": {"kind": "api_key", "template": "Bearer"}})

    def test_an_incremental_template_has_to_say_where_the_value_goes(self) -> None:
        bad = {
            **MINIMAL,
            "streams": [{"name": "t", "path": "/t",
                         "incremental": {"cursor_field": "updated", "param": "since", "template": "x"}}],
        }
        with pytest.raises(ManifestError, match=r"\{value\}"):
            parse(bad)

    def test_two_streams_cannot_share_a_name(self) -> None:
        bad = {**MINIMAL, "streams": [{"name": "t", "path": "/a"}, {"name": "t", "path": "/b"}]}
        with pytest.raises(ManifestError, match="share a name"):
            parse(bad)

    def test_a_key_has_to_be_usable_as_an_identifier(self) -> None:
        with pytest.raises(ManifestError, match="not usable as a connector key"):
            parse({**MINIMAL, "key": "Example API"})

    def test_an_unknown_category_lists_the_real_ones(self) -> None:
        with pytest.raises(ManifestError, match="not a category"):
            parse({**MINIMAL, "category": "wibble"})

    def test_broken_yaml_names_the_file(self, tmp_path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("key: x\n  bad: indent")
        with pytest.raises(ManifestError, match="broken.yaml"):
            load_file(path)

    def test_a_non_mapping_document_is_refused(self, tmp_path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- one\n- two")
        with pytest.raises(ManifestError, match="should be a mapping"):
            load_file(path)


class TestManifestConnectors:
    def test_a_manifest_becomes_a_working_spec(self) -> None:
        spec = registry.get("klaviyo").spec
        assert spec.label == "Klaviyo"
        assert spec.origin == "manifest"
        assert "read" in spec.capabilities
        assert "auth_secret" in spec.secret_fields

    def test_a_stream_with_an_incremental_cursor_declares_the_capability(self) -> None:
        assert "incremental" in registry.get("klaviyo").spec.capabilities
        # And one without does not claim it.
        assert "incremental" not in registry.get("slack").spec.capabilities

    def test_discovery_returns_the_declared_streams(self) -> None:
        streams = registry.get("zendesk").discover({})
        assert {stream.name for stream in streams} == {"tickets", "users", "organizations"}

    def test_columns_come_from_the_manifest_where_it_declares_them(self) -> None:
        columns = registry.get("klaviyo").columns({}, registry.get("klaviyo").discover({})[0])
        names = {column.name for column in columns}
        # `attributes.email` is where the value is; `email` is what anybody
        # building a pipeline wants to type.
        assert "email" in names
        assert "attributes.email" not in names

    def test_columns_refuse_rather_than_guess_when_undeclared(self) -> None:
        from service_connectors.protocol import ConnectorError

        # A sample of an API that returns nulls for optional fields describes
        # the sample, not the endpoint -- so an undeclared schema refuses.
        connector = registry.get("ga4")
        with pytest.raises(ConnectorError, match="does not describe the columns"):
            connector.columns({}, connector.discover({})[0])

    def test_an_unknown_stream_lists_the_real_ones(self) -> None:
        from service_connectors.protocol import ConnectorError, StreamRef

        connector = registry.get("ga4")
        with pytest.raises(ConnectorError, match="Available:"):
            connector.columns({}, StreamRef(name="ghost"))

    def test_a_templated_base_url_is_filled_from_config(self) -> None:
        connector = registry.get("zendesk")
        resolved = connector._resolve({"subdomain": "acme"}, connector.discover({})[0])
        assert resolved["base_url"] == "https://acme.zendesk.com/api/v2"

    def test_a_missing_url_setting_says_which_one(self) -> None:
        from service_connectors.protocol import ConnectorError

        connector = registry.get("zendesk")
        with pytest.raises(ConnectorError, match="subdomain"):
            connector._resolve({}, connector.discover({})[0])

    def test_the_auth_template_reaches_the_request_headers(self) -> None:
        from service_connectors.adapters.rest import _headers

        connector = registry.get("klaviyo")
        resolved = connector._resolve({"auth_secret": "pk_123"}, connector.discover({})[0])
        headers = _headers(resolved)
        # Klaviyo wants its own wording, and the manifest is what supplies it.
        assert headers["Authorization"] == "Klaviyo-API-Key pk_123"

    def test_a_bearer_manifest_gets_a_bearer_header(self) -> None:
        from service_connectors.adapters.rest import _headers

        connector = registry.get("intercom")
        resolved = connector._resolve({"auth_secret": "tok"}, connector.discover({})[0])
        assert _headers(resolved)["Authorization"] == "Bearer tok"

    def test_a_query_key_manifest_puts_it_in_the_query(self) -> None:
        from service_connectors.adapters.rest import _query_params

        connector = registry.get("pipedrive")
        resolved = connector._resolve({"auth_secret": "abc"}, connector.discover({})[0])
        assert _query_params(resolved)["api_token"] == "abc"

    def test_an_incremental_cursor_becomes_a_request_parameter(self) -> None:
        connector = registry.get("klaviyo")
        stream = next(s for s in connector.discover({}) if s.name == "profiles")
        resolved = connector._resolve({"auth_secret": "x"}, stream, cursor="2026-01-01")
        assert resolved["extra_params"]["filter"] == "greater-than(updated,2026-01-01)"

    def test_a_secret_is_never_in_the_spec_defaults(self) -> None:
        for spec in registry.specs():
            for field in spec.config_fields:
                if field.kind == "secret":
                    assert field.default in (None, "")


class TestDialectGenerator:
    def test_the_table_covers_the_roadmap_s_categories(self) -> None:
        categories = {dialect.category for dialect in all_dialects()}
        assert {"database", "warehouse", "lakehouse", "timeseries"} <= categories

    def test_an_installed_driver_yields_full_capabilities(self) -> None:
        # SQLite is built into SQLAlchemy, so its capabilities are real.
        spec = DialectConnector(next(d for d in all_dialects() if d.key == "sqlite")).spec
        assert spec.available
        assert {"read", "discover", "schema"} <= spec.capabilities

    def test_a_missing_driver_narrows_to_test_only(self) -> None:
        """The Phase 04 rule, per row of the table.

        A spec that promised `read` on a database whose driver is absent is a
        promise the caller only discovers by trying.
        """
        teradata = next(d for d in all_dialects() if d.key == "teradata")
        spec = DialectConnector(teradata).spec
        assert not spec.available
        assert spec.capabilities == frozenset({"test"})
        assert "teradatasqlalchemy" in (spec.unavailable_reason or "")

    def test_an_unavailable_connector_still_says_what_to_install(self) -> None:
        result = registry.get("teradata").test({})
        assert not result.success
        assert "teradatasqlalchemy" in result.message

    def test_limit_styles_produce_the_right_sql(self) -> None:
        by_key = {d.key: d for d in all_dialects()}
        assert by_key["postgresql"].sample_sql("t", 5) == "SELECT * FROM t LIMIT 5"
        assert by_key["sqlserver"].sample_sql("t", 5) == "SELECT TOP 5 * FROM t"
        assert by_key["oracle_db"].sample_sql("t", 5) == "SELECT * FROM t FETCH FIRST 5 ROWS ONLY"

    def test_an_unknown_limit_style_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown limit style"):
            Dialect(key="x", label="X", driver="sqlite", package="", builtin=True, limit_style="wibble")

    def test_the_connection_shape_decides_the_form(self) -> None:
        by_key = {d.key: d for d in all_dialects()}
        file_fields = {f.name for f in by_key["sqlite"].config_fields()}
        assert file_fields == {"file_path"}
        server_fields = {f.name for f in by_key["mysql"].config_fields()}
        assert {"host", "port", "database", "username", "password"} <= server_fields
        account_fields = {f.name for f in by_key["snowflake"].config_fields()}
        assert {"account", "warehouse", "role"} <= account_fields

    def test_a_file_dialect_builds_a_file_url(self) -> None:
        connector = DialectConnector(next(d for d in all_dialects() if d.key == "sqlite"))
        assert str(connector._url({"file_path": "/tmp/x.db"})).endswith("/tmp/x.db")

    def test_a_missing_host_is_an_actionable_error(self) -> None:
        from service_connectors.protocol import ConnectorError

        connector = DialectConnector(next(d for d in all_dialects() if d.key == "mysql"))
        with pytest.raises(ConnectorError, match="needs a host"):
            connector._url({})


class TestDialectConnectorAgainstARealDatabase:
    """SQLite is the one database available here, so it is the one used."""

    @pytest.fixture()
    def database(self, tmp_path):
        import sqlalchemy as sa

        path = tmp_path / "warehouse.db"
        engine = sa.create_engine(f"sqlite:///{path}")
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT)"))
            connection.execute(sa.text("INSERT INTO orders VALUES (1,'eu'),(2,'us'),(3,'eu')"))
            connection.execute(sa.text("CREATE VIEW eu AS SELECT * FROM orders WHERE region='eu'"))
        engine.dispose()
        return {"file_path": str(path)}

    @pytest.fixture()
    def connector(self):
        return DialectConnector(next(d for d in all_dialects() if d.key == "sqlite"))

    def test_it_connects(self, connector, database) -> None:
        result = connector.test(database)
        assert result.success, result.message
        assert result.latency_ms is not None

    def test_it_lists_tables_and_views(self, connector, database) -> None:
        streams = connector.discover(database)
        assert {s.name for s in streams} == {"orders", "eu"}
        assert {s.kind for s in streams} == {"table", "view"}

    def test_it_reads_columns_with_the_key_marked(self, connector, database) -> None:
        columns = connector.columns(database, next(s for s in connector.discover(database) if s.name == "orders"))
        by_name = {column.name: column for column in columns}
        assert by_name["id"].primary_key
        assert not by_name["region"].primary_key

    def test_it_reads_rows(self, connector, database) -> None:
        stream = next(s for s in connector.discover(database) if s.name == "orders")
        result = connector.read(database, stream, limit=10)
        assert result.row_count == 3
        assert not result.truncated
        assert list(result.dataframe["region"]) == ["eu", "us", "eu"]

    def test_a_limit_reports_that_it_truncated(self, connector, database) -> None:
        stream = next(s for s in connector.discover(database) if s.name == "orders")
        result = connector.read(database, stream, limit=2)
        assert result.row_count == 2
        assert result.truncated

    def test_a_missing_table_is_an_actionable_error(self, connector, database) -> None:
        from service_connectors.protocol import ConnectorError, StreamRef

        with pytest.raises(ConnectorError, match="Could not read"):
            connector.read(database, StreamRef(name="ghost"), limit=1)

    def test_an_error_never_carries_the_connection_string(self, connector) -> None:
        # A URL in an error message is a password in a log.
        result = connector.test({"file_path": "/nonexistent-directory/db.sqlite"})
        assert not result.success
        assert "sqlite://" not in result.message


class TestStoreMatrix:
    def test_the_matrix_is_stores_times_formats(self) -> None:
        from service_connectors.formats import FORMATS

        assert combinations() == len(all_stores()) * len(FORMATS)
        assert combinations() > 250

    def test_an_s3_compatible_store_is_real_code(self) -> None:
        spec = registry.get("minio").spec
        assert spec.available
        assert {"read", "discover"} <= spec.capabilities

    def test_its_endpoint_is_built_from_config(self) -> None:
        connector = registry.get("cloudflare_r2")
        resolved = connector._resolved({"account_id": "abc123", "bucket": "data"})
        assert resolved["endpoint_url"] == "https://abc123.r2.cloudflarestorage.com"

    def test_a_missing_endpoint_setting_says_which_one(self) -> None:
        from service_connectors.protocol import ConnectorError

        with pytest.raises(ConnectorError, match="account_id"):
            registry.get("cloudflare_r2")._resolved({"bucket": "data"})

    def test_a_store_with_no_client_declares_only_test(self) -> None:
        # An installed SDK is not an implemented connector.
        spec = registry.get("gcs").spec
        assert not spec.available
        assert spec.capabilities == frozenset({"test"})

    def test_it_says_what_to_do_instead(self) -> None:
        result = registry.get("dropbox").test({})
        assert not result.success
        assert "no client for it yet" in result.message

    def test_every_store_offers_the_whole_format_registry(self) -> None:
        from service_connectors.formats import FORMATS

        for spec in registry.specs():
            if spec.origin != "matrix":
                continue
            options = {f.options for f in spec.config_fields if f.name == "format"}
            assert options == {tuple(entry.name for entry in FORMATS)}


class TestAddingAConnectorIsCheap:
    """The roadmap's last acceptance criterion, made checkable.

    "Adding a documented REST SaaS takes < 30 minutes end to end" is not
    something a test can time. What it can check is that the work involved is
    one file with no code in it -- which is the claim underneath.
    """

    def test_a_new_manifest_needs_no_python_at_all(self, tmp_path) -> None:
        document = {
            "key": "acme_widgets",
            "label": "Acme Widgets",
            "description": "Read widgets from Acme.",
            "base_url": "https://api.acme.test/v1",
            "auth": {"kind": "api_key", "header": "X-Acme-Key", "template": "{token}"},
            "streams": [
                {"name": "widgets", "path": "/widgets", "records_path": "data",
                 "primary_key": "id", "pagination": {"kind": "page"}}
            ],
        }
        path = tmp_path / "acme_widgets.yaml"
        path.write_text(yaml.safe_dump(document))

        connector = ManifestConnector(load_file(path))
        assert check_spec(connector).ok
        assert connector.spec.label == "Acme Widgets"
        assert [s.name for s in connector.discover({})] == ["widgets"]

        from service_connectors.adapters.rest import _headers

        resolved = connector._resolve({"auth_secret": "k"}, connector.discover({})[0])
        assert _headers(resolved)["X-Acme-Key"] == "k"

    def test_the_shipped_manifests_are_plain_yaml_a_person_can_edit(self) -> None:
        for path in sorted(MANIFEST_DIR.glob("*.yaml"))[:5]:
            document = yaml.safe_load(path.read_text())
            assert isinstance(document, dict)
            assert "!!python" not in path.read_text()


class TestTierClaimsAreAuditable:
    """`verified_by` names a test file, so a tier is a citation not an assertion.

    Without this the tier system is decoration: anybody can type `tier: 1` into
    a manifest, and the badge in the picker would say "Verified" on a connector
    nothing has ever run.
    """

    #: Every test directory in the repository. A connector can legitimately be
    #: verified by another service's tests -- SQLite is exercised end to end by
    #: `service-extraction`, which is where the code that drives it lives -- so
    #: a citation is resolved across all of them rather than one folder.
    ROOT = pathlib.Path(__file__).resolve().parents[3]

    @classmethod
    def _find(cls, filename: str) -> pathlib.Path | None:
        for path in cls.ROOT.glob(f"*/*/tests/{filename}"):
            return path
        for path in cls.ROOT.glob(f"*/*/{filename}"):
            return path
        return None

    def test_every_elevated_tier_cites_a_test_file_that_exists(self) -> None:
        missing: list[str] = []
        for spec in registry.specs():
            if not spec.tier.verified:
                continue
            assert spec.verified_by, f"{spec.type} claims tier {int(spec.tier)} with no citation"
            if self._find(spec.verified_by) is None:
                missing.append(f"{spec.type} cites {spec.verified_by}, which does not exist")
        assert missing == []

    def test_the_cited_test_actually_exercises_the_connector(self) -> None:
        """The citation has to name something the test file actually drives.

        Either the connector's type -- how the registry is asked for it -- or
        the class that implements it. A file that mentions neither is not
        evidence for anything, however plausible the reasoning was.
        """
        unmentioned: list[str] = []
        for spec in registry.specs():
            if not spec.tier.verified or not spec.verified_by:
                continue
            found = self._find(spec.verified_by)
            assert found is not None
            body = found.read_text()
            implementation = type(registry.get(spec.type)).__name__
            if spec.type not in body and implementation not in body:
                unmentioned.append(
                    f"{spec.type} cites {spec.verified_by}, which mentions neither "
                    f"'{spec.type}' nor {implementation}"
                )
        assert unmentioned == []

    def test_the_spec_itself_refuses_an_uncited_claim(self) -> None:
        from service_connectors.protocol import ConnectorSpec

        with pytest.raises(ValueError, match="does not say what verified it"):
            ConnectorSpec(
                type="wishful", label="Wishful", category="api",
                description="Claims to be verified.", tier=Tier.LIVE,
            )

    def test_the_honest_default_dominates_the_catalogue(self) -> None:
        # Not a target to game: with 190 connectors, most of them written from
        # vendor documentation, "mostly unverified" is the true statement and
        # the picker says so on every one of them.
        specs = registry.specs()
        unverified = [spec for spec in specs if not spec.tier.verified]
        assert len(unverified) > len(specs) / 2
        for spec in unverified:
            assert spec.tier is Tier.SPEC_ONLY
            assert "Never executed" in spec.tier.explanation


class TestHealthOverview:
    def test_it_counts_the_catalogue(self) -> None:
        from service_connectors.health import overview

        report = overview()
        assert report.total == len(registry.known_types())
        assert report.available <= report.total
        assert report.verified <= report.total

    def test_every_tier_appears_even_at_zero(self) -> None:
        from service_connectors.health import overview

        # A tier missing from the summary reads as "none of these exist"
        # rather than "none are at this level".
        tiers = {summary.tier for summary in overview().tiers}
        assert tiers == {1, 2, 3, 4}

    def test_it_says_what_installing_a_package_would_unlock(self) -> None:
        from service_connectors.health import overview

        report = overview()
        assert report.missing_packages
        top = report.missing_packages[0]
        assert top["unlocks"] >= 1
        # Sorted by how much each unlocks, because that is the decision being
        # made: which one package is worth installing.
        counts = [entry["unlocks"] for entry in report.missing_packages]
        assert counts == sorted(counts, reverse=True)

    def test_the_matrix_size_is_reported_not_claimed(self) -> None:
        from service_connectors.formats import FORMATS
        from service_connectors.health import overview
        from service_connectors.stores import all_stores

        report = overview()
        assert report.store_format_combinations == len(all_stores()) * len(FORMATS)
        assert report.formats == len(FORMATS)

    def test_categories_sum_to_the_total(self) -> None:
        from service_connectors.health import overview

        report = overview()
        assert sum(category.total for category in report.categories) == report.total


#: The S3-compatible stores, and a configuration that fills each one's endpoint
#: template. Declared here rather than derived from the table: a test that read
#: the template to build its own settings would pass whatever the template said.
S3_COMPATIBLE_CASES = {
    "minio": ({"endpoint_url": "http://minio.internal:9000"}, "http://minio.internal:9000"),
    "cloudflare_r2": (
        {"account_id": "abc123"},
        "https://abc123.r2.cloudflarestorage.com",
    ),
    "backblaze_b2": (
        {"region": "us-west-004"},
        "https://s3.us-west-004.backblazeb2.com",
    ),
    "digitalocean_spaces": (
        {"region": "nyc3"},
        "https://nyc3.digitaloceanspaces.com",
    ),
    "wasabi": ({"region": "eu-central-1"}, "https://s3.eu-central-1.wasabisys.com"),
    "oracle_object_storage": (
        {"namespace": "acmens", "region": "uk-london-1"},
        "https://acmens.compat.objectstorage.uk-london-1.oraclecloud.com",
    ),
    # S3 itself has no endpoint template -- boto3 knows where AWS is -- so it is
    # in this family for everything except the address.
    "s3": ({"region": "eu-west-1"}, None),
}


@pytest.mark.parametrize("store_key", sorted(S3_COMPATIBLE_CASES), ids=sorted(S3_COMPATIBLE_CASES))
class TestTheS3FamilyIsGenuinelyExercised:
    """Each store's tier claim, made true rather than argued.

    "R2 speaks the S3 API this connector is tested against" is reasoning, and
    reasoning is not a citation. What follows drives every one of these
    connector objects through the S3 code path against a stub client -- the
    endpoint each one builds, the listing, and a real read through the format
    registry. That is what makes tier 2 honest for the family rather than for
    the one member somebody happened to write a test for.

    The network is the only thing replaced. Everything above it is the shipped
    connector.
    """

    @pytest.fixture()
    def connector(self, store_key):
        return registry.get(store_key)

    @pytest.fixture()
    def stub(self, monkeypatch, connector):
        """A boto3 stand-in that records what it was asked for.

        Not a mock of the connector -- the connector runs for real. This
        replaces only the network, which is the one thing a test cannot have.
        """
        import datetime
        import io

        from service_connectors.formats import write_bytes
        import pandas as pd

        payload = write_bytes(pd.DataFrame({"id": [1, 2], "region": ["eu", "us"]}), format="csv")
        calls: dict[str, object] = {}

        class Client:
            def list_objects_v2(self, **kwargs):
                calls["list"] = kwargs
                return {
                    "Contents": [
                        {"Key": "orders/day=1/part.csv", "Size": len(payload),
                         "LastModified": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)},
                        {"Key": "orders/", "Size": 0,
                         "LastModified": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)},
                    ]
                }

            def get_object(self, **kwargs):
                calls["get"] = kwargs
                return {"Body": io.BytesIO(payload)}

            def head_bucket(self, **kwargs):
                calls["head"] = kwargs
                return {}

        def fake_client(self, config):
            calls["endpoint"] = config.get("endpoint_url")
            calls["key"] = config.get("access_key_id")
            return Client()

        # Patched on `S3Connector` itself rather than "whatever this object's
        # parent happens to be": the generated stores subclass it, and the
        # hand-written S3 connector *is* it.
        from service_connectors.adapters.files import S3Connector

        monkeypatch.setattr(S3Connector, "_client", fake_client)
        return calls

    def _config(self, store_key, **overrides):
        settings, _ = S3_COMPATIBLE_CASES[store_key]
        return {
            **settings,
            "bucket": "warehouse",
            "prefix": "orders/",
            "access_key_id": "an-access-key",
            "secret_access_key": "a-secret",
            "format": "csv",
            **overrides,
        }

    def test_the_endpoint_reaches_the_client(self, store_key, connector, stub) -> None:
        _, expected = S3_COMPATIBLE_CASES[store_key]
        connector.discover(self._config(store_key))
        assert stub["endpoint"] == expected

    def test_it_lists_objects_under_the_prefix(self, store_key, connector, stub) -> None:
        streams = connector.discover(self._config(store_key))
        assert stub["list"]["Bucket"] == "warehouse"
        assert stub["list"]["Prefix"] == "orders/"
        # A folder marker is not an object.
        assert [stream.name for stream in streams] == ["orders/day=1/part.csv"]

    def test_it_reads_rows_through_the_format_registry(self, store_key, connector, stub) -> None:
        streams = connector.discover(self._config(store_key))
        result = connector.read(self._config(store_key), streams[0], limit=10)
        assert result.row_count == 2
        assert list(result.dataframe["region"]) == ["eu", "us"]
        assert stub["get"]["Bucket"] == "warehouse"

    def test_the_credential_reaches_the_client(self, store_key, connector, stub) -> None:
        connector.discover(self._config(store_key))
        assert stub["key"] == "an-access-key"

    def test_a_verified_read_carries_no_caveat(self, store_key, connector, stub) -> None:
        """The warning has to mean something, which it stops doing if it is on
        every read regardless of tier."""
        streams = connector.discover(self._config(store_key))
        result = connector.read(self._config(store_key), streams[0], limit=10)
        unverified = any("unverified" in warning.lower() for warning in result.warnings)
        assert unverified is not connector.spec.tier.verified

    def test_a_missing_endpoint_setting_is_refused_before_any_call(
        self, store_key, connector, stub
    ) -> None:
        from service_connectors.protocol import ConnectorError

        if not S3_COMPATIBLE_CASES[store_key][0]:
            pytest.skip("this store needs no endpoint setting")
        if store_key == "s3":
            pytest.skip("boto3 knows where AWS is; there is no template to leave empty")
        with pytest.raises(ConnectorError):
            connector.discover({"bucket": "warehouse"})
        assert "list" not in stub


class TestUrlTemplatesAreSafe:
    """A config value is a *piece* of a URL, never a place to build one.

    Both of these were real: paths were not substituted at all, so GitHub asked
    for `/repos/{org}/{repo}/issues` literally; and a subdomain containing `/`
    or `#` moved the request to a host the manifest never named -- with the
    credential attached.
    """

    def test_a_path_placeholder_is_filled(self) -> None:
        connector = registry.get("github")
        stream = next(s for s in connector.discover({}) if s.name == "issues")
        resolved = connector._resolve(
            {"auth_secret": "t", "org": "acme", "repo": "web"}, stream
        )
        assert resolved["path"] == "/repos/acme/web/issues"

    def test_a_missing_path_setting_says_which_one(self) -> None:
        from service_connectors.protocol import ConnectorError

        connector = registry.get("github")
        stream = next(s for s in connector.discover({}) if s.name == "issues")
        with pytest.raises(ConnectorError, match="repo"):
            connector._resolve({"auth_secret": "t", "org": "acme"}, stream)

    @pytest.mark.parametrize(
        "hostile",
        ["evil.com/x#", "acme/../other", "acme?x=1", "acme@evil.com", "acme:8080",
         "acme com", "acme%2f", "acme\\nHost: evil"],
    )
    def test_a_value_cannot_escape_its_url_component(self, hostile: str) -> None:
        from service_connectors.protocol import ConnectorError

        connector = registry.get("zendesk")
        with pytest.raises(ConnectorError, match="cannot contain"):
            connector._resolve(
                {"auth_secret": "t", "subdomain": hostile}, connector.discover({})[0]
            )

    def test_an_ordinary_value_still_works(self) -> None:
        connector = registry.get("zendesk")
        resolved = connector._resolve(
            {"auth_secret": "t", "subdomain": "acme"}, connector.discover({})[0]
        )
        assert resolved["base_url"] == "https://acme.zendesk.com/api/v2"

    def test_the_refusal_names_the_setting_and_the_characters(self) -> None:
        from service_connectors.protocol import ConnectorError

        connector = registry.get("zendesk")
        with pytest.raises(ConnectorError) as caught:
            connector._resolve(
                {"auth_secret": "t", "subdomain": "a/b"}, connector.discover({})[0]
            )
        assert "subdomain" in str(caught.value)
        assert "'/'" in str(caught.value)

    def test_every_manifest_placeholder_has_a_config_field_to_fill_it(self) -> None:
        """A placeholder nothing can fill is a connector nobody can configure.

        It would only surface when somebody tried to use it, as an error about
        a setting that does not appear on the form.
        """
        import re

        missing: list[str] = []
        for spec in registry.specs():
            if spec.origin != "manifest":
                continue
            manifest = registry.get(spec.type).manifest
            fields = {field.name for field in spec.config_fields}
            templates = [manifest.base_url, *(stream.path for stream in manifest.streams)]
            for template in templates:
                for name in re.findall(r"\{([a-z_][a-z0-9_]*)\}", template):
                    if name not in fields:
                        missing.append(f"{spec.type}: {{{name}}} in {template!r}")
        assert missing == []


class TestTheTierCaveatCannotBeForgotten:
    """The caveat is built in one place, and every connector has to use it.

    The roadmap's rule is that a run whose source is unverified says so in its
    *output* -- the picker is long gone by the time somebody is reading the
    numbers. Three connectors used to build that sentence themselves and a
    fourth quietly did not, which is exactly how a rule like this dies.
    """

    def test_the_sentence_exists_once(self) -> None:
        from service_connectors.protocol import Tier

        spec = registry.spec_for("workday")
        assert spec.tier is Tier.SPEC_ONLY
        assert spec.tier_caveat is not None
        assert "unverified" in spec.tier_caveat.lower()

    def test_a_verified_connector_has_nothing_to_say(self) -> None:
        assert registry.spec_for("sqlite").tier_caveat is None

    def test_every_adapter_that_reads_attaches_it(self) -> None:
        """A source check, in the spirit of the web app's colour-literal test.

        A behavioural test per connector would need a stub per protocol; what
        actually goes wrong is somebody adding a `read` and not thinking about
        the tier at all, and that is visible from the source.
        """
        import pathlib

        adapters = pathlib.Path(service_connectors.__file__).parent / "adapters"
        missing = []
        for path in sorted(adapters.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "    def read(" not in source:
                continue
            # Either it attaches the caveat, or it hands the result back to a
            # base class that does -- `saas.py` is the second kind.
            if "with_tier_note" in source or "super().read(" in source:
                continue
            missing.append(path.name)
        assert missing == [], (
            f"these adapters read rows without attaching the tier caveat: {missing}. "
            "Wrap the result in protocol.with_tier_note(result, self.spec)."
        )

    def test_a_failed_test_is_not_annotated(self) -> None:
        """A failure has a reason of its own; the tier is not it."""
        from service_connectors.protocol import TestResult, with_tier_note

        failed = TestResult(success=False, message="Wrong password.")
        assert with_tier_note(failed, registry.spec_for("workday")) is failed

    def test_the_family_promoted_here_is_the_family_tested_here(self) -> None:
        """A store citing this file has to appear in the parametrised cases."""
        cited = {
            spec.type
            for spec in registry.specs()
            if spec.origin in ("matrix", "handwritten")
            and spec.category == "storage"
            and spec.verified_by == "test_generators.py"
        }
        assert cited == set(S3_COMPATIBLE_CASES)


class TestDeclaredEngines:
    """The entries this platform cannot drive, and why they are still listed.

    Omitting Cassandra would leave somebody concluding their data is out of
    reach; listing it as though it worked would be worse. The compromise is an
    entry that declares only `test`, says what would be needed, and names the
    interface this platform *can* read instead.
    """

    def test_every_declared_engine_is_in_the_catalogue(self) -> None:
        from service_connectors.datastores import all_datastores

        declared = {store.key for store in all_datastores()}
        assert declared <= set(registry.known_types())

    def test_none_of_them_claims_to_read(self) -> None:
        for spec in registry.specs():
            if spec.origin != "declared":
                continue
            assert spec.capabilities == frozenset({"test"})
            assert not spec.available
            assert not spec.supports("read")

    def test_each_one_says_what_to_use_instead(self) -> None:
        """The reason the entry earns its place at all."""
        for spec in registry.specs():
            if spec.origin != "declared":
                continue
            assert spec.unavailable_reason
            # Two sentences: what is missing, and what does work.
            assert len(spec.unavailable_reason.split(". ")) >= 2, spec.type

    def test_an_entry_with_no_alternative_is_refused(self) -> None:
        from service_connectors.datastores import DataStore

        with pytest.raises(ValueError, match="no alternative"):
            DataStore(
                key="ghost", label="Ghost", category="nosql",
                description="Nothing.", package="ghost", instead="",
            )

    def test_testing_one_reports_the_reason_rather_than_failing_obscurely(self) -> None:
        result = registry.get("cassandra").test({})
        assert not result.success
        assert "Stargate" in result.message

    def test_they_pass_the_conformance_suite_unchanged(self) -> None:
        """The roadmap's bar: every generator's output, same suite, no exceptions."""
        from service_connectors.conformance import check_spec

        for spec in registry.specs():
            if spec.origin != "declared":
                continue
            report = check_spec(registry.get(spec.type))
            assert report.ok, f"{spec.type}: {report.failures}"

    def test_the_alternative_it_offers_actually_exists(self) -> None:
        """"Use the X connector instead" has to name a connector that is here.

        This caught a real one: HBase pointed at Phoenix, which has no entry in
        the dialect table. Sending somebody to a connector that does not exist
        is worse than the gap the sentence was meant to fill.
        """
        from service_connectors.datastores import all_datastores

        known = set(registry.known_types())
        #: How each alternative reads in prose, and the connector behind it.
        NAMED = {
            "REST connector": "rest_api",
            "DynamoDB connector": "dynamodb",
            "S3 connector": "s3",
            "Hive": "hive",
            "Trino": "trino",
            "Phoenix": "phoenix",
        }
        broken: list[str] = []
        for store in all_datastores():
            for phrase, connector_type in NAMED.items():
                if phrase in store.instead and connector_type not in known:
                    broken.append(f"{store.key} points at {connector_type}, which is absent")
        assert broken == []

    def test_the_roadmap_s_named_engines_are_all_present(self) -> None:
        """Phase 10.4 lists these by name; each is reachable from the picker."""
        expected = {
            "cassandra", "scylladb", "couchbase", "redis", "arangodb", "hbase",
            "aerospike", "timestream", "hdfs",
        }
        assert expected <= set(registry.known_types())


class TestTheGuideIsGenerated:
    """`docs/adding-a-connector.md` is output, not prose somebody maintains.

    The generator's docstring claimed a test enforced this and none did, so the
    checked-in file was free to drift from the schema it describes -- which is
    exactly the failure the generator exists to prevent. This is that test.
    """

    def _render(self) -> str:
        import importlib.util
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        script = root / "scripts" / "generate-connector-guide.py"
        spec = importlib.util.spec_from_file_location("_connector_guide", script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.render()

    def test_the_checked_in_copy_matches_the_generator(self) -> None:
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        target = root / "docs" / "adding-a-connector.md"
        assert target.exists(), "the guide has not been generated"
        assert target.read_text(encoding="utf-8") == self._render(), (
            "docs/adding-a-connector.md is out of date. "
            "Run: .venv/bin/python scripts/generate-connector-guide.py"
        )

    def test_it_describes_every_way_a_connector_is_added(self) -> None:
        """A route into the catalogue that the guide never mentions is a route
        the next person will not find."""
        body = self._render()
        for origin, heading in (
            ("manifest", "write a manifest"),
            ("dialect", "dialect table"),
            ("matrix", "store table"),
            ("declared", "declare it"),
        ):
            present = any(spec.origin == origin for spec in registry.specs())
            assert present, f"no connector has origin {origin!r}"
            assert heading in body, f"the guide never explains {origin!r}"
