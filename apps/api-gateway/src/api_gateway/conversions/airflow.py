"""An Airflow DAG file to a workflow, recipes and checks (E2, X3).

The file is read with Python's own parser and never run, as Airflow's
published DAG format has it: ``with DAG(...)`` (or ``dag = DAG(...)``),
operators assigned to names, ``TaskGroup``s, and dependencies written with
``>>``, ``<<``, lists, ``chain()``, ``cross_downstream()``,
``set_downstream()`` and ``set_upstream()``. What it finds:

- the DAG becomes a workflow: its cron schedule (or preset), the time zone of
  its start date, and each task's retries and retry delay (from
  ``default_args`` too);
- a SQL task (``SQLExecuteQueryOperator`` and the database-specific ones)
  that makes a table from a SELECT (``CREATE [OR REPLACE] TABLE … AS``,
  ``CREATE VIEW … AS``, ``INSERT OVERWRITE``) becomes a recipe making that
  table, read by the tasks after it that name the table; a table no task
  makes is a dataset the project has, matched by name or chosen;
- ``SQLColumnCheckOperator`` and ``SQLTableCheckOperator`` become checks and
  a quality gate; an empty task (``EmptyOperator``) is a link, nothing more.

Everything else runs code or acts on something outside (Python, a shell, a
container, a sensor, an email, another DAG), which this does not run, and
says so task by task. A task left out keeps the order of the tasks around
it, and a workflow with any task left out is made to start by hand, with its
schedule in the report, so it never runs on time with a step missing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from shared_python.words import count_of

from api_gateway.conversions.model import (
    CheckPlan,
    Conversion,
    LinkPlan,
    NotConverted,
    RecipePlan,
    TaskPlan,
    WorkflowPlan,
)
from api_gateway.conversions.sql import Scope, compile_model, dataset_table, parameter_for

_UNKNOWN = object()
_PRESETS = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
            "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}
_SQL_OPERATORS = {"SQLExecuteQueryOperator", "PostgresOperator", "MySqlOperator", "MsSqlOperator",
                  "SnowflakeOperator", "RedshiftSQLOperator", "SqliteOperator", "TrinoOperator", "OracleOperator",
                  "DatabricksSqlOperator", "VerticaOperator", "JdbcOperator", "DruidOperator", "ExasolOperator"}
_FAMILIES = [
    (("PythonOperator", "BranchPythonOperator", "ShortCircuitOperator", "PythonVirtualenvOperator",
      "ExternalPythonOperator", "PythonSensor", "BranchDayOfWeekOperator"),
     "It runs Python code, which this reads and never runs."),
    (("BashOperator", "SSHOperator", "DockerOperator", "KubernetesPodOperator", "EcsRunTaskOperator"),
     "It runs a command or a container, which a workflow here does not run."),
    (("EmailOperator",), "It sends an email; a workflow here tells people with a notification in the app, which "
                         "is not the same thing, so it is not converted."),
    (("TriggerDagRunOperator", "ExternalTaskSensor", "ExternalTaskMarker"),
     "It starts or waits for another workflow, which this file does not hold."),
    (("SimpleHttpOperator", "HttpOperator", "HttpSensor"), "It calls a web service, which a workflow here does not "
                                                           "do."),
]


@dataclass
class _Task:
    task_id: str
    operator: str
    call: ast.Call
    group: str | None
    line: int
    upstream: list[str] = field(default_factory=list)


def convert_airflow(files: dict[str, bytes], lookup) -> Conversion:
    (name, data), = files.items()
    try:
        tree = ast.parse(data.decode("utf-8", errors="replace"), filename=name)
    except SyntaxError as exc:
        raise NotConverted(f"{name} is not Python this can read: {exc.msg} on line {exc.lineno}.") from exc
    reader = _Reader(name)
    reader.read(tree)
    if reader.dag is None:
        raise NotConverted(f"{name} defines no workflow (with DAG(...) as dag, dag = DAG(...) or @dag).")
    return reader.convert(lookup)


class _Reader:
    """Walks the module, keeping the literal values it can read without running anything."""

    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        self.values: dict[str, Any] = {}
        self.dag: dict[str, Any] | None = None
        self.dag_name: str | None = None
        self.tasks: dict[str, _Task] = {}
        self.by_variable: dict[str, list[str]] = {}
        self.groups: dict[str, list[str]] = {}
        self.edges: list[tuple[str, str]] = []
        self.problems: list[tuple[str, str]] = []
        self.decorated: list[tuple[str, int]] = []
        #: A name an import gave something else: Q for SQLExecuteQueryOperator.
        self.aliases: dict[str, str] = {}

    # --------------------------------------------------------------- values

    def value(self, node: ast.AST) -> Any:
        """A literal, worked out without running anything; _UNKNOWN when it needs code."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [self.value(item) for item in node.elts]
            return _UNKNOWN if any(item is _UNKNOWN for item in items) else items
        if isinstance(node, ast.Dict):
            out = {}
            for key, item in zip(node.keys, node.values):
                if key is None:
                    spread = self.value(item)
                    if not isinstance(spread, dict):
                        return _UNKNOWN
                    out.update(spread)
                    continue
                k, v = self.value(key), self.value(item)
                if k is _UNKNOWN or v is _UNKNOWN:
                    return _UNKNOWN
                out[k] = v
            return out
        if isinstance(node, ast.Name):
            return self.values.get(node.id, _UNKNOWN)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.value(node.left), self.value(node.right)
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            return _UNKNOWN
        if isinstance(node, ast.JoinedStr):
            parts = []
            for part in node.values:
                if isinstance(part, ast.Constant):
                    parts.append(str(part.value))
                elif isinstance(part, ast.FormattedValue) and isinstance(self.value(part.value), (str, int, float)):
                    parts.append(str(self.value(part.value)))
                else:
                    return _UNKNOWN
            return "".join(parts)
        if isinstance(node, ast.Call):
            called = self.called(node)
            if called == "timedelta":
                units = {"weeks": 604800, "days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}
                total = 0.0
                for keyword in node.keywords:
                    amount = self.value(keyword.value)
                    if keyword.arg not in units or not isinstance(amount, (int, float)):
                        return _UNKNOWN
                    total += amount * units[keyword.arg]
                for index, arg in enumerate(node.args[:1]):
                    amount = self.value(arg)
                    if not isinstance(amount, (int, float)):
                        return _UNKNOWN
                    total += amount * 86400
                return {"__seconds__": total}
            if called in ("datetime", "pendulum.datetime", "datetime.datetime"):
                zone = next((self.value(k.value) for k in node.keywords if k.arg in ("tz", "tzinfo")), None)
                if isinstance(zone, dict) and "__zone__" in zone:
                    zone = zone["__zone__"]
                return {"__start__": True, "__zone__": zone if isinstance(zone, str) else None}
            if called in ("pendulum.timezone", "timezone"):
                zone = self.value(node.args[0]) if node.args else None
                return {"__zone__": zone} if isinstance(zone, str) else _UNKNOWN
        return _UNKNOWN

    # ---------------------------------------------------------------- walk

    def read(self, module: ast.Module) -> None:
        for node in ast.walk(module):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.asname:
                        self.aliases[alias.asname] = alias.name.split(".")[-1] if isinstance(
                            node, ast.ImportFrom) else alias.name
        for statement in module.body:
            self.statement(statement, group=None, in_dag=False)

    def called(self, call: ast.Call) -> str:
        """What a call calls, through any name an import gave it."""
        name = _called(call)
        head, _, rest = name.partition(".")
        head = self.aliases.get(head, head)
        return f"{head}.{rest}" if rest else head

    def statement(self, node: ast.stmt, *, group: str | None, in_dag: bool) -> None:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if isinstance(node.value, ast.Call) and self.called(node.value) in ("DAG", "models.DAG"):
                self._dag(node.value)
                return
            if isinstance(node.value, ast.Call) and self._is_task(node.value):
                self.by_variable[target] = [self._task(node.value, group, node.lineno)]
                return
            if isinstance(node.value, ast.Call) and self.called(node.value) == "TaskGroup":
                self.by_variable[target] = [f"group:{self._group_id(node.value, group)}"]
                return
            literal = self.value(node.value)
            if literal is not _UNKNOWN:
                self.values[target] = literal
            elif isinstance(node.value, ast.BinOp) and self._is_dependency(node.value):
                self._dependency(node.value)
            return
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and self.called(call) in ("DAG", "models.DAG"):
                    self._dag(call)
                    for inner in node.body:
                        self.statement(inner, group=group, in_dag=True)
                    return
                if isinstance(call, ast.Call) and self.called(call) == "TaskGroup":
                    group_id = self._group_id(call, group)
                    if item.optional_vars is not None and isinstance(item.optional_vars, ast.Name):
                        self.by_variable[item.optional_vars.id] = [f"group:{group_id}"]
                    self.groups.setdefault(group_id, [])
                    for inner in node.body:
                        self.statement(inner, group=group_id, in_dag=True)
                    return
            for inner in node.body:
                self.statement(inner, group=group, in_dag=in_dag)
            return
        if isinstance(node, ast.Expr):
            value = node.value
            if isinstance(value, ast.Call) and self._is_task(value):
                self._task(value, group, node.lineno)
            elif isinstance(value, ast.BinOp) and self._is_dependency(value):
                self._dependency(value)
            elif isinstance(value, ast.Call) and self.called(value) in ("chain", "cross_downstream"):
                self._chain(value)
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and \
                    value.func.attr in ("set_downstream", "set_upstream"):
                self._set(value)
            return
        if isinstance(node, (ast.For, ast.While, ast.If)) and in_dag:
            self.problems.append((f"line {node.lineno}", "Tasks or links made in a loop or under a condition are "
                                                         "code that runs; this reads them only when written out."))
            return
        if isinstance(node, ast.FunctionDef):
            names = {_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
                     for decorator in node.decorator_list}
            if names & {"dag", "DAG"}:
                decorator = next(d for d in node.decorator_list if _name(d.func if isinstance(d, ast.Call) else d)
                                 in ("dag", "DAG"))
                self._dag(decorator if isinstance(decorator, ast.Call) else ast.Call(func=decorator, args=[],
                                                                                      keywords=[]),
                          default_id=node.name)
                for inner in node.body:
                    self.statement(inner, group=group, in_dag=True)
            elif names & {"task", "task.python", "task.branch", "task.bash", "task.virtualenv", "task.docker"}:
                self.decorated.append((node.name, node.lineno))

    def _dag(self, call: ast.Call, default_id: str | None = None) -> None:
        settings = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        dag_id = self.value(call.args[0]) if call.args else self.value(settings.get("dag_id", ast.Constant(None)))
        self.dag_name = dag_id if isinstance(dag_id, str) else default_id or "dag"
        self.dag = settings

    def _group_id(self, call: ast.Call, parent: str | None) -> str:
        raw = self.value(call.args[0]) if call.args else self.value(
            next((k.value for k in call.keywords if k.arg == "group_id"), ast.Constant(None)))
        group_id = str(raw) if isinstance(raw, str) else f"group_{call.lineno}"
        return f"{parent}.{group_id}" if parent else group_id

    def _is_task(self, call: ast.Call) -> bool:
        return any(keyword.arg == "task_id" for keyword in call.keywords) and self.called(call) != "TaskGroup"

    def _task(self, call: ast.Call, group: str | None, line: int) -> str:
        raw = self.value(next(k.value for k in call.keywords if k.arg == "task_id"))
        task_id = str(raw) if isinstance(raw, str) else f"task_{line}"
        full = f"{group}.{task_id}" if group else task_id
        self.tasks[full] = _Task(full, self.called(call).split(".")[-1], call, group, line)
        node = group
        while node:
            self.groups.setdefault(node, []).append(full)
            node = node.rsplit(".", 1)[0] if "." in node else None
        return full

    # --------------------------------------------------------- dependencies

    def _is_dependency(self, node: ast.AST) -> bool:
        return isinstance(node, ast.BinOp) and isinstance(node.op, (ast.RShift, ast.LShift))

    def _members(self, node: ast.AST) -> list[str] | None:
        """The tasks (or groups) an expression in a dependency names."""
        if isinstance(node, ast.Name):
            return self.by_variable.get(node.id)
        if isinstance(node, (ast.List, ast.Tuple)):
            found = []
            for item in node.elts:
                members = self._members(item)
                if members is None:
                    return None
                found.extend(members)
            return found
        if isinstance(node, ast.Call) and self._is_task(node):
            return [self._task(node, None, node.lineno)]
        return None

    def _dependency(self, node: ast.BinOp) -> list[str] | None:
        """Links from a >> b >> c (or <<); returns the rightmost members."""
        left = self._dependency(node.left) if self._is_dependency(node.left) else self._members(node.left)
        right = self._members(node.right)
        if left is None or right is None:
            self.problems.append((f"line {node.lineno}", "A dependency names something this cannot follow without "
                                                         "running the file."))
            return right
        pairs = [(a, b) for a in left for b in right] if isinstance(node.op, ast.RShift) else \
            [(b, a) for a in left for b in right]
        self.edges.extend(pairs)
        return right

    def _chain(self, call: ast.Call) -> None:
        parts = [self._members(arg) for arg in call.args]
        if any(part is None for part in parts):
            self.problems.append((f"line {call.lineno}", f"{self.called(call)}() names what this cannot follow."))
            return
        if self.called(call) == "cross_downstream":
            if len(parts) == 2:
                self.edges.extend((a, b) for a in parts[0] for b in parts[1])
            return
        for before, after in zip(parts, parts[1:]):
            if len(before) > 1 and len(after) > 1 and len(before) != len(after):
                self.problems.append((f"line {call.lineno}", "chain() of two lists of different lengths is an "
                                                             "error in Airflow too."))
                return
            if len(before) > 1 and len(after) > 1:
                self.edges.extend(zip(before, after))
            else:
                self.edges.extend((a, b) for a in before for b in after)

    def _set(self, call: ast.Call) -> None:
        owner = self._members(call.func.value)
        others = self._members(call.args[0]) if call.args else None
        if owner is None or others is None:
            self.problems.append((f"line {call.lineno}", f"{call.func.attr}() names something this cannot follow."))
            return
        if call.func.attr == "set_downstream":
            self.edges.extend((a, b) for a in owner for b in others)
        else:
            self.edges.extend((b, a) for a in owner for b in others)

    def _expand(self, member: str, end: str) -> list[str]:
        """A group in a link means its first tasks (downstream end) or its last ones (upstream end)."""
        if not member.startswith("group:"):
            return [member]
        inside = set(self.groups.get(member.removeprefix("group:"), []))
        inner_edges = [(a, b) for a, b in self._task_edges() if a in inside and b in inside]
        if end == "upstream":
            return sorted(t for t in inside if not any(a == t for a, _ in inner_edges))
        return sorted(t for t in inside if not any(b == t for _, b in inner_edges))

    def _task_edges(self) -> list[tuple[str, str]]:
        return [(a, b) for a, b in self.edges if not a.startswith("group:") and not b.startswith("group:")]

    def links(self) -> list[tuple[str, str]]:
        found = []
        for a, b in self.edges:
            for x in self._expand(a, "upstream"):
                for y in self._expand(b, "downstream"):
                    if x != y:
                        found.append((x, y))
        return list(dict.fromkeys(found))

    # ------------------------------------------------------------- convert

    def convert(self, lookup) -> Conversion:
        assert self.dag is not None
        conversion = Conversion(format="airflow", title=f"the Airflow workflow {self.dag_name}")
        overview = conversion.section(f"{self.file_name}: the workflow {self.dag_name}")
        dag = self.dag
        default_args = self.value(dag["default_args"]) if "default_args" in dag else {}
        default_args = default_args if isinstance(default_args, dict) else {}
        params = self.value(dag["params"]) if "params" in dag else {}
        if params is _UNKNOWN or not isinstance(params, dict):
            overview.not_converted("params", "Its params are worked out by code.")
            params = {}
        params = {key: (value.get("value") if isinstance(value, dict) and "value" in value else value)
                  for key, value in params.items()}
        cron, timezone, schedule_note = self._schedule(dag, overview)
        for key in ("catchup", "max_active_runs", "sla_miss_callback", "on_failure_callback", "on_success_callback"):
            if key in dag:
                words = {"catchup": "Runs for past dates are made by hand here: a workflow's Backfill.",
                         "max_active_runs": "A workflow here runs one run at a time per worker.",
                         }.get(key, "It runs Python code, which this reads and never runs.")
                (overview.nothing_to_do if key in ("catchup", "max_active_runs") else overview.not_converted)(
                    key, words)
        for problem_at, reason in self.problems:
            overview.not_converted(problem_at, reason)
        for function, line in self.decorated:
            conversion.section(f"{self.file_name}: @task {function}").not_converted(
                f"@task {function} (line {line})", "It runs Python code, which this reads and never runs.")

        tasks_out: list[TaskPlan] = []
        made: dict[str, str] = {}  # task id -> node key
        tables: dict[str, tuple[str, dict]] = {}  # table name -> (recipe key, columns)
        skipped: dict[str, str] = {}
        links = self.links()
        ordered = _in_order(list(self.tasks), links)
        for task_id in ordered:
            task = self.tasks[task_id]
            section = conversion.section(f"{self.file_name}: task {task_id}")
            subject = f"task {task_id} ({task.operator})"
            options = {keyword.arg: keyword.value for keyword in task.call.keywords if keyword.arg}
            retries = self.value(options["retries"]) if "retries" in options else default_args.get("retries", 0)
            delay = self.value(options["retry_delay"]) if "retry_delay" in options else default_args.get(
                "retry_delay")
            rule = self.value(options["trigger_rule"]) if "trigger_rule" in options else "all_success"
            if rule is _UNKNOWN and isinstance(options.get("trigger_rule"), ast.Attribute):
                rule = options["trigger_rule"].attr  # TriggerRule.ALL_DONE
            rule = rule.split(".")[-1].lower() if isinstance(rule, str) else "worked out by code"
            if rule not in ("all_success", None):
                section.not_converted(subject, f"Its trigger rule is {rule}; a task here runs when every task "
                                               "before it succeeded.")
                skipped[task_id] = "its trigger rule"
                continue
            try:
                plan = self._task_plan(task, options, conversion, lookup, tables, params, section, subject)
            except NotConverted as exc:
                section.not_converted(subject, exc.reason)
                skipped[task_id] = exc.reason
                continue
            if plan is None:
                continue
            plan.retries = int(retries) if isinstance(retries, int) else 0
            if isinstance(delay, dict) and "__seconds__" in delay:
                plan.retry_delay_seconds = max(1, int(delay["__seconds__"]))
            plan.node_key = _node_key(task_id, tasks_out)
            tasks_out.append(plan)
            made[task_id] = plan.node_key

        # Links between the tasks that converted; one left out keeps the order around it.
        out_links: list[LinkPlan] = []
        for a in made:
            for b in _reachable_through(a, links, set(made)):
                out_links.append(LinkPlan(made[a], made[b]))
        sections = {section.title: section for section in conversion.sections}
        for a, b in links:
            if a in skipped and b in made:
                entries = sections[f"{self.file_name}: task {b}"].entries
                entries[-1].notes.append(f"In Airflow it waited for {a}, which did not convert; here it follows "
                                         f"what {a} followed.")
        complete = not skipped and not self.problems and not self.decorated
        if tasks_out:
            trigger = "cron" if cron and complete else "manual"
            description = str(self.value(dag["description"])) if "description" in dag and isinstance(
                self.value(dag["description"]), str) else f"The Airflow workflow {self.dag_name}."
            conversion.workflows.append(WorkflowPlan(
                key="workflow:dag", name=str(self.dag_name)[:160], description=description[:2000], tasks=tasks_out,
                links=_unique(out_links), trigger_type=trigger, cron_expression=cron if trigger == "cron" else None,
                timezone=timezone if trigger == "cron" else None, default_parameters=dict(params)))
            words = f"The workflow “{self.dag_name}”"
            if cron and not complete:
                overview.converted("the workflow", [words, f"It starts by hand: set its schedule ({cron}"
                                                      f"{', ' + timezone if timezone else ''}) once what did not "
                                                      "convert is done here."])
            else:
                overview.converted("the workflow", [words, schedule_note] if schedule_note else words)
        else:
            overview.not_converted("the workflow", "None of its tasks converted, so there is no workflow to make.")
        conversion.notes.append("The file is read, never run: no Python of it ran here.")
        return conversion

    def _schedule(self, dag: dict[str, ast.AST], overview) -> tuple[str | None, str | None, str | None]:
        node = dag.get("schedule", dag.get("schedule_interval", dag.get("timetable")))
        start = self.value(dag["start_date"]) if "start_date" in dag else None
        timezone = None
        if isinstance(start, dict) and start.get("__start__"):
            timezone = start.get("__zone__") or "UTC"
        if node is None:
            return None, timezone, None
        value = self.value(node)
        if value is None:
            overview.converted("schedule", "None: it starts by hand")
            return None, timezone, None
        if isinstance(value, str) and value in _PRESETS:
            overview.converted("schedule", f"{value}: the schedule {_PRESETS[value]}{', ' + timezone if timezone else ''}")
            return _PRESETS[value], timezone, None
        if isinstance(value, str) and value == "@once":
            overview.not_converted("schedule", "@once runs it a single time, which a schedule here does not do; it "
                                               "starts by hand.")
            return None, timezone, None
        if isinstance(value, str) and len(value.split()) == 5:
            overview.converted("schedule", f"The schedule {value}{', ' + timezone if timezone else ''}")
            return value, timezone, None
        if isinstance(value, dict) and "__seconds__" in value:
            overview.not_converted("schedule", "It runs every so often from its start (a timedelta), where a "
                                               "schedule here is a timetable of days and times; it starts by hand.")
            return None, timezone, None
        overview.not_converted("schedule", "Its schedule is worked out by code (a timetable or a dataset), which "
                                           "this does not run; it starts by hand.")
        return None, timezone, None

    def _task_plan(self, task: _Task, options, conversion: Conversion, lookup, tables, params, section,
                   subject) -> TaskPlan | None:
        operator = task.operator
        if operator in ("EmptyOperator", "DummyOperator"):
            section.nothing_to_do(subject, "It does nothing; the tasks after it follow the tasks before it.")
            return None
        if operator in _SQL_OPERATORS:
            return self._sql_task(task, options, conversion, lookup, tables, params, section, subject)
        if operator == "SQLColumnCheckOperator":
            return self._column_checks(task, options, conversion, lookup, tables, section, subject)
        if operator == "SQLTableCheckOperator":
            return self._table_checks(task, options, conversion, lookup, tables, section, subject)
        for names, reason in _FAMILIES:
            if operator in names:
                raise NotConverted(reason)
        if operator.endswith("Sensor"):
            raise NotConverted("It waits for something outside (a file, a table, a time), which a workflow here "
                               "does not do.")
        if "Dbt" in operator:
            raise NotConverted("It runs dbt. Convert the dbt project itself: upload its folder as a .zip.")
        raise NotConverted(f"{operator} is not an operator this converts: SQL tasks that make a table, "
                           "SQLColumnCheckOperator, SQLTableCheckOperator and EmptyOperator are.")

    # ----------------------------------------------------------------- SQL

    def _sql_of(self, options) -> str:
        raw = self.value(options["sql"]) if "sql" in options else _UNKNOWN
        if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], str):
            raw = raw[0]
        if not isinstance(raw, str):
            raise NotConverted("Its SQL is worked out by code, or is a list of statements; this converts one "
                               "statement written in the file.")
        if re.fullmatch(r"\s*[\w./-]+\.sql\s*", raw):
            raise NotConverted(f"Its SQL is in the file {raw.strip()}, which is not in this upload.")
        return raw

    def _sql_task(self, task, options, conversion, lookup, tables, params, section, subject) -> TaskPlan | None:
        import sqlglot

        exp = _sqlglot()
        text = self._sql_of(options)
        used_params: dict[str, Any] = {}

        def parameter(match: re.Match) -> str:
            name = match.group(1)
            if name not in params:
                raise NotConverted(f"Its SQL uses {{{{ params.{name} }}}}, which the workflow's params do not give.")
            used_params[name] = params[name]
            return f"__pw_parameter_{name}__"

        text = re.sub(r"\{\{\s*params\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", parameter, text)
        template = re.search(r"\{\{.*?\}\}|\{%.*?%\}", text, re.S)
        if template:
            raise NotConverted(f"Its SQL uses {template.group(0)[:40]}, a value Airflow works out for each run from "
                               "its data intervals, which runs here do not have; give it as a param instead.")
        statements = [s for s in text.split(";") if s.strip()]
        if len(statements) != 1:
            raise NotConverted(f"Its SQL has {len(statements)} statements; this converts a task of one.")
        try:
            statement = sqlglot.parse_one(statements[0])
        except Exception as exc:  # noqa: BLE001 - sqlglot names the place
            raise NotConverted(f"Its SQL cannot be read: {str(exc).splitlines()[0]}") from exc
        target, query = None, None
        if isinstance(statement, exp.Create) and statement.args.get("kind", "").upper() in ("TABLE", "VIEW") and \
                isinstance(statement.expression, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            target, query = statement.this, statement.expression
            if isinstance(target, exp.Schema):
                raise NotConverted("It names the new table's columns before AS, which this does not convert.")
        elif isinstance(statement, exp.Insert) and statement.args.get("overwrite") and isinstance(
                statement.expression, (exp.Select, exp.Union)):
            target, query = statement.this, statement.expression
        elif isinstance(statement, exp.Insert):
            raise NotConverted("It adds rows to a table (INSERT INTO), where a recipe makes its result anew each "
                               "run.")
        elif isinstance(statement, (exp.Select, exp.Union)):
            section.nothing_to_do(subject, "It runs a SELECT and keeps nothing, so there is nothing to make.")
            return None
        else:
            raise NotConverted(f"It runs {statement.key.upper()}, which changes a table in place; a recipe makes "
                               "its own result.")
        table_name = ".".join(p for p in (target.catalog, target.db, target.name) if p) if isinstance(
            target, exp.Table) else str(target)
        scope_tables, waiting = {}, None
        defined = {cte.alias.lower() for cte in query.find_all(exp.CTE)}
        for table in query.find_all(exp.Table):
            full = ".".join(p for p in (table.catalog, table.db, table.name) if p)
            if table.name.lower() in defined:
                continue
            if full.lower() in tables:
                key, columns = tables[full.lower()]
                scope_tables[full] = dataset_table(full, key, columns)
                continue
            need = conversion.need(f"table:{full.lower()}", table.name, f"the table {full}")
            columns = lookup(need)
            if columns is None:
                waiting = (f"It reads {full}. Choose the dataset that holds it (none here is called "
                           f"“{table.name}”), then read the file again.")
                break
            scope_tables[full] = dataset_table(full, need.key, columns)
        if waiting:
            raise NotConverted(waiting)
        recipe_key = f"task:{task.task_id}"
        chain, compiler = compile_model(query, scope=Scope(tables=scope_tables), owner=table_name,
                                        owner_key=recipe_key, parameters=used_params)
        conversion.recipes.extend(compiler.helpers)
        from service_transformations.parameters import used

        conversion.recipes.append(RecipePlan(
            key=recipe_key, name=table_name[:160], reads=chain.base, steps=chain.steps, columns=chain.columns,
            description=f"Makes {table_name}, as the Airflow task {task.task_id} did.",
            parameters=[parameter_for(p, used_params.get(p)) for p in sorted(used(chain.steps))]))
        tables[table_name.lower()] = (recipe_key, chain.columns)
        section.converted(subject, [f"The recipe “{table_name}”, step {i}: {line}"
                                    for i, line in enumerate(chain.lines, start=1)]
                          + [f"The task “{task.task_id}”, which runs it"])
        config: dict[str, Any] = {"pipeline_id": {"$recipe": recipe_key}}
        if used_params:
            config["parameters"] = {name: "{{ params." + name + " }}" for name in used_params}
        return TaskPlan(node_key="", name=task.task_id[:160], node_type="transformation", config=config)

    # -------------------------------------------------------------- checks

    def _checked_table(self, options, conversion, lookup, tables) -> tuple[str, str]:
        raw = self.value(options["table"]) if "table" in options else _UNKNOWN
        if not isinstance(raw, str):
            raise NotConverted("The table it checks is worked out by code.")
        if raw.lower() in tables:
            return raw, tables[raw.lower()][0]
        need = conversion.need(f"table:{raw.lower()}", raw.split(".")[-1], f"the table {raw}")
        if lookup(need) is None:
            raise NotConverted(f"It checks {raw}. Choose the dataset that holds it, then read the file again.")
        return raw, need.key

    def _column_checks(self, task, options, conversion, lookup, tables, section, subject) -> TaskPlan:
        table, reads = self._checked_table(options, conversion, lookup, tables)
        mapping = self.value(options["column_mapping"]) if "column_mapping" in options else _UNKNOWN
        if not isinstance(mapping, dict):
            raise NotConverted("Its column_mapping is worked out by code.")
        for key in ("partition_clause", "accept_none"):
            if key in options:
                raise NotConverted(f"It is set with {key}, which a check here has no setting for.")
        keys: list[str] = []
        for column, checks in mapping.items():
            for check, condition in (checks or {}).items():
                made = _column_check(table, reads, str(column), str(check), condition or {})
                if isinstance(made, str):
                    section.not_converted(f"{check} on {table}.{column}", made)
                    continue
                made.key = f"check:{task.task_id}.{column}.{check}"
                conversion.checks.append(made)
                keys.append(made.key)
                section.converted(f"{check} on {table}.{column}", f"The check “{made.name}”")
        if not keys:
            raise NotConverted("None of its checks converted.")
        section.converted(subject, f"The task “{task.task_id}”, a quality gate running {count_of(len(keys), 'check')}")
        return TaskPlan(node_key="", name=task.task_id[:160], node_type="quality_gate",
                        config={"dataset_id": {"$dataset": reads}, "rule_ids": {"$checks": keys}})

    def _table_checks(self, task, options, conversion, lookup, tables, section, subject) -> TaskPlan:
        table, reads = self._checked_table(options, conversion, lookup, tables)
        checks = self.value(options["checks"]) if "checks" in options else _UNKNOWN
        if not isinstance(checks, dict):
            raise NotConverted("Its checks are worked out by code.")
        keys = []
        for check_name, settings in checks.items():
            statement = str((settings or {}).get("check_statement") or "")
            match = re.fullmatch(r"\s*COUNT\(\s*\*\s*\)\s*(>=|>|<=|<|=|==)\s*(\d+)\s*", statement, re.I)
            if not match or (settings or {}).get("partition_clause"):
                section.not_converted(f"{check_name} on {table}", "This converts a row count (COUNT(*) compared with "
                                                                  "a number); its statement is something else.")
                continue
            sign, number = match.group(1), int(match.group(2))
            bounds = {">=": {"min": number}, ">": {"min": number + 1}, "<=": {"max": number}, "<": {"max": number - 1},
                      "=": {"min": number, "max": number}, "==": {"min": number, "max": number}}[sign]
            key = f"check:{task.task_id}.{check_name}"
            words = f"{table}: {check_name}"
            conversion.checks.append(CheckPlan(key=key, name=words[:160], reads=reads, rule_type="row_count",
                                               config=bounds, description=f"{statement.strip()}, as the Airflow task "
                                                                          f"{task.task_id} checked."))
            keys.append(key)
            section.converted(f"{check_name} on {table}", f"The check “{words}”")
        if not keys:
            raise NotConverted("None of its checks converted.")
        section.converted(subject, f"The task “{task.task_id}”, a quality gate running {count_of(len(keys), 'check')}")
        return TaskPlan(node_key="", name=task.task_id[:160], node_type="quality_gate",
                        config={"dataset_id": {"$dataset": reads}, "rule_ids": {"$checks": keys}})


def _column_check(table: str, reads: str, column: str, check: str, condition: dict) -> CheckPlan | str:
    """One of SQLColumnCheckOperator's checks as a check here, or why not."""
    extra = set(condition) - {"equal_to", "geq_to", "leq_to", "greater_than", "less_than", "tolerance"}
    if extra or condition.get("tolerance") is not None:
        return f"It is set with {', '.join(sorted(extra)) or 'tolerance'}, which a check here has no setting for."
    if check in ("null_check", "unique_check"):
        if condition != {"equal_to": 0}:
            return "This converts it compared with equal_to: 0, none of them."
        if check == "null_check":
            return CheckPlan(key="", name=f"{table}: {column} has no empty values"[:160], reads=reads,
                             rule_type="not_null", config={"column": column},
                             description=f"null_check on {column}, as Airflow checked it.")
        # Airflow counts COUNT(column) - COUNT(DISTINCT column): empty values never repeat.
        return CheckPlan(key="", name=f"{table}: {column} has no repeats"[:160], reads=reads, rule_type="unique",
                         config={"column": column, "ignore_empty": True},
                         description=f"unique_check on {column}, as Airflow checked it.")
    if check in ("min", "max"):
        if set(condition) == {"geq_to"} and check == "min":
            bound = {"min": condition["geq_to"]}
        elif set(condition) == {"leq_to"} and check == "max":
            bound = {"max": condition["leq_to"]}
        else:
            return "This converts min with geq_to and max with leq_to: a range that includes its end."
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bound.values()):
            return "Its bound is not a number."
        words = f"{column} is at least {bound['min']}" if "min" in bound else f"{column} is at most {bound['max']}"
        return CheckPlan(key="", name=f"{table}: {words}"[:160], reads=reads, rule_type="range",
                         config={"column": column, **bound}, description=f"{check} on {column}, as Airflow checked it.")
    return f"{check} is not a column check this converts: null_check, unique_check, min and max are."


def _sqlglot():
    from sqlglot import exp

    return exp


def _called(call: ast.Call) -> str:
    return _name(call.func)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _in_order(tasks: list[str], links: list[tuple[str, str]]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()

    def visit(task: str, trail: set[str]) -> None:
        if task in seen or task in trail:
            return
        for a, b in links:
            if b == task:
                visit(a, trail | {task})
        seen.add(task)
        order.append(task)

    for task in tasks:
        visit(task, set())
    return order


def _reachable_through(start: str, links: list[tuple[str, str]], kept: set[str]) -> list[str]:
    """The kept tasks after `start`, directly or through tasks that were left out."""
    found, stack, seen = [], [b for a, b in links if a == start], set()
    while stack:
        task = stack.pop()
        if task in seen:
            continue
        seen.add(task)
        if task in kept:
            found.append(task)
        else:
            stack.extend(b for a, b in links if a == task)
    return found


def _node_key(wanted: str, tasks: list[TaskPlan]) -> str:
    base = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", wanted.lower())).strip("_")[:56] or "task"
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
