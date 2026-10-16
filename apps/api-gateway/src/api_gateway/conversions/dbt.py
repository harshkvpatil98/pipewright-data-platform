"""A dbt project to recipes, checks and a workflow (E2, X3).

Read from a .zip of the project's folder, as dbt's own published layout
has it: ``dbt_project.yml``, models (``.sql`` with ``.yml`` properties),
sources, seeds (``.csv``) and tests. The Jinja is read, never run: a model
may use ``ref``, ``source``, ``var`` and ``config``, and ``is_incremental()``
in an ``if`` (a full build is converted, as ``dbt run --full-refresh``
builds it); anything else (a macro, a loop, ``set``) is code this does not
run, and the model is not converted, with the reason.

- A model becomes a recipe (``sql.py``): its first table is what the recipe
  reads, its joins steps, the rest a SQL step; a CTE another part reads as a
  table becomes a recipe of its own. A ``var`` becomes a recipe parameter,
  written into the SQL as dbt writes it.
- A seed becomes a dataset made from its file; a source is a dataset the
  project has, matched by name or chosen.
- ``not_null``, ``unique``, ``accepted_values`` and two of dbt_utils' tests
  become checks; ``relationships`` and a test written as SQL (in ``tests/``)
  become a recipe whose result is the failing rows, with a check that there
  are none, which is what a dbt test is.
- A workflow builds them as ``dbt build`` does: each model after what it
  reads, and its tests after it.
"""

from __future__ import annotations

import ast
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from service_transformations.parameters import used
from shared_python.types import PWType

from api_gateway.conversions.model import (
    CheckPlan,
    Conversion,
    LinkPlan,
    Needed,
    NotConverted,
    RecipePlan,
    Section,
    Seed,
    TaskPlan,
    WorkflowPlan,
)
from api_gateway.conversions.sql import Scope, compile_model, dataset_table, parameter_for, parse

#: (a need) -> its columns, from the dataset matched or chosen for it; None when there is none yet.
Lookup = Callable[[Needed], "dict[str, PWType] | None"]

MAX_FILES = 2_000
_PARAMETER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_JINJA = re.compile(r"\{\{-?(.*?)-?\}\}|\{%-?(.*?)-?%\}|\{#.*?#\}", re.S)
# What a file in each folder dbt never builds is called in the report.
_KIND_OF_FOLDER = {"macros": "macro", "snapshots": "the table", "analyses": "analysis"}


def is_dbt_project(files: dict[str, bytes]) -> bool:
    return any(posixpath.basename(path) == "dbt_project.yml" for path in files)


def read_zip(data: bytes) -> dict[str, bytes]:
    """The files of a .zip, by path. Paths that climb out of it are refused."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise NotConverted("This is not a .zip file this can open.") from exc
    entries = [info for info in archive.infolist() if not info.is_dir()]
    if len(entries) > MAX_FILES:
        raise NotConverted(f"The .zip holds {len(entries):,} files; a project here is at most {MAX_FILES:,}.")
    files: dict[str, bytes] = {}
    total = 0
    for info in entries:
        path = posixpath.normpath(info.filename.replace("\\", "/"))
        if path.startswith("../") or path.startswith("/") or "/../" in path:
            raise NotConverted(f"The .zip holds {info.filename}, which points outside it.")
        if "__MACOSX" in path or posixpath.basename(path).startswith("._"):
            continue
        total += info.file_size
        if total > 50 * 1024 * 1024:
            raise NotConverted("The project's files come to more than 50 MB unpacked.")
        files[path] = archive.read(info)
    return files


# ===================================================================== Jinja


@dataclass
class Rendered:
    sql: str
    #: sentinel -> ("ref", model) or ("source", (source, table))
    tables: dict[str, tuple[str, Any]] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    incremental: bool = False


def _literal(node: ast.AST, what: str) -> Any:
    try:
        return ast.literal_eval(node)
    except ValueError as exc:
        raise NotConverted(f"{what} is given something worked out by code ({ast.unparse(node)}), which this "
                           "reads but never runs.") from exc


def render(text: str, *, variables: dict[str, Any], what: str) -> Rendered:
    """A model's Jinja, read: its tables, parameters and config, and the SQL left."""
    out: list[str] = []
    rendered = Rendered("")
    keeping: list[bool] = []
    position = 0
    sentinels: dict[tuple[str, Any], str] = {}

    def sentinel(kind: str, value: Any) -> str:
        key = (kind, value)
        if key not in sentinels:
            sentinels[key] = f"__pw_{kind}_{len(sentinels)}__"
            rendered.tables[sentinels[key]] = (kind, value)
        return sentinels[key]

    for match in _JINJA.finditer(text):
        if all(keeping):
            out.append(text[position:match.start()])
        position = match.end()
        expression, statement = match.group(1), match.group(2)
        if expression is not None:
            if not all(keeping):
                continue
            out.append(_expression(expression.strip(), rendered, sentinel, variables, what))
        elif statement is not None:
            words = statement.strip()
            condition = re.fullmatch(r"if\s+(not\s+)?is_incremental\(\s*\)", words)
            if condition:
                rendered.incremental = True
                # A full build: is_incremental() is false.
                keeping.append(bool(condition.group(1)))
            elif words == "else" and keeping:
                keeping[-1] = not keeping[-1]
            elif words == "endif" and keeping:
                keeping.pop()
            else:
                keyword = words.split()[0] if words else "a statement"
                raise NotConverted(f"{what} uses {{% {keyword} %}}, Jinja code dbt runs to write the SQL; this "
                                   "reads a project and never runs its code.")
    if keeping:
        raise NotConverted(f"{what} opens an {{% if %}} it never closes.")
    out.append(text[position:])
    rendered.sql = "".join(out)
    return rendered


def _expression(expression: str, rendered: Rendered, sentinel, variables: dict[str, Any], what: str) -> str:
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError as exc:
        raise NotConverted(f"{what} has {{{{ {expression[:60]} }}}}, which is not Jinja this can read.") from exc
    if isinstance(node, ast.Name) and node.id == "this":
        raise NotConverted(f"{what} names {{{{ this }}}}, the table it is building, which a recipe cannot read "
                           "while it makes it.")
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        shown = ast.unparse(node.func) if isinstance(node, ast.Call) else expression
        raise NotConverted(f"{what} uses {shown[:60]}, a macro or code dbt runs to write the SQL; this reads a "
                           "project and never runs its code.")
    name = node.func.id
    args = [_literal(arg, f"{name}()") for arg in node.args]
    kwargs = {keyword.arg: _literal(keyword.value, f"{name}()") for keyword in node.keywords if keyword.arg}
    if name == "ref":
        if not 1 <= len(args) <= 2 or not all(isinstance(a, str) for a in args):
            raise NotConverted(f"{what} has ref() with {len(args)} names; it takes a model's name.")
        if len(args) == 2:
            raise NotConverted(f"{what} reads {args[1]} from the package {args[0]}; packages are code from "
                               "elsewhere, which this does not read.")
        return sentinel("ref", args[0])
    if name == "source":
        if len(args) != 2 or not all(isinstance(a, str) for a in args):
            raise NotConverted(f"{what} has source() with {len(args)} names; it takes a source and a table.")
        return sentinel("source", (args[0], args[1]))
    if name == "var":
        if not args or not isinstance(args[0], str):
            raise NotConverted(f"{what} has var() with no name.")
        variable = args[0]
        if variable in variables:
            value = variables[variable]
        elif len(args) > 1:
            value = args[1]
        else:
            raise NotConverted(f"{what} uses var('{variable}'), which has no value in dbt_project.yml and no "
                               "default; dbt stops on it too.")
        if not _PARAMETER_NAME.fullmatch(variable) or isinstance(value, (list, dict)):
            raise NotConverted(f"{what} uses var('{variable}'), whose value a recipe parameter cannot hold.")
        rendered.parameters[variable] = value
        return f"__pw_parameter_{variable}__"
    if name == "config":
        rendered.config.update(kwargs)
        return ""
    raise NotConverted(f"{what} uses {name}(), a macro or code dbt runs to write the SQL; this reads a project "
                       "and never runs its code.")


# ==================================================================== project


@dataclass
class _Model:
    name: str
    path: str
    text: str
    properties: dict[str, Any]
    config: dict[str, Any]
    rendered: Rendered | None = None
    problem: str | None = None


def _yaml(data: bytes, path: str) -> Any:
    try:
        return yaml.safe_load(data.decode("utf-8", errors="replace")) or {}
    except yaml.YAMLError as exc:
        raise NotConverted(f"{path} is not YAML this can read: {str(exc).splitlines()[0]}") from exc


def _folder_config(tree: Any, segments: list[str]) -> dict[str, Any]:
    """dbt_project.yml's model config for a model in these folders: the nearest wins."""
    config: dict[str, Any] = {}
    node = tree if isinstance(tree, dict) else {}
    for segment in [None, *segments]:
        if segment is not None:
            node = node.get(segment) if isinstance(node.get(segment), dict) else None
            if node is None:
                break
        for key, value in node.items():
            if key.startswith("+"):
                config[key[1:]] = value
            elif key in ("materialized", "enabled", "tags", "schema", "alias") and not isinstance(value, dict):
                config[key] = value
    return config


def convert_dbt(files: dict[str, bytes], lookup: Lookup) -> Conversion:
    root_file = min((path for path in files if posixpath.basename(path) == "dbt_project.yml"),
                    key=lambda path: path.count("/"), default=None)
    if root_file is None:
        raise NotConverted("There is no dbt_project.yml in it, so it is not a dbt project.")
    root = posixpath.dirname(root_file)
    rel = {posixpath.relpath(path, root) if root else path: data for path, data in files.items()
           if not root or path.startswith(root + "/")}
    project = _yaml(rel["dbt_project.yml"], "dbt_project.yml")
    name = str(project.get("name") or "dbt project")
    conversion = Conversion(format="dbt", title=f"the dbt project {name}")
    overview = conversion.section("dbt_project.yml")
    model_paths = [str(p).strip("/") for p in project.get("model-paths") or project.get("source-paths") or ["models"]]
    seed_paths = [str(p).strip("/") for p in project.get("seed-paths") or project.get("data-paths") or ["seeds"]]
    test_paths = [str(p).strip("/") for p in project.get("test-paths") or ["tests"]]
    variables = _variables(project.get("vars") or {}, name)

    for key in ("on-run-start", "on-run-end"):
        if project.get(key):
            overview.not_converted(key, "It runs statements against the warehouse at the start or end of a run, "
                                        "which a recipe does not do.")
    if any(path in rel for path in ("packages.yml", "dependencies.yml")):
        overview.not_converted("packages.yml", "Packages are models and macros from elsewhere; this reads what is "
                                               "in the project. A model that uses one says so.")
    if variables:
        overview.converted("vars", "Recipe parameters: " + ", ".join(
            f"{key} (by default {value})" for key, value in sorted(variables.items())))

    def under(paths: list[str], suffix: str) -> list[str]:
        return sorted(path for path in rel if path.endswith(suffix)
                      and any(path == p or path.startswith(p + "/") for p in paths))

    # -------------------------------------------------- properties (.yml)
    properties: dict[str, dict[str, Any]] = {}
    sources: dict[tuple[str, str], dict[str, Any]] = {}
    seed_properties: dict[str, dict[str, Any]] = {}
    for path in under(model_paths + seed_paths, ".yml") + under(model_paths + seed_paths, ".yaml"):
        document = _yaml(rel[path], path)
        if not isinstance(document, dict):
            continue
        for item in document.get("models") or []:
            if isinstance(item, dict) and item.get("name"):
                properties[str(item["name"])] = item
        for item in document.get("seeds") or []:
            if isinstance(item, dict) and item.get("name"):
                seed_properties[str(item["name"])] = item
        for source in document.get("sources") or []:
            for table in (source or {}).get("tables") or []:
                if isinstance(table, dict) and table.get("name"):
                    sources[(str(source.get("name")), str(table["name"]))] = {**table, "_source": source}
        for kind in ("exposures", "metrics", "semantic_models", "saved_queries"):
            for item in document.get(kind) or []:
                conversion.section(f"{path}").nothing_to_do(
                    f"{kind.replace('_', ' ').rstrip('s')} {item.get('name')}",
                    "It describes who uses the models or how to measure them; there is nothing in it to run.")

    # ---------------------------------------------------------------- seeds
    seeds: dict[str, dict[str, PWType]] = {}
    for path in under(seed_paths, ".csv"):
        seed_name = posixpath.splitext(posixpath.basename(path))[0]
        section = conversion.section(path)
        try:
            columns = _seed_columns(rel[path])
        except NotConverted as exc:
            section.not_converted(f"seed {seed_name}", exc.reason)
            continue
        seeds[seed_name] = columns
        conversion.seeds.append(Seed(key=f"seed:{seed_name}", name=seed_name, what=f"the dbt seed {seed_name}",
                                     file_name=posixpath.basename(path), data=rel[path]))
        section.converted(f"seed {seed_name}", f"The dataset “{seed_name}”, made from the file "
                                               f"({len(columns)} columns)")
        seed_config = (seed_properties.get(seed_name) or {}).get("config") or {}
        if seed_config.get("column_types"):
            section.not_converted("column_types", "Its columns' types are read from its values here, as every "
                                                  "file's are; a type dbt was told is not applied.")

    def need_for(source: str, table: str) -> tuple[Needed, dict[str, PWType] | None]:
        declared = sources.get((source, table)) or {}
        identifier = str(declared.get("identifier") or table)
        named = [str(column.get("name")) for column in declared.get("columns") or [] if isinstance(column, dict)]
        need = conversion.need(f"source:{source}.{table}", identifier, f"the dbt source {source}.{table}",
                               columns=named)
        found = lookup(need)
        if found is None and named:
            from shared_python.types.lattice import UNKNOWN

            found = {column: UNKNOWN for column in named}
        return need, found

    # --------------------------------------------------------------- models
    models: dict[str, _Model] = {}
    for path in under(model_paths, ".sql"):
        model_name = posixpath.splitext(posixpath.basename(path))[0]
        segments = posixpath.dirname(posixpath.relpath(path, next(
            p for p in model_paths if path.startswith(p + "/")))).split("/")
        segments = [s for s in segments if s and s != "."]
        props = properties.get(model_name) or {}
        config = {**_folder_config((project.get("models") or {}).get(name) or {}, segments),
                  **(props.get("config") or {})}
        model = _Model(model_name, path, rel[path].decode("utf-8", errors="replace"), props, config)
        try:
            model.rendered = render(model.text, variables=variables, what=f"The model {model_name}")
            model.config.update(model.rendered.config)
        except NotConverted as exc:
            model.problem = exc.reason
        models[model_name] = model

    order = _in_build_order(models)
    made_columns: dict[str, dict[str, PWType]] = {}
    sections: dict[str, Section] = {}
    built: list[str] = []

    for model_name in order:
        model = models[model_name]
        section = sections[model_name] = conversion.section(model.path)
        subject = f"model {model_name}"
        if model.config.get("enabled") is False:
            section.nothing_to_do(subject, "It is turned off (enabled: false), so dbt does not build it.")
            continue
        if model.problem:
            section.not_converted(subject, model.problem)
            continue
        rendered = model.rendered
        assert rendered is not None
        scope_tables, waiting = _tables(rendered, made_columns, seeds, models, need_for)
        if waiting:
            section.not_converted(subject, waiting)
            continue
        materialized = str(model.config.get("materialized") or "view")
        notes = []
        if materialized == "incremental" or rendered.incremental:
            notes.append("dbt adds only new rows on later runs; the recipe builds it in full every run, as "
                         "dbt run --full-refresh does, which gives the same rows when its incremental filter is "
                         "right.")
        elif materialized == "ephemeral":
            notes.append("dbt writes an ephemeral model into the models that read it; here it is a recipe of its "
                         "own, whose result they read: the same rows.")
        elif materialized not in ("view", "table"):
            section.not_converted(subject, f"It is materialized as {materialized}, which this does not convert.")
            continue
        try:
            query = parse(rendered.sql, f"The model {model_name}")
            chain, compiler = compile_model(query, scope=Scope(tables=scope_tables), owner=model_name,
                                            owner_key=f"model:{model_name}", parameters=rendered.parameters)
        except NotConverted as exc:
            section.not_converted(subject, exc.reason)
            continue
        for helper in compiler.helpers:
            conversion.recipes.append(helper)
            section.converted(f"the {helper.name.split(' · ', 1)[1]} part of {model_name}",
                              [f"The recipe “{helper.name}”, step {index}: {line}"
                               for index, line in enumerate(compiler.lines.get(helper.key, []), start=1)])
        conversion.recipes.append(RecipePlan(
            key=f"model:{model_name}", name=model_name, reads=chain.base, steps=chain.steps, columns=chain.columns,
            description=str(model.properties.get("description") or f"The dbt model {model_name}.")[:2000],
            parameters=[parameter_for(p, rendered.parameters.get(p)) for p in sorted(used(chain.steps))]))
        made_columns[model_name] = chain.columns
        built.append(model_name)
        section.converted(subject, [f"The recipe “{model_name}”, step {index}: {line}"
                                    for index, line in enumerate(chain.lines, start=1)], notes)
        if materialized in ("view", "table"):
            section.nothing_to_do(f"materialized: {materialized}", "A recipe's result is a dataset, whichever "
                                                                   "dbt makes; its rows are the same.")

    # Tests once every model is converted, so a test may compare with any of them.
    tests = _Tests()
    for model_name in built:
        _model_tests(conversion, sections[model_name], model_name, models[model_name].properties, made_columns,
                     seeds, need_for, tests)
    _source_tests(conversion, sources, need_for, tests)
    for path in under(test_paths, ".sql"):
        _singular_test(conversion, path, rel[path], variables, made_columns, seeds, models, need_for, tests)
    for path in sorted(rel):
        top = path.split("/")[0]
        if top in ("macros", "snapshots", "analyses", "analysis") and path.endswith(".sql"):
            words = {"macros": "A macro is code dbt runs to write SQL; this reads a project and never runs its "
                               "code. A model that uses it says so.",
                     "snapshots": "dbt keeps every version of this table's rows between runs, which a recipe "
                                  "does not do."}.get(top, "An analysis is a query dbt compiles and never builds, so there "
                                                  "is nothing to make.")
            section = conversion.section(path)
            (section.nothing_to_do if top.startswith("analys") else section.not_converted)(
                f"{_KIND_OF_FOLDER.get(top, 'analysis')} {posixpath.splitext(posixpath.basename(path))[0]}", words)

    if conversion.recipes:
        conversion.workflows.append(_build_workflow(conversion, name, tests))
        overview.converted("the project", f"The workflow “dbt build: {name}”")
    conversion.notes.append("The project is read, never run: no macro, hook or Jinja code of it ran here.")
    return conversion


def _tables(rendered: Rendered, made_columns, seeds, models, need_for) -> tuple[dict, str | None]:
    """The tables a model or test reads, or why it cannot read them yet."""
    tables = {}
    for sentinel, (kind, value) in rendered.tables.items():
        if kind == "ref":
            if value in made_columns:
                tables[sentinel] = dataset_table(value, f"model:{value}", made_columns[value])
            elif value in seeds:
                tables[sentinel] = dataset_table(value, f"seed:{value}", seeds[value])
            elif value in models:
                return tables, f"It reads the model {value}, which did not convert."
            else:
                return tables, f"It reads {value}, which is neither a model nor a seed of this project."
        else:
            need, columns = need_for(*value)
            if columns is None:
                return tables, (f"It reads {need.what}. Choose the dataset that holds it (none here is called "
                                f"“{need.name}”), then read the project again.")
            tables[sentinel] = dataset_table(f"{value[0]}.{value[1]}", need.key, columns)
    return tables, None


@dataclass
class _Tests:
    """What the workflow runs after each model: its checks, and the recipes of its tests."""

    #: model or source key -> its checks' keys
    checks: dict[str, list[str]] = field(default_factory=dict)
    #: test recipe key -> (its check's key, the models it is a test of)
    recipes: dict[str, tuple[str, list[str]]] = field(default_factory=dict)


def _reads(recipe: RecipePlan) -> list[str]:
    return recipe.reads_all()


def _build_workflow(conversion: Conversion, name: str, tests: _Tests) -> WorkflowPlan:
    """dbt build as a workflow: each recipe after what it reads, each model's tests after it, and a model
    after the tests of the models it reads (a failing test skips what follows, as in dbt)."""
    tasks: list[TaskPlan] = []
    links: list[LinkPlan] = []
    task_of: dict[str, str] = {}
    for recipe in conversion.recipes:
        verb = "Run" if recipe.key.startswith("test:") else "Build"
        key = _node_key(f"{verb}_{recipe.name}", tasks)
        tasks.append(TaskPlan(node_key=key, name=f"{verb} {recipe.name}"[:160], node_type="transformation",
                              config={"pipeline_id": {"$recipe": recipe.key}}))
        task_of[recipe.key] = key
    done: dict[str, list[str]] = {}
    for subject, keys in tests.checks.items():
        label = subject.split(":", 1)[1]
        gate = _node_key(f"test_{label}", tasks)
        tasks.append(TaskPlan(node_key=gate, name=f"Test {label}"[:160], node_type="quality_gate",
                              config={"dataset_id": {"$dataset": subject}, "rule_ids": {"$checks": keys}}))
        if subject in task_of:
            links.append(LinkPlan(task_of[subject], gate))
        done.setdefault(subject, []).append(gate)
    for recipe_key, (check_key, of) in tests.recipes.items():
        gate = _node_key(f"check_{conversion.recipe(recipe_key).name}", tasks)
        tasks.append(TaskPlan(node_key=gate, name=f"Check {conversion.recipe(recipe_key).name}"[:160],
                              node_type="quality_gate",
                              config={"dataset_id": {"$dataset": recipe_key}, "rule_ids": {"$checks": [check_key]}}))
        links.append(LinkPlan(task_of[recipe_key], gate))
        for model in of:
            done.setdefault(model, []).append(gate)
    for recipe in conversion.recipes:
        testing = recipe.key.split("·")[0].startswith("test:")
        for upstream in _reads(recipe):
            if upstream in task_of:
                # A test runs once what it tests is built; anything else waits for that model's tests too.
                sources = [task_of[upstream]] if testing or upstream not in done else done[upstream]
            else:
                sources = done.get(upstream, [])  # a source's tests, before what reads it
            for source in sources:
                links.append(LinkPlan(source, task_of[recipe.key]))
    return WorkflowPlan(key="workflow:build", name=f"dbt build: {name}"[:160], tasks=tasks, links=_unique(links),
                        description="Builds each model after the models it reads and runs each model's tests "
                                    "after it, as dbt build does: a model waits for the tests of the models it "
                                    "reads, and a failing test skips what follows.")


def _variables(tree: dict[str, Any], project: str) -> dict[str, Any]:
    """dbt_project.yml's vars: global ones, then the project's own, which win."""
    found = {key: value for key, value in tree.items() if not isinstance(value, dict)}
    found.update({key: value for key, value in (tree.get(project) or {}).items()} if isinstance(
        tree.get(project), dict) else {})
    return found


def _seed_columns(data: bytes) -> dict[str, PWType]:
    """A seed's columns as a run reads the dataset made from it."""
    from service_ingestion.read_copy import parse as parse_file
    from shared_python.errors import BadRequestError
    from shared_python.types import infer_pw_type

    try:
        frame = parse_file(data, file_type="csv", spec=None)
    except BadRequestError as exc:
        raise NotConverted(f"The file cannot be read: {exc.detail}") from exc
    return {str(column): infer_pw_type(frame[column]) for column in frame.columns}


def _in_build_order(models: dict[str, _Model]) -> list[str]:
    """Models after the models they read; a loop is refused where it is."""
    order: list[str] = []
    state: dict[str, str] = {}

    def visit(name: str, trail: list[str]) -> None:
        if state.get(name) == "done":
            return
        if state.get(name) == "visiting":
            loop = trail[trail.index(name):] + [name]
            for member in loop[:-1]:
                models[member].problem = f"It is in a loop of models that read each other: {' → '.join(loop)}."
            return
        state[name] = "visiting"
        rendered = models[name].rendered
        for kind, value in (rendered.tables.values() if rendered else []):
            if kind == "ref" and value in models:
                visit(value, [*trail, name])
        state[name] = "done"
        order.append(name)

    for name in sorted(models):
        visit(name, [])
    return order


def _node_key(wanted: str, tasks: list[TaskPlan]) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", wanted.lower()).strip("_")[:56] or "task"
    if not base[0].isalpha():
        base = f"t_{base}"[:56]
    key, number = base, 2
    while any(task.node_key == key for task in tasks):
        key, number = f"{base}_{number}", number + 1
    return key


def _unique(links: list[LinkPlan]) -> list[LinkPlan]:
    seen, out = set(), []
    for link in links:
        if (link.source, link.target) not in seen and link.source != link.target:
            seen.add((link.source, link.target))
            out.append(link)
    return out


# ===================================================================== tests


def _tests_of(item: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """A column's or a model's tests, as (name, arguments)."""
    found = []
    for test in [*(item.get("tests") or []), *(item.get("data_tests") or [])]:
        if isinstance(test, str):
            found.append((test, {}))
        elif isinstance(test, dict) and len(test) == 1:
            (test_name, arguments), = test.items()
            found.append((str(test_name), dict(arguments or {}) if isinstance(arguments, dict) else {}))
        elif isinstance(test, dict) and (test.get("test_name") or test.get("name")):
            arguments = {k: v for k, v in test.items() if k not in ("test_name", "name")}
            found.append((str(test.get("test_name") or test.get("name")), {**arguments,
                                                                          **(arguments.get("arguments") or {})}))
    return found


def _severity(arguments: dict[str, Any]) -> tuple[str, str | None]:
    """The check's severity, or why the test's settings cannot be kept."""
    config = {**arguments, **(arguments.get("config") or {})}
    for key in ("where", "limit", "error_if", "warn_if", "store_failures", "fail_calc"):
        if config.get(key) not in (None, False) and not (key == "error_if" and config[key] == "!= 0") and not (
                key == "warn_if" and config[key] == "!= 0"):
            return "error", f"It is set with {key}, which a check here has no setting for."
    severity = str(config.get("severity") or "error").lower()
    return ("warning" if severity == "warn" else "error"), None


def _model_tests(conversion: Conversion, section: Section, model_name: str, properties: dict[str, Any],
                 made_columns, seeds, need_for, tests: _Tests) -> None:
    reads = f"model:{model_name}"
    columns = made_columns[model_name]
    for column_props in properties.get("columns") or []:
        if not isinstance(column_props, dict) or not column_props.get("name"):
            continue
        column = str(column_props["name"])
        for test_name, arguments in _tests_of(column_props):
            subject = f"test {test_name} on {model_name}.{column}"
            if column not in columns:
                section.not_converted(subject, f"The model has no column {column}.")
                continue
            _column_test(conversion, section, subject, reads, model_name, column, test_name, arguments,
                         made_columns, seeds, need_for, tests)
    for test_name, arguments in _tests_of(properties):
        _table_test(conversion, section, f"test {test_name} on {model_name}", reads, model_name, columns,
                    test_name, arguments, tests)


def _column_test(conversion, section, subject, reads, model_name, column, test_name, arguments, made_columns,
                 seeds, need_for, tests: _Tests) -> None:
    severity, problem = _severity(arguments)
    if problem:
        section.not_converted(subject, problem)
        return
    short = test_name.split(".")[-1]
    if test_name in ("not_null", "unique", "accepted_values", "dbt_utils.accepted_range"):
        if test_name == "not_null":
            rule, config, words = "not_null", {"column": column}, f"{column} has no empty values"
        elif test_name == "unique":
            # dbt's unique test, as a SQL UNIQUE constraint, lets empty values repeat.
            rule, config, words = "unique", {"column": column, "ignore_empty": True}, f"{column} has no repeats"
        elif test_name == "accepted_values":
            values = arguments.get("values")
            if not isinstance(values, list) or not values:
                section.not_converted(subject, "It lists no values.")
                return
            if arguments.get("quote") is False and not all(isinstance(v, (int, float)) for v in values):
                section.not_converted(subject, "Its values are SQL written unquoted, which this does not run.")
                return
            rule, config, words = "allowed_values", {"column": column, "allowed_values": values,
                                                      "allow_null": True}, f"{column} is one of its values"
        else:
            if arguments.get("inclusive") is False:
                section.not_converted(subject, "It leaves out its ends (inclusive: false); a range check here "
                                               "includes them.")
                return
            low, high = arguments.get("min_value"), arguments.get("max_value")
            if not all(v is None or isinstance(v, (int, float)) and not isinstance(v, bool) for v in (low, high)) \
                    or (low is None and high is None):
                section.not_converted(subject, "Its range is not given as numbers.")
                return
            rule, words = "range", f"{column} is in its range"
            config = {"column": column, **({"min": low} if low is not None else {}),
                      **({"max": high} if high is not None else {})}
        key = f"check:{model_name}.{column}.{short}"
        conversion.checks.append(CheckPlan(key=key, name=f"{model_name}: {words}"[:160], reads=reads,
                                           rule_type=rule, config=config, severity=severity,
                                           description=f"The dbt test {test_name} on {model_name}.{column}."))
        tests.checks.setdefault(reads, []).append(key)
        section.converted(subject, f"The check “{model_name}: {words}”")
        return
    if test_name == "relationships":
        target = str(arguments.get("to") or "")
        field_name = str(arguments.get("field") or "")
        match = re.fullmatch(r"""\s*(ref|source)\(\s*(['"])([^'"]+)\2(?:\s*,\s*(['"])([^'"]+)\4)?\s*\)\s*""",
                             target)
        if not match or not field_name:
            section.not_converted(subject, "It names its other table in a way this does not read.")
            return
        if match.group(1) == "ref":
            other = match.group(3)
            if other in made_columns:
                other_key, other_columns, label = f"model:{other}", made_columns[other], other
            elif other in seeds:
                other_key, other_columns, label = f"seed:{other}", seeds[other], other
            else:
                section.not_converted(subject, f"It compares with {other}, which did not convert.")
                return
        else:
            if not match.group(5):
                section.not_converted(subject, "Its source() names no table.")
                return
            need, other_columns = need_for(match.group(3), match.group(5))
            if other_columns is None:
                section.not_converted(subject, f"It compares with {need.what}; choose the dataset that holds it.")
                return
            other_key, label = need.key, f"{match.group(3)}.{match.group(5)}"
        if field_name not in other_columns:
            section.not_converted(subject, f"{label} has no column {field_name}.")
            return
        # dbt's own test: the child's values, not empty, that the parent does not have.
        sql = (f"select child.{_ident(column)} as from_field from __pw_child__ child left join __pw_parent__ parent "
               f"on child.{_ident(column)} = parent.{_ident(field_name)} where child.{_ident(column)} is not null "
               f"and parent.{_ident(field_name)} is null")
        _failing_rows(conversion, section, subject, sql, {
            "__pw_child__": dataset_table(model_name, reads, made_columns.get(model_name) or {}),
            "__pw_parent__": dataset_table(label, other_key, other_columns)},
            f"test · {model_name}.{column} is in {label}.{field_name}", f"{model_name}: {column} is found in {label}",
            severity, tests, [reads],
            f"The dbt test relationships on {model_name}.{column}: its rows are the values the other table "
            "does not have.")
        return
    section.not_converted(subject, f"{test_name} is not a test this converts: not_null, unique, accepted_values, "
                                   "relationships, dbt_utils.accepted_range and "
                                   "dbt_utils.unique_combination_of_columns are, and tests written as SQL.")


def _table_test(conversion, section, subject, reads, model_name, columns, test_name, arguments,
                tests: _Tests) -> None:
    severity, problem = _severity(arguments)
    if problem:
        section.not_converted(subject, problem)
        return
    if test_name == "dbt_utils.unique_combination_of_columns":
        combination = [str(c) for c in arguments.get("combination_of_columns") or []]
        missing = [c for c in combination if c not in columns]
        if not combination or missing:
            section.not_converted(subject, f"The model has no column {missing[0]}." if missing else
                                  "It names no columns.")
            return
        key = f"check:{model_name}.{'_'.join(combination)}.unique_combination"
        words = f"{', '.join(combination)} together have no repeats"
        # dbt_utils groups by the columns, where empty values group together, as this check counts them.
        conversion.checks.append(CheckPlan(key=key, name=f"{model_name}: {words}"[:160], reads=reads,
                                           rule_type="unique", config={"columns": combination}, severity=severity,
                                           description=f"The dbt test {test_name} on {model_name}."))
        tests.checks.setdefault(reads, []).append(key)
        section.converted(subject, f"The check “{model_name}: {words}”")
        return
    section.not_converted(subject, f"{test_name} is not a test this converts on a whole model.")


def _failing_rows(conversion, section, subject, sql, tables, recipe_name, check_words, severity, tests: _Tests,
                  of: list[str], description: str) -> None:
    """A test as dbt runs it: a query of the failing rows, which passes when it has none."""
    key = f"test:{len([r for r in conversion.recipes if r.key.startswith('test:') and '·' not in r.key]) + 1}"
    try:
        chain, compiler = compile_model(parse(sql, recipe_name), scope=Scope(tables=tables), owner=recipe_name,
                                        owner_key=key, parameters={})
    except NotConverted as exc:
        section.not_converted(subject, exc.reason)
        return
    conversion.recipes.extend(compiler.helpers)
    conversion.recipes.append(RecipePlan(key=key, name=recipe_name[:160], reads=chain.base, steps=chain.steps,
                                         columns=chain.columns, description=description))
    check_key = f"check:{key}"
    conversion.checks.append(CheckPlan(key=check_key, name=check_words[:160], reads=key, rule_type="row_count",
                                       config={"max": 0}, severity=severity,
                                       description="It passes when the test's recipe finds no failing rows."))
    tests.recipes[key] = (check_key, of)
    section.converted(subject, [f"The recipe “{recipe_name}”, step {i}: {line}"
                                for i, line in enumerate(chain.lines, start=1)]
                      + [f"The check “{check_words}”: the recipe's result has no rows"])


def _source_tests(conversion: Conversion, sources, need_for, tests: _Tests) -> None:
    """Tests on sources: checks on the datasets, run before what reads them, as dbt build does."""
    for (source, table), declared in sorted(sources.items()):
        found = [(column, test) for column in declared.get("columns") or [] if isinstance(column, dict)
                 for test in _tests_of(column)]
        if not found:
            continue
        section = conversion.section(f"source {source}.{table}")
        need, columns = need_for(source, table)
        for column_props, (test_name, arguments) in found:
            column = str(column_props.get("name"))
            subject = f"test {test_name} on {source}.{table}.{column}"
            if columns is None:
                section.not_converted(subject, f"It tests {need.what}; choose the dataset that holds it.")
            elif test_name not in ("not_null", "unique", "accepted_values"):
                section.not_converted(subject, "On a source this converts not_null, unique and accepted_values.")
            else:
                _column_test(conversion, section, subject, need.key, f"{source}.{table}", column, test_name,
                             arguments, {}, {}, need_for, tests)


def _singular_test(conversion, path, data, variables, made_columns, seeds, models, need_for, tests: _Tests) -> None:
    test_name = posixpath.splitext(posixpath.basename(path))[0]
    section = conversion.section(path)
    subject = f"test {test_name}"
    try:
        rendered = render(data.decode("utf-8", errors="replace"), variables=variables, what=f"The test {test_name}")
    except NotConverted as exc:
        section.not_converted(subject, exc.reason)
        return
    tables, waiting = _tables(rendered, made_columns, seeds, models, need_for)
    if waiting:
        section.not_converted(subject, waiting)
        return
    severity, problem = _severity(rendered.config)
    if problem:
        section.not_converted(subject, problem)
        return
    of = [table.dataset for table in tables.values() if table.dataset and table.dataset.startswith("model:")]
    _failing_rows(conversion, section, subject, rendered.sql, tables, f"test · {test_name}",
                  f"{test_name} finds no rows", severity, tests, of,
                  f"The dbt test {test_name}: its rows are the ones that fail it.")


def _ident(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'
