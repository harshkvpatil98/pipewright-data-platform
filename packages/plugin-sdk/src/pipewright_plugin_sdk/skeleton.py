"""A plugin to start from: what ``pipewright plugin new`` writes (X1).

It works as written: a tool, a formula function, a chart type and a REST
connector, each with an example, so ``pipewright plugin check`` passes on it
before anything is changed.
"""

from __future__ import annotations

import pathlib

from pipewright_plugin_sdk import NAME, SDK_VERSION

_PYPROJECT = """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{dist}"
version = "0.1.0"
description = "{title}: a Pipewright plugin."
requires-python = ">=3.11"
dependencies = ["pipewright-plugin-sdk>={sdk}"]

# Pipewright finds the plugin here, and loads it when an administrator names
# it in PLUGINS_ENABLED.
[project.entry-points."pipewright.plugins"]
{name} = "{package}:plugin"

[tool.setuptools]
packages = ["{package}"]
"""

_PACKAGE = '''"""{title}: a Pipewright plugin."""

from pipewright_plugin_sdk import ChartType, Example, Function, Mark, Param, Plugin, RestManifest, Tool


def _initials(value, settings):
    words = str(value).split()
    joined = settings.get("separator") or ""
    return joined.join(word[0].upper() for word in words if word)


def _between(value, low, high):
    return low <= value <= high


plugin = Plugin(
    name="{name}",
    version="0.1.0",
    publisher="{publisher}",
    description="Initials, a range test, a lollipop chart and an example REST connector.",
    tools=(
        Tool(
            name="initials",
            title="Initials",
            summary="The first letter of each word, in capitals.",
            transform=_initials,
            accepts="text",
            returns="text",
            params=(Param("separator", "Between the letters", required=False, default=""),),
            example=Example(values=("ada lovelace", "grace brewster hopper"), expect=("AL", "GBH")),
            synonyms=("first letters", "monogram"),
        ),
    ),
    functions=(
        Function(
            name="{name}_between",
            summary="Whether a number is from low to high, both included.",
            implementation=_between,
            returns="boolean",
            min_args=3,
            max_args=3,
            examples=(((5, 1, 10), True), ((11, 1, 10), False)),
        ),
    ),
    chart_types=(
        ChartType(
            name="lollipop",
            label="Lollipop",
            description="A number for each category, as a stem and a dot.",
            marks=(Mark("rule"), Mark("point", size=5)),
        ),
    ),
    connectors=(
        RestManifest({{
            "key": "{name}_status",
            "label": "Example status API",
            "description": "An example REST API with one endpoint, to show a plugin's connector.",
            "category": "api",
            "base_url": "https://status.example.com/api",
            "auth": {{"kind": "none"}},
            "streams": [{{"name": "components", "path": "/components", "records_path": "components"}}],
        }}),
    ),
)
'''

_FOLDER = '''"""Pipewright loads a folder plugin from here: PLUGINS_PATH names the folder this is in."""

from {package} import plugin  # noqa: F401
'''

_README = """# {title}

A Pipewright plugin. Check it, then install it where Pipewright runs:

    pipewright plugin check .
    pip install -e .

and name it in the server's settings: `PLUGINS_ENABLED={name}`. Restart the
gateway and the worker; **Admin → Plugins** lists it, what it adds and its
checks.
"""


def write_skeleton(directory: str | pathlib.Path, name: str, publisher: str = "Your name") -> pathlib.Path:
    """Write a working plugin called ``name`` into ``directory``/``name``; refuse to write over one."""
    if not NAME.match(name):
        raise ValueError(f"{name!r} is not a plugin name: lowercase letters, digits and _, such as acme.")
    root = pathlib.Path(directory) / name
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{root} already exists and is not empty.")
    package = f"{name}_plugin"
    title = name.replace("_", " ").title()
    values = {"name": name, "package": package, "publisher": publisher.replace('"', "'"), "title": title,
              "dist": f"pipewright-plugin-{name.replace('_', '-')}", "sdk": SDK_VERSION}
    (root / package).mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(_PYPROJECT.format(**values), encoding="utf-8")
    (root / package / "__init__.py").write_text(_PACKAGE.format(**values), encoding="utf-8")
    (root / "plugin.py").write_text(_FOLDER.format(**values), encoding="utf-8")
    (root / "README.md").write_text(_README.format(**values), encoding="utf-8")
    return root
