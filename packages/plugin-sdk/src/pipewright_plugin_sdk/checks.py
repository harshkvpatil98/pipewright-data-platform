"""The checks a plugin passes before anything of it is used (X1).

These are the checks that need no server: what is declared, and whether the
examples come out as they say. ``pipewright plugin check`` runs them; a
server runs them too, then its own suites (the connector conformance suite,
the tool library's structural tests, the function catalogue's and the chart
validator's checks) on what the plugin adds, and refuses the whole plugin
when any check fails.
"""

from __future__ import annotations

import datetime as _dt
import importlib
import importlib.util
import math
import pathlib
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pipewright_plugin_sdk import (
    CONNECTOR_CATEGORIES,
    NAME,
    SDK_VERSION,
    ChartType,
    Connector,
    Function,
    Plugin,
    RestManifest,
    Tool,
)

VERSION = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$")
PARAM_KINDS = ("text", "number", "integer", "boolean", "select")
ACCEPTS = ("any", "text", "number", "date", "boolean")
VALUE_TYPES = ("text", "number", "integer", "boolean", "date", "timestamp")
MARK_KINDS = ("bar", "line", "point", "area", "rule", "text")
FIELD_KINDS = ("string", "secret", "number", "boolean", "select", "text")
#: How many dimensions and measures a chart can take at all.
MAX_DIMENSIONS, MAX_MEASURES = 2, 6


@dataclass
class Check:
    subject: str
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class Report:
    plugin: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]

    def expect(self, subject: str, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(subject, name, bool(passed), "" if passed else detail))
        return bool(passed)

    def run(self, subject: str, name: str, attempt: Callable[[], str | None]) -> bool:
        """A check that passes unless ``attempt`` returns what is wrong, or raises."""
        try:
            problem = attempt()
        except Exception as exc:  # noqa: BLE001 - a plugin's own code failing is the finding
            problem = f"{type(exc).__name__}: {exc}"
        return self.expect(subject, name, problem is None, problem or "")

    def to_dict(self) -> dict[str, Any]:
        return {"plugin": self.plugin, "ok": self.ok, "checks": [check.to_dict() for check in self.checks]}


# ------------------------------------------------------------------ loading


def load_folder(path: str | pathlib.Path) -> Plugin:
    """The plugin a folder's ``plugin.py`` defines as ``plugin``."""
    folder = pathlib.Path(path).resolve()
    source = folder / "plugin.py"
    if not source.is_file():
        raise ValueError(f"{folder} has no plugin.py.")
    module_name = f"pipewright_folder_plugin_{abs(hash(str(folder)))}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ValueError(f"{source} cannot be imported.")
    module = importlib.util.module_from_spec(spec)
    # The folder's own modules and packages are read from it, fresh: an edited
    # plugin, or another folder whose package has the same name, must not be
    # answered by what an earlier load left in sys.modules.
    own = {child.stem for child in folder.iterdir()
           if (child.suffix == ".py" and child.name != "plugin.py") or (child / "__init__.py").is_file()}
    for cached in [name for name in sys.modules if name.split(".")[0] in own]:
        del sys.modules[cached]
    sys.path.insert(0, str(folder))
    # No compiled copies are written into someone's plugin folder; one written
    # there would also answer for an edit made in the same second.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
        sys.path.remove(str(folder))
    found = getattr(module, "plugin", None)
    if not isinstance(found, Plugin):
        raise ValueError(f"{source} does not define plugin = Plugin(...).")
    return found


def load_object(reference: str) -> Plugin:
    """The plugin at ``module:attribute``, as an entry point names it."""
    module_name, _, attribute = reference.partition(":")
    found = getattr(importlib.import_module(module_name), attribute or "plugin", None)
    if not isinstance(found, Plugin):
        raise ValueError(f"{reference} is not a Plugin.")
    return found


def load(target: str) -> Plugin:
    """A folder, or ``module:attribute``."""
    if pathlib.Path(target).is_dir():
        return load_folder(target)
    return load_object(target)


# ------------------------------------------------------------------ values


def same(expected: Any, actual: Any) -> bool:
    """Equal the way a person reading the example would read them."""
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        # True and 1 are equal in Python, not to a reader: a yes-or-no answer is one.
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if isinstance(actual, float) and math.isnan(actual):
            return False
        return round(float(expected), 6) == round(float(actual), 6)
    if isinstance(expected, (_dt.date, _dt.datetime)) or isinstance(actual, (_dt.date, _dt.datetime)):
        return str(expected)[:19] == str(actual)[:19]
    return str(expected) == str(actual)


# ------------------------------------------------------------------ the checks


def check(plugin: Plugin) -> Report:
    report = Report(plugin=getattr(plugin, "name", "?"))
    subject = "plugin"
    if not report.expect(subject, "is a Plugin", isinstance(plugin, Plugin), "plugin is not a Plugin(...)."):
        return report
    report.expect(subject, "was written for this SDK", plugin.sdk == SDK_VERSION,
                  f"It was written for SDK {plugin.sdk}; this is SDK {SDK_VERSION}.")
    report.expect(subject, "has a name of lowercase letters, digits and _", bool(NAME.match(plugin.name)),
                  f"{plugin.name!r} is not a name such as acme or acme_tools.")
    report.expect(subject, "has a version such as 1.0.0", bool(VERSION.match(plugin.version)),
                  f"{plugin.version!r} is not a version such as 1.0.0.")
    report.expect(subject, "names its publisher", bool(plugin.publisher.strip()), "Say who publishes it.")
    report.expect(subject, "says what it is for", _sentence(plugin.description),
                  "Describe it in a sentence ending in a full stop.")
    report.expect(subject, "adds something", bool(plugin.contributions()),
                  "It adds no tool, function, chart type or connector.")
    names = [name for _, name, _ in plugin.contributions()]
    repeated = sorted({name for name in names if names.count(name) > 1})
    report.expect(subject, "adds nothing twice", not repeated, f"Two things are called {', '.join(repeated)}.")
    for tool in plugin.tools:
        _check_tool(report, plugin, tool)
    for function in plugin.functions:
        _check_function(report, function)
    for chart in plugin.chart_types:
        _check_chart(report, plugin, chart)
    for connector in plugin.connectors:
        if isinstance(connector, RestManifest):
            _check_manifest(report, plugin, connector)
        else:
            _check_connector(report, plugin, connector)
    return report


def _sentence(text: str) -> bool:
    return bool(text and text.strip() and text.strip()[0].isupper() and text.strip().endswith("."))


def _check_tool(report: Report, plugin: Plugin, tool: Tool) -> None:
    subject = f"tool {plugin.name}.{getattr(tool, 'name', '?')}"
    if not report.expect(subject, "is a Tool", isinstance(tool, Tool), "Declare it as Tool(...)."):
        return
    report.expect(subject, "has a name of lowercase letters, digits and _", bool(NAME.match(tool.name)),
                  f"{tool.name!r} is not a name such as reverse_words.")
    report.expect(subject, "has a title", bool(tool.title.strip()), "Give it a title.")
    report.expect(subject, "says what it does in a sentence", _sentence(tool.summary),
                  "The summary is a sentence ending in a full stop.")
    report.expect(subject, "says what it works on", tool.accepts in ACCEPTS,
                  f"accepts is one of {', '.join(ACCEPTS)}.")
    report.expect(subject, "says what it gives", tool.returns in (*VALUE_TYPES, "same"),
                  f"returns is one of {', '.join(VALUE_TYPES)} or same.")
    report.expect(subject, "transforms with a function", callable(tool.transform), "transform is not callable.")
    keys = [param.key for param in tool.params]
    reserved = {"column", "into", "tool"} & set(keys)
    report.expect(subject, "names each setting once, and none column, into or tool",
                  len(keys) == len(set(keys)) and not reserved, "A setting's key is repeated or reserved.")
    for param in tool.params:
        report.expect(subject, f"setting {param.key} is described",
                      bool(NAME.match(param.key)) and bool(param.label.strip()) and param.kind in PARAM_KINDS,
                      f"{param.key!r} needs a key of lowercase letters, a label and a kind of "
                      f"{', '.join(PARAM_KINDS)}.")
        if param.kind == "select":
            report.expect(subject, f"setting {param.key} has choices",
                          bool(param.options) and (param.default is None or param.default in param.options),
                          "A choice needs options, and its default among them.")
    example = tool.example
    unknown = sorted(set(example.params) - set(keys))
    missing = sorted(p.key for p in tool.params if p.required and p.default is None and p.key not in example.params)
    report.expect(subject, "its example gives every setting it needs", not unknown and not missing,
                  f"The example's settings: unknown {unknown}, missing {missing}.")
    report.expect(subject, "its example has as many answers as values",
                  len(example.values) == len(example.expect) and len(example.values) > 0,
                  "Give the example values and an answer for each.")
    if unknown or missing or not callable(tool.transform):
        return
    settings = {**{p.key: p.default for p in tool.params}, **dict(example.params)}

    def example_runs() -> str | None:
        got = [None if value is None else tool.transform(value, settings) for value in example.values]
        wrong = [(v, e, g) for v, e, g in zip(example.values, example.expect, got) if not same(e, g)]
        return None if not wrong else "; ".join(f"{v!r} gave {g!r}, not {e!r}" for v, e, g in wrong[:3])

    report.run(subject, "its example gives what it says", example_runs)


def _check_function(report: Report, function: Function) -> None:
    subject = f"function {str(getattr(function, 'name', '?')).upper()}"
    if not report.expect(subject, "is a Function", isinstance(function, Function), "Declare it as Function(...)."):
        return
    report.expect(subject, "has a name of lowercase letters, digits and _", bool(NAME.match(function.name)),
                  f"{function.name!r} is not a name such as acme_score.")
    report.expect(subject, "says what it does in a sentence", _sentence(function.summary),
                  "The summary is a sentence ending in a full stop.")
    report.expect(subject, "says what it gives", function.returns in VALUE_TYPES,
                  f"returns is one of {', '.join(VALUE_TYPES)}.")
    report.expect(subject, "takes 1 to 10 arguments",
                  1 <= function.min_args <= function.max_args <= 10,
                  "min_args and max_args are 1 to 10, the smaller first: a function works on its arguments.")
    report.expect(subject, "has examples", bool(function.examples), "Give at least one (arguments, answer).")
    for arguments, answer in function.examples:
        def example_runs(arguments=arguments, answer=answer) -> str | None:
            if not function.min_args <= len(arguments) <= function.max_args:
                return f"{arguments!r} is the wrong number of arguments."
            got = function.implementation(*arguments)
            return None if same(answer, got) else f"{arguments!r} gave {got!r}, not {answer!r}"

        report.run(subject, f"{function.name.upper()}{tuple(arguments)!r} gives {answer!r}", example_runs)


def _check_chart(report: Report, plugin: Plugin, chart: ChartType) -> None:
    subject = f"chart type {plugin.name}_{getattr(chart, 'name', '?')}"
    if not report.expect(subject, "is a ChartType", isinstance(chart, ChartType), "Declare it as ChartType(...)."):
        return
    report.expect(subject, "has a name of lowercase letters, digits and _", bool(NAME.match(chart.name)),
                  f"{chart.name!r} is not a name such as lollipop.")
    report.expect(subject, "has a label", bool(chart.label.strip()), "Give it a label.")
    report.expect(subject, "says what it shows in a sentence", _sentence(chart.description),
                  "The description is a sentence ending in a full stop.")
    low_d, high_d = chart.dimensions
    low_m, high_m = chart.measures
    report.expect(subject, "takes 0 to 2 grouping columns and 1 to 6 measures",
                  0 <= low_d <= high_d <= MAX_DIMENSIONS and 1 <= low_m <= high_m <= MAX_MEASURES,
                  f"dimensions {chart.dimensions}, measures {chart.measures}.")
    report.expect(subject, "has marks", bool(chart.marks), "A chart draws at least one mark.")
    series = high_m if high_d < 2 else 99
    for mark in chart.marks:
        report.expect(subject, f"its {mark.kind} mark draws something it has",
                      mark.kind in MARK_KINDS and (mark.series == "all"
                                                   or (isinstance(mark.series, int) and 0 <= mark.series < series)),
                      f"A mark is one of {', '.join(MARK_KINDS)}, on all series or a series it has.")
    report.expect(subject, "has known scales", chart.x_scale in ("band", "linear") and chart.y_scale in
                  ("linear", "log"), "x_scale is band or linear; y_scale linear or log.")


def _check_connector(report: Report, plugin: Plugin, connector: Connector) -> None:
    subject = f"connector {plugin.name}_{getattr(connector, 'name', '?')}"
    if not report.expect(subject, "is a Connector", isinstance(connector, Connector),
                         "Declare a class that subclasses Connector, and add an instance of it."):
        return
    report.expect(subject, "has a name of lowercase letters, digits and _", bool(NAME.match(connector.name)),
                  f"{connector.name!r} is not a name such as acme_api.")
    report.expect(subject, "has a label", bool(connector.label.strip()), "Give it a label.")
    report.expect(subject, "says what it reaches", len(connector.description.strip()) >= 10,
                  "Describe it in at least a few words.")
    report.expect(subject, "is in a known category", connector.category in CONNECTOR_CATEGORIES,
                  f"category is one of {', '.join(CONNECTOR_CATEGORIES)}.")
    names = [f.name for f in connector.fields]
    report.expect(subject, "names each setting once", len(names) == len(set(names)) and all(
        NAME.match(name) and f.label.strip() and f.kind in FIELD_KINDS for name, f in zip(names, connector.fields)),
        "Each setting needs its own key, a label and a known kind.")
    report.expect(subject, "can test a connection", type(connector).can("test"), "Fill in test(config).")
    reads = type(connector).can("read")
    report.expect(subject, "lists what it reads if it reads", not reads or type(connector).can("streams"),
                  "A connector that reads also lists its streams.")


def _check_manifest(report: Report, plugin: Plugin, manifest: RestManifest) -> None:
    subject = "connector manifest"
    try:
        document = manifest.load()
    except Exception as exc:  # noqa: BLE001 - an unreadable manifest is the finding
        report.expect(subject, "can be read", False, f"{type(exc).__name__}: {exc}")
        return
    subject = f"connector {document.get('key', '?')}"
    kind = str(document.get("key", ""))
    report.expect(subject, "is named after its plugin", kind.startswith(f"{plugin.name}_") and bool(NAME.match(kind)),
                  f"A plugin's connector is named after it: {plugin.name}_something, not {kind!r}.")
    report.expect(subject, "has a label and a description",
                  bool(str(document.get("label", "")).strip()) and len(str(document.get("description", ""))) >= 10,
                  "Give it a label and a description.")
    report.expect(subject, "claims no tier it has not earned here", document.get("tier", 4) == 4,
                  "A plugin's connector is not yet tested here: leave tier at 4.")
