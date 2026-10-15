"""What a Pipewright plugin is made of: SDK 1 (Phase 23, X1).

A plugin is a Python package, or a folder, that hands Pipewright one
`Plugin`: its name, version and publisher, the SDK version it was written
for, and what it adds. It can add

* **tools** for the Studio, each working on one column a value at a time;
* **formula functions**, usable in any formula as ``NAME(...)``;
* **chart types**, declared as marks over a chart's series, which the web
  draws with its own SVG, so no plugin code ever runs in a browser;
* **connectors**, as a REST manifest in the format of Pipewright's own, or a
  class that tests a connection, lists what it can read and reads it.

A package names its plugin under the ``pipewright.plugins`` entry point::

    [project.entry-points."pipewright.plugins"]
    acme = "acme_plugin:plugin"

and a folder holds a ``plugin.py`` that defines ``plugin``. Pipewright loads
only the plugins an administrator names in ``PLUGINS_ENABLED``, runs the same
checks on each as on its own tools, functions, charts and connectors, and
refuses a plugin, saying why, when any part of it fails them. Nothing is ever
loaded silently.

This module depends on nothing outside the standard library, so a plugin can
be written and checked (``pipewright plugin check``) without a Pipewright
server.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

#: The interface this package describes. A plugin says which it was written
#: for; a server refuses a plugin written for another.
SDK_VERSION = 1

#: Names a plugin and the things in it, as they appear in settings and data.
NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

ParamKind = Literal["text", "number", "integer", "boolean", "select"]
Accepts = Literal["any", "text", "number", "date", "boolean"]
ValueType = Literal["text", "number", "integer", "boolean", "date", "timestamp"]
#: The kinds of connector Pipewright's catalogue groups by.
CONNECTOR_CATEGORIES = ("database", "warehouse", "api", "storage", "saas", "nosql", "file", "timeseries",
                        "streaming", "lakehouse")
FieldKind = Literal["string", "secret", "number", "boolean", "select", "text"]


@dataclass(frozen=True)
class Param:
    """A setting of a tool, shown in its form."""

    key: str
    label: str
    kind: ParamKind = "text"
    required: bool = True
    default: Any = None
    options: tuple[str, ...] = ()
    help: str = ""


@dataclass(frozen=True)
class Example:
    """Values in, settings, and the values that come out: run by every check."""

    values: tuple[Any, ...]
    expect: tuple[Any, ...]
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    """A Studio tool that works on one column, a value at a time.

    ``transform(value, settings)`` is given one value that is there (never an
    empty one: an empty value stays empty without it being asked) and the
    tool's settings, and returns the new value. Pipewright names the tool
    ``<plugin>.<name>`` and lists it under ``category``.
    """

    name: str
    title: str
    summary: str
    transform: Callable[[Any, Mapping[str, Any]], Any]
    example: Example
    accepts: Accepts = "any"
    #: The type of what it gives; "same" keeps the column's own.
    returns: ValueType | Literal["same"] = "same"
    params: tuple[Param, ...] = ()
    synonyms: tuple[str, ...] = ()
    category: str = "From plugins"


@dataclass(frozen=True)
class Function:
    """A formula function: ``NAME(argument, ...)`` in any formula.

    ``implementation(*arguments)`` is given arguments that are all there; an
    empty argument gives an empty answer without it being asked. Runs on this
    server, never in a database.
    """

    name: str
    summary: str
    implementation: Callable[..., Any]
    returns: ValueType
    min_args: int = 1
    max_args: int = 1
    #: (arguments, answer) pairs, each checked.
    examples: tuple[tuple[tuple[Any, ...], Any], ...] = ()


MarkKind = Literal["bar", "line", "point", "area", "rule", "text"]


@dataclass(frozen=True)
class Mark:
    """One layer of a chart: how each series' values are drawn against the labels.

    ``series`` is "all", or the position of one series (from 0). A rule is a
    line from zero to each value, a text writes each value.
    """

    kind: MarkKind
    series: Literal["all"] | int = "all"
    size: int = 4


@dataclass(frozen=True)
class ChartType:
    """A chart people can choose in the chart builder, drawn by the web from its marks.

    A chart is a query's grouping columns (dimensions) and numbers (measures):
    the first dimension gives the labels along the bottom, each measure (or,
    with a second dimension, each of its values) a series.
    """

    name: str
    label: str
    description: str
    marks: tuple[Mark, ...]
    dimensions: tuple[int, int] = (1, 1)
    measures: tuple[int, int] = (1, 1)
    x_scale: Literal["band", "linear"] = "band"
    y_scale: Literal["linear", "log"] = "linear"
    stacked: bool = False
    max_categories: int | None = 60


@dataclass(frozen=True)
class Field:
    """A setting of a connection, shown in its form; a secret is kept encrypted."""

    name: str
    label: str
    kind: FieldKind = "string"
    required: bool = True
    default: Any = None
    help: str = ""
    options: tuple[str, ...] = ()


class Connector:
    """A connector written in Python. Subclass it and fill in what it can do.

    ``test`` is required; ``streams`` and ``read`` make it a source. A row is
    a mapping of column to value. Pipewright names it ``<plugin>_<name>`` and,
    as for any connector it has not tested itself, says it is not yet tested.
    """

    name: str = ""
    label: str = ""
    description: str = ""
    category: str = "api"
    fields: tuple[Field, ...] = ()

    def test(self, config: Mapping[str, Any]) -> tuple[bool, str]:
        """Whether the settings reach the system, and a sentence saying so."""
        raise NotImplementedError

    def streams(self, config: Mapping[str, Any]) -> list[str]:
        """What can be read: tables, endpoints, files."""
        raise NotImplementedError

    def read(self, config: Mapping[str, Any], stream: str, limit: int) -> Iterable[Mapping[str, Any]]:
        """Up to ``limit`` rows of a stream."""
        raise NotImplementedError

    @classmethod
    def can(cls, method: str) -> bool:
        """Whether this connector fills in a method itself."""
        return getattr(cls, method) is not getattr(Connector, method)


@dataclass(frozen=True)
class RestManifest:
    """A REST connector in the manifest format of Pipewright's own (``connectors/manifests``).

    ``document`` is the manifest, or the path of its YAML file (read with
    PyYAML, which a Pipewright server has).
    """

    document: Mapping[str, Any] | str

    def load(self) -> dict[str, Any]:
        if isinstance(self.document, str):
            import yaml  # a server always has it; checking a folder plugin by hand needs it installed

            with open(self.document, encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
            if not isinstance(loaded, dict):
                raise ValueError(f"{self.document} is not a manifest: it holds no mapping.")
            return loaded
        return dict(self.document)


@dataclass(frozen=True)
class Plugin:
    """Everything one plugin adds, and who made it."""

    name: str
    version: str
    publisher: str
    description: str
    sdk: int = SDK_VERSION
    tools: tuple[Tool, ...] = ()
    functions: tuple[Function, ...] = ()
    chart_types: tuple[ChartType, ...] = ()
    connectors: tuple[Connector | RestManifest, ...] = ()

    def contributions(self) -> list[tuple[str, str, str]]:
        """(kind, name as Pipewright knows it, title) for each thing it adds."""
        found: list[tuple[str, str, str]] = []
        found += [("tool", f"{self.name}.{tool.name}", tool.title) for tool in self.tools]
        found += [("function", function.name.upper(), function.summary) for function in self.functions]
        found += [("chart type", f"{self.name}_{chart.name}", chart.label) for chart in self.chart_types]
        for connector in self.connectors:
            if isinstance(connector, RestManifest):
                try:
                    document = connector.load()
                except Exception:  # noqa: BLE001 - the checks say what is wrong with it
                    document = {}
                found.append(("connector", str(document.get("key", "?")), str(document.get("label", "?"))))
            else:
                found.append(("connector", f"{self.name}_{connector.name}", connector.label))
        return found


__all__ = [
    "CONNECTOR_CATEGORIES",
    "ChartType",
    "Connector",
    "Example",
    "Field",
    "Function",
    "Mark",
    "NAME",
    "Param",
    "Plugin",
    "RestManifest",
    "SDK_VERSION",
    "Tool",
]
