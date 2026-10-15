"""Loading plugins: what an administrator names, checked like Pipewright's own (X1).

A plugin is an installed package naming itself under the ``pipewright.plugins``
entry point, or a folder with a ``plugin.py`` inside one of the folders in
``PLUGINS_PATH``. Only those named in ``PLUGINS_ENABLED`` are imported at all;
the rest are listed as installed and not enabled, so nothing runs that nobody
chose.

Each enabled plugin is checked first by the SDK's own checks (what it
declares and its examples), then each thing it adds by the suite that holds
Pipewright's own of that kind: a tool by the tool library's structural
checks, a function by the function catalogue's, a chart type by the chart
validator and a connector by the connector conformance suite. One failure
refuses the whole plugin, with the reason, and leaves nothing of it behind.

The gateway and each background process (the workflow worker, the schedule
ticker, the live runner) load plugins when they start, the same way, so a
plugin's tool works in a preview and in a run alike. What happened is kept
for **Admin → Plugins**.
"""

from __future__ import annotations

import logging
import os
import pathlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from typing import Any

logger = logging.getLogger(__name__)

GROUP = "pipewright.plugins"


@dataclass
class PluginStatus:
    name: str
    source: str
    state: str  # "loaded", "refused", "not enabled", "not found"
    reason: str = ""
    version: str = ""
    publisher: str = ""
    description: str = ""
    sdk: int | None = None
    contributions: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Refused(Exception):
    pass


STATUSES: list[PluginStatus] = []
#: How to take back what each loaded plugin added, by plugin name.
_UNDO: dict[str, list[Callable[[], None]]] = {}
_LOADED = False


def _names(setting: str) -> list[str]:
    seen: list[str] = []
    for name in setting.split(","):
        if name.strip() and name.strip() not in seen:
            seen.append(name.strip())
    return seen


def discover(plugins_path: str) -> dict[str, tuple[str, Callable[[], Any]]]:
    """Every plugin installed here, by name, with how to load it; nothing is imported."""
    from pipewright_plugin_sdk.checks import load_folder

    found: dict[str, tuple[str, Callable[[], Any]]] = {}
    for entry in entry_points(group=GROUP):
        found.setdefault(entry.name, (f"the package entry point {entry.value}", entry.load))
    for folder in (part for part in plugins_path.split(os.pathsep) if part.strip()):
        root = pathlib.Path(folder).expanduser()
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if (child / "plugin.py").is_file():
                found.setdefault(child.name, (f"the folder {child}", lambda child=child: load_folder(child)))
    return found


def load_enabled(settings: Any = None) -> list[PluginStatus]:
    """Load the plugins named in ``PLUGINS_ENABLED``, once per process."""
    global _LOADED
    if _LOADED:
        return STATUSES
    if settings is None:
        from api_gateway.config import settings
    _LOADED = True
    enabled = _names(getattr(settings, "plugins_enabled", "") or "")
    found = discover(getattr(settings, "plugins_path", "") or "")
    for name, (source, _) in sorted(found.items()):
        if name not in enabled:
            STATUSES.append(PluginStatus(name=name, source=source, state="not enabled",
                                         reason="Installed here; add it to PLUGINS_ENABLED to load it."))
    for name in enabled:
        if name not in found:
            STATUSES.append(PluginStatus(
                name=name, source="", state="not found",
                reason=f"PLUGINS_ENABLED names {name}, but no installed package (entry point {GROUP}) or folder "
                       "in PLUGINS_PATH provides it."))
            logger.warning("plugin_not_found", extra={"plugin": name})
            continue
        source, loader = found[name]
        status = _load_one(name, source, loader)
        STATUSES.append(status)
        log = logger.info if status.state == "loaded" else logger.warning
        log("plugin_%s", status.state.replace(" ", "_"), extra={"plugin": name, "reason": status.reason})
    return STATUSES


def unload_all() -> None:
    """Take back everything plugins added, as if none had loaded (for tests)."""
    global _LOADED
    for undo in _UNDO.values():
        for step in reversed(undo):
            step()
    _UNDO.clear()
    STATUSES.clear()
    _LOADED = False


def _load_one(name: str, source: str, loader: Callable[[], Any]) -> PluginStatus:
    from pipewright_plugin_sdk import Plugin
    from pipewright_plugin_sdk.checks import check

    status = PluginStatus(name=name, source=source, state="refused")
    try:
        plugin = loader()
    except Exception as exc:  # noqa: BLE001 - a plugin that does not import is refused, saying why
        status.reason = f"It could not be imported: {type(exc).__name__}: {exc}"
        return status
    if not isinstance(plugin, Plugin):
        status.reason = "It does not give Pipewright a Plugin(...) from pipewright_plugin_sdk."
        return status
    status.version, status.publisher, status.description, status.sdk = (
        plugin.version, plugin.publisher, plugin.description, plugin.sdk)
    if plugin.name != name:
        status.reason = f"It is installed as {name} but calls itself {plugin.name}."
        return status
    report = check(plugin)
    status.checks = [{**item.to_dict(), "suite": "the plugin SDK"} for item in report.checks]
    status.contributions = [{"kind": kind, "name": added, "title": title} for kind, added, title in
                            plugin.contributions()]
    if not report.ok:
        first = report.failures[0]
        status.reason = f"{first.subject} does not pass: {first.name}. {first.detail}".strip()
        return status
    undo: list[Callable[[], None]] = []
    try:
        _add_tools(plugin, status, undo)
        _add_functions(plugin, status, undo)
        _add_charts(plugin, status, undo)
        _add_connectors(plugin, status, undo)
    except _Refused as refusal:
        for step in reversed(undo):
            step()
        status.reason = str(refusal)
        return status
    except Exception as exc:  # noqa: BLE001 - refused, never half loaded
        for step in reversed(undo):
            step()
        status.reason = f"Pipewright could not add what it brings: {type(exc).__name__}: {exc}"
        return status
    _UNDO[name] = undo
    status.state, status.reason = "loaded", ""
    for contribution in status.contributions:
        contribution["tier"] = ("Not yet tested: written from its own description, never run here against "
                                "the system it reaches" if contribution["kind"] == "connector"
                                else "Checked here by the suites Pipewright's own pass")
    return status


def _record(status: PluginStatus, subject: str, suite: str, passed: list[str], failures: list[str]) -> None:
    for name in passed:
        status.checks.append({"subject": subject, "name": name, "passed": True, "detail": "", "suite": suite})
    for failure in failures:
        name, _, detail = failure.partition(": ")
        status.checks.append({"subject": subject, "name": name, "passed": False, "detail": detail, "suite": suite})
    if failures:
        raise _Refused(f"{subject} does not pass {suite}: {failures[0]}.")


def _add_tools(plugin: Any, status: PluginStatus, undo: list) -> None:
    from service_transformations import plugin_host
    from service_transformations.tools.conformance import check_tool

    for tool in plugin.tools:
        spec = plugin_host.tool_spec(plugin.name, tool)
        plugin_host.add_tool(spec)
        undo.append(lambda name=spec.name: plugin_host.remove_tool(name))
        report = check_tool(spec)
        _record(status, f"tool {spec.name}", "the tool library's structural checks", report.passed, report.failures)


def _add_functions(plugin: Any, status: PluginStatus, undo: list) -> None:
    from service_transformations import plugin_host

    for function in plugin.functions:
        clash = plugin_host.function_clash(function.name)
        if clash:
            _record(status, f"function {function.name.upper()}", "the function catalogue's checks", [],
                    [f"has a name of its own: {clash}"])
        name = plugin_host.add_function(plugin.name, function)
        undo.append(lambda name=name: plugin_host.remove_function(name))
        problems = plugin_host.check_function(name, function.examples)
        _record(status, f"function {name.upper()}", "the function catalogue's checks",
                [] if problems else ["gives its examples in a formula, and empty for an empty argument"],
                [f"works in a formula: {problem}" for problem in problems])


def _add_charts(plugin: Any, status: PluginStatus, undo: list) -> None:
    from service_reporting import charts

    for chart in plugin.chart_types:
        name = f"{plugin.name}_{chart.name}"
        declared = {"marks": [{"kind": mark.kind, "series": mark.series, "size": mark.size} for mark in chart.marks],
                    "x_scale": chart.x_scale, "y_scale": chart.y_scale, "stacked": chart.stacked}
        spec = charts.ChartType(name, chart.label, chart.description, chart.dimensions[0], chart.dimensions[1],
                                chart.measures[0], chart.measures[1], chart.max_categories, declared=declared,
                                plugin=plugin.name)
        charts.register_chart_type(spec)
        undo.append(lambda name=name: charts.unregister_chart_type(name))
        problems = charts.check_chart_type(spec)
        _record(status, f"chart type {name}", "the chart validator",
                [] if problems else ["draws a query it allows"], [f"draws a query it allows: {p}" for p in problems])


def _add_connectors(plugin: Any, status: PluginStatus, undo: list) -> None:
    from pipewright_plugin_sdk import RestManifest
    from service_connectors import registry
    from service_connectors.conformance import check_spec
    from service_connectors.plugin_host import PluginConnector, manifest_connector

    for declared in plugin.connectors:
        connector = (manifest_connector(declared.load()) if isinstance(declared, RestManifest)
                     else PluginConnector(plugin.name, declared))
        kind = connector.spec.type
        if kind in registry.known_types():
            _record(status, f"connector {kind}", "the connector conformance suite", [],
                    [f"has a name of its own: there is a connector called {kind} already"])
        registry.register(connector)
        undo.append(lambda kind=kind: registry.unregister(kind))
        report = check_spec(connector)
        _record(status, f"connector {kind}", "the connector conformance suite", list(report.passed),
                list(report.failures))


def build_plugins_router(get_current_user: Callable[..., Any]):
    """``GET /plugins``: what is installed and enabled, and how each did, for an administrator."""
    from fastapi import APIRouter, Depends

    from service_auth.schemas import UserRead
    from shared_python.errors import ForbiddenError

    router = APIRouter(tags=["plugins"])

    @router.get("/plugins")
    def list_plugins(current_user: UserRead = Depends(get_current_user)) -> dict[str, Any]:
        """Every plugin installed here, what it adds, its checks and whether it loaded."""
        if current_user.role != "admin":
            raise ForbiddenError("Only a platform admin can see the plugins.")
        from pipewright_plugin_sdk import SDK_VERSION

        return {"sdk": SDK_VERSION, "items": [status.to_dict() for status in STATUSES]}

    return router
