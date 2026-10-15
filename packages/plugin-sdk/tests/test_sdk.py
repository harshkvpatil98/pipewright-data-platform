"""The plugin SDK's own checks (X1): what passes, and what is refused and why."""

from __future__ import annotations

import dataclasses

import pytest

from pipewright_plugin_sdk import (
    SDK_VERSION,
    ChartType,
    Connector,
    Example,
    Field,
    Function,
    Mark,
    Param,
    Plugin,
    RestManifest,
    Tool,
)
from pipewright_plugin_sdk.checks import check, load, load_folder, same
from pipewright_plugin_sdk.skeleton import write_skeleton


def _tool(**overrides) -> Tool:
    base = dict(name="shout", title="Shout", summary="Capitals and an exclamation mark.",
                transform=lambda value, settings: f"{str(value).upper()}{settings.get('mark') or '!'}",
                example=Example(values=("hello", None), expect=("HELLO!", None)), accepts="text", returns="text",
                params=(Param("mark", "Mark", required=False, default="!"),))
    return Tool(**{**base, **overrides})


def _plugin(**overrides) -> Plugin:
    base = dict(name="acme", version="1.0.0", publisher="Acme Ltd", description="Acme's everyday tools.",
                tools=(_tool(),))
    return Plugin(**{**base, **overrides})


def _failing(report) -> list[str]:
    return [f"{item.subject}: {item.name}" for item in report.failures]


def test_a_plugin_written_to_the_sdk_passes() -> None:
    report = check(_plugin())
    assert report.ok, _failing(report)
    assert report.to_dict()["ok"] is True


def test_the_skeleton_passes_its_own_checks(tmp_path) -> None:
    root = write_skeleton(tmp_path, "starter", publisher="Ana")
    plugin = load_folder(root)
    report = check(plugin)
    assert report.ok, _failing(report)
    assert {kind for kind, _, _ in plugin.contributions()} == {"tool", "function", "chart type", "connector"}
    assert load(str(root)).name == "starter"
    assert (root / "pyproject.toml").read_text().count('starter = "starter_plugin:plugin"') == 1


def test_the_skeleton_will_not_write_over_a_plugin(tmp_path) -> None:
    write_skeleton(tmp_path, "starter")
    with pytest.raises(ValueError, match="already exists"):
        write_skeleton(tmp_path, "starter")
    with pytest.raises(ValueError, match="not a plugin name"):
        write_skeleton(tmp_path, "Not a name")


def test_another_sdk_version_is_refused() -> None:
    report = check(_plugin(sdk=SDK_VERSION + 1))
    assert not report.ok and "written for SDK 2" in report.failures[0].detail


def test_an_example_that_is_wrong_is_found() -> None:
    wrong = _tool(example=Example(values=("hello",), expect=("hello!",)))
    report = check(_plugin(tools=(wrong,)))
    [failure] = report.failures
    assert failure.name == "its example gives what it says" and "'hello' gave 'HELLO!', not 'hello!'" in failure.detail


def test_a_tool_that_raises_is_found_not_raised() -> None:
    def broken(value, settings):
        raise RuntimeError("nope")

    report = check(_plugin(tools=(_tool(transform=broken),)))
    assert any("RuntimeError: nope" in item.detail for item in report.failures)


def test_names_settings_and_sentences_are_checked() -> None:
    bad = _tool(name="Shout!", summary="no full stop", params=(Param("column", "Column"),
                                                                  Param("kind", "Kind", kind="select")))
    report = check(_plugin(name="Acme Tools", version="one", tools=(bad,)))
    failing = _failing(report)
    assert "plugin: has a name of lowercase letters, digits and _" in failing
    assert "plugin: has a version such as 1.0.0" in failing
    assert any("says what it does in a sentence" in name for name in failing)
    assert any("none column, into or tool" in name for name in failing)
    assert any("setting kind has choices" in name for name in failing)


def test_a_function_is_checked_on_its_examples() -> None:
    good = Function(name="acme_double", summary="Twice the number.", implementation=lambda x: x * 2,
                    returns="number", examples=(((2,), 4), ((1.5,), 3.0)))
    wrong = dataclasses.replace(good, name="acme_wrong", examples=(((2,), 5),))
    report = check(_plugin(tools=(), functions=(good, wrong)))
    assert [item.subject for item in report.failures] == ["function ACME_WRONG"]


def test_a_chart_type_draws_what_it_has() -> None:
    good = ChartType(name="lollipop", label="Lollipop", description="A stem and a dot for each category.",
                     marks=(Mark("rule"), Mark("point")))
    bad = ChartType(name="spiral", label="Spiral", description="Not a chart.", marks=(Mark("bar", series=3),),
                    measures=(1, 2))
    report = check(_plugin(tools=(), chart_types=(good, bad)))
    assert {item.subject for item in report.failures} == {"chart type acme_spiral"}


class _Api(Connector):
    name = "api"
    label = "Acme API"
    description = "Acme's own records, read over HTTPS."
    fields = (Field("token", "Token", kind="secret"),)

    def test(self, config):
        return bool(config.get("token")), "Reached Acme." if config.get("token") else "Give a token."

    def streams(self, config):
        return ["customers"]

    def read(self, config, stream, limit):
        return [{"id": 1}]


class _ReadsBlind(Connector):
    name = "blind"
    label = "Blind"
    description = "Reads without saying what it can read."

    def test(self, config):
        return True, "Fine."

    def read(self, config, stream, limit):
        return []


def test_a_connector_is_checked_for_what_it_can_do() -> None:
    report = check(_plugin(tools=(), connectors=(_Api(), _ReadsBlind())))
    assert [item.name for item in report.failures] == ["lists what it reads if it reads"]
    assert _Api.can("read") and not Connector.can("read")


def test_a_manifest_is_named_after_its_plugin_and_claims_no_tier() -> None:
    manifest = {"key": "status", "label": "Status", "description": "A status page's components.", "tier": 2}
    report = check(_plugin(tools=(), connectors=(RestManifest(manifest),)))
    assert {item.name for item in report.failures} == {"is named after its plugin", "claims no tier it has not earned here"}


def test_a_plugin_that_adds_nothing_twice() -> None:
    report = check(_plugin(tools=(_tool(), _tool())))
    assert any(item.name == "adds nothing twice" for item in report.failures)
    assert not check(_plugin(tools=())).ok


@pytest.mark.parametrize(("expected", "actual", "agrees"), [
    (1, 1.0, True), (0.1 + 0.2, 0.3, True), (None, None, True), (None, 0, False), (True, 1, False),
    ("2026-01-01", "2026-01-01 00:00:00", False), (float("nan"), float("nan"), False),
])
def test_values_compare_as_a_reader_would(expected, actual, agrees) -> None:
    assert same(expected, actual) is agrees


def test_two_folders_with_one_package_name_load_their_own(tmp_path) -> None:
    """An edited plugin, or another folder's package of the same name, is read afresh, not from an earlier load."""
    first = write_skeleton(tmp_path / "a", "starter")
    second = write_skeleton(tmp_path / "b", "starter", publisher="Bo")
    assert load_folder(first).publisher == "Your name"
    assert load_folder(second).publisher == "Bo"
    source = first / "starter_plugin" / "__init__.py"
    source.write_text(source.read_text().replace('version="0.1.0"', 'version="0.2.0"'))
    assert load_folder(first).version == "0.2.0"
