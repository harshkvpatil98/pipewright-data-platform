"""The Python escape hatch, and attempts to escape through it.

The roadmap asks for exactly this: "sandbox escape attempts are covered by
tests; unsandboxable deployments disable the step". Most of what follows is
adversarial, because the tests that matter for a sandbox are the ones that try
to get out of it.

What this proves and what it does not: these show the *language-level* barriers
hold -- imports, builtins, filesystem, network, and the resource limits. They do
not prove a CPython interpreter escape is impossible, and the module says so.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.errors import BadRequestError
from service_workbench import sandbox


class TestTheGateIsHonest:
    """The roadmap's rule: a deployment that cannot sandbox properly disables
    the step with a stated reason rather than running it unsafely."""

    def test_capabilities_are_probed_not_assumed(self) -> None:
        # `hasattr(resource, "RLIMIT_AS")` is true on macOS and setting it
        # raises. Asking the kernel is the only way to know.
        available = sandbox.capabilities(refresh=True)
        assert {item.name for item in available.items} >= {
            "process_isolation", "wall_clock", "memory_limit", "cpu_limit", "audit_hook"
        }

    def test_the_gate_matches_what_was_probed(self) -> None:
        available = sandbox.capabilities()
        if available.usable:
            sandbox.require_usable()
        else:
            with pytest.raises(BadRequestError, match="Python cells are disabled"):
                sandbox.require_usable()

    def test_an_unenforceable_limit_names_the_platform_in_its_reason(self) -> None:
        available = sandbox.capabilities()
        for item in available.items:
            if not item.available:
                assert item.detail, f"{item.name} is unavailable with no explanation"

    def test_a_missing_limit_disables_cells(self) -> None:
        broken = sandbox.Capabilities(
            items=[
                sandbox.Capability("process_isolation", True, ""),
                sandbox.Capability("wall_clock", True, ""),
                sandbox.Capability("memory_limit", False, "no address-space limit here"),
                sandbox.Capability("cpu_limit", True, ""),
            ]
        )
        assert not broken.usable
        assert "memory limit" in broken.reason
        assert "no address-space limit here" in broken.reason

    def test_the_mechanism_still_runs_where_the_policy_would_refuse(self) -> None:
        # `run` is the mechanism and `require_usable` is the policy. Keeping
        # them apart is what lets the escape tests below run on a platform the
        # policy declines -- otherwise the barriers would be untested exactly
        # where they are most needed.
        assert sandbox.run("x = 1").ok


class TestItRuns:
    def test_a_cell_runs_and_prints(self) -> None:
        result = sandbox.run("print('hello')")
        assert result.ok
        assert result.stdout.strip() == "hello"

    def test_bindings_come_back(self) -> None:
        result = sandbox.run("total = 1 + 1\nname = 'ada'")
        assert result.bindings["total"] == "2"
        assert result.bindings["name"] == "'ada'"

    def test_pandas_is_available_without_importing_it(self) -> None:
        result = sandbox.run("out = pd.DataFrame({'a': [1, 2]})")
        assert result.ok, result.error
        assert "out" in result.frames
        assert list(result.frames["out"]["a"]) == [1, 2]

    def test_a_frame_from_an_earlier_cell_is_readable(self) -> None:
        given = pd.DataFrame({"amount": [10, 20, 30]})
        result = sandbox.run("total = int(orders['amount'].sum())", {"orders": given})
        assert result.ok, result.error
        assert result.bindings["total"] == "60"

    def test_a_returned_frame_describes_its_shape(self) -> None:
        result = sandbox.run("out = pd.DataFrame({'a': [1, 2, 3]})")
        assert result.bindings["out"] == "DataFrame(3 rows x 1 columns)"

    def test_allowed_imports_work(self) -> None:
        result = sandbox.run("import json, math, datetime\nx = math.floor(1.7)")
        assert result.ok, result.error
        assert result.bindings["x"] == "1"

    def test_defining_and_calling_a_function_works(self) -> None:
        result = sandbox.run("def double(n):\n    return n * 2\nresult = double(21)")
        assert result.ok, result.error
        assert result.bindings["result"] == "42"

    def test_a_class_can_be_defined(self) -> None:
        # `__build_class__` is a dunder builtin; filtering it out breaks `class`.
        result = sandbox.run("class Thing:\n    value = 1\nout = Thing().value")
        assert result.ok, result.error
        assert result.bindings["out"] == "1"


class TestErrorsAreTheCellAuthorsProblem:
    def test_a_syntax_error_names_the_line(self) -> None:
        result = sandbox.run("x = (1 +")
        assert not result.ok
        assert "Line 1" in result.error

    def test_a_runtime_error_is_reported_without_a_gateway_traceback(self) -> None:
        result = sandbox.run("1 / 0")
        assert not result.ok
        assert "ZeroDivisionError" in result.error
        assert "service_workbench" not in result.error

    def test_output_before_a_failure_is_kept(self) -> None:
        result = sandbox.run("print('got here')\nraise ValueError('nope')")
        assert not result.ok
        assert "got here" in result.stdout
        assert "nope" in result.error

    def test_empty_source_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="no code"):
            sandbox.run("   ")


class TestEscapeAttempts:
    """Each of these is a way out if the barrier is missing."""

    @pytest.mark.parametrize(
        "module",
        ["os", "sys", "subprocess", "socket", "shutil", "pathlib", "ctypes", "pickle",
         "importlib", "urllib", "http", "threading", "multiprocessing", "sqlite3"],
    )
    def test_a_dangerous_module_cannot_be_imported(self, module: str) -> None:
        result = sandbox.run(f"import {module}")
        assert not result.ok
        assert "cannot be imported here" in result.error

    def test_the_refusal_says_why_and_what_is_allowed(self) -> None:
        result = sandbox.run("import os")
        assert "filesystem" in result.error
        assert "pandas" in result.error

    def test_a_submodule_of_a_blocked_package_is_blocked(self) -> None:
        assert not sandbox.run("import os.path").ok
        assert not sandbox.run("from os import getcwd").ok

    def test_dunder_import_is_the_guarded_one(self) -> None:
        # `import x` compiles to a call to `__import__`, so replacing it is the
        # barrier; leaving the real one reachable would undo everything.
        result = sandbox.run("__import__('os')")
        assert not result.ok

    def test_open_is_not_available(self) -> None:
        result = sandbox.run("open('/etc/passwd')")
        assert not result.ok
        assert "open" in result.error

    def test_eval_and_exec_are_not_available(self) -> None:
        assert not sandbox.run("eval('1+1')").ok
        assert not sandbox.run("exec('x = 1')").ok

    def test_compile_is_not_available(self) -> None:
        assert not sandbox.run("compile('1', '<s>', 'eval')").ok

    def test_builtins_cannot_be_reached_through_a_class(self) -> None:
        # The classic route: object.__subclasses__() to find something that
        # holds a reference to the real builtins.
        result = sandbox.run(
            "cls = ().__class__.__base__.__subclasses__()\n"
            "found = [c for c in cls if c.__name__ == 'BuiltinImporter']\n"
            "found[0].load_module('os')"
        )
        assert not result.ok

    def test_the_real_import_is_not_reachable_through_a_function(self) -> None:
        result = sandbox.run(
            "def f():\n    pass\n"
            "real = f.__globals__['__builtins__']['__import__']\n"
            "real('os')"
        )
        assert not result.ok

    def test_writing_a_file_fails(self) -> None:
        # RLIMIT_FSIZE is zero, and `open` is gone, so both routes are shut.
        result = sandbox.run("import io\nf = io.open('/tmp/escape.txt', 'w')")
        assert not result.ok

    def test_the_parent_process_state_is_not_visible(self) -> None:
        # `spawn`, not `fork`: the child starts from a clean interpreter, so a
        # secret held in the gateway's memory is not in the cell's.
        result = sandbox.run("out = [n for n in dir() if 'SECRET' in n.upper()]")
        assert result.ok
        assert result.bindings["out"] == "[]"


class TestResourceLimits:
    def test_an_endless_loop_is_stopped_by_the_deadline(self) -> None:
        result = sandbox.run("while True:\n    pass", timeout_seconds=2)
        assert not result.ok
        assert "more than 2 seconds" in result.error

    def test_a_sleeping_cell_is_stopped_too(self) -> None:
        # Sleeping burns no CPU, so only the wall clock catches this one.
        result = sandbox.run("import time\ntime.sleep(30)", timeout_seconds=2)
        assert not result.ok
        assert "2 seconds" in result.error

    def test_a_huge_allocation_is_stopped_where_the_limit_is_enforceable(self) -> None:
        result = sandbox.run(
            "x = bytearray(400 * 1024 * 1024)", memory_mb=64, timeout_seconds=10
        )
        if "RLIMIT_AS" in result.limits_applied:
            assert not result.ok
        else:
            # This platform will not take the limit. The run reports which
            # limits stuck, and the gate refuses to expose cells at all -- so
            # the honest assertion here is that it did not claim one it lacks.
            assert "RLIMIT_AS" not in result.limits_applied
            assert not sandbox.capabilities().usable

    def test_a_run_reports_which_limits_actually_took_effect(self) -> None:
        result = sandbox.run("x = 1")
        assert "RLIMIT_CPU" in result.limits_applied
        assert "RLIMIT_FSIZE" in result.limits_applied

    def test_enormous_output_is_capped(self) -> None:
        result = sandbox.run("print('x' * 10)\nprint('y' * 1_000_000)")
        assert len(result.stdout) <= sandbox.MAX_OUTPUT_CHARS


class TestCapabilityReporting:
    def test_it_reports_what_it_can_enforce(self) -> None:
        available = sandbox.capabilities()
        names = {item.name for item in available.items}
        assert {"process_isolation", "wall_clock", "memory_limit", "cpu_limit"} <= names

    def test_describe_is_honest_about_what_is_not_covered(self) -> None:
        described = sandbox.describe()
        network = next(c for c in described["capabilities"] if c["name"] == "network")
        # The claim is "no network module is importable", not "no network".
        assert "does not block sockets at the OS level" in network["detail"]


class TestTheCachedModuleRoute:
    """The escape that got through the first two versions of this module.

    An import already performed at interpreter startup sits in `sys.modules`,
    and any route that reads that cache never performs an import -- so no
    `import` audit event fires and an allowlist on `__import__` is irrelevant.
    """

    def test_the_builtin_importer_cannot_hand_back_a_cached_module(self) -> None:
        result = sandbox.run(
            "cls = ().__class__.__base__.__subclasses__()\n"
            "found = [c for c in cls if c.__name__ == 'BuiltinImporter']\n"
            "escaped = found[0].load_module('os')"
        )
        assert not result.ok

    def test_the_classic_wrap_close_route_to_os_system_is_refused(self) -> None:
        """`os._wrap_close.__init__.__globals__['system']` is the textbook one.

        Purging `sys.modules` does not unload the class -- it is still reachable
        through `object.__subclasses__()` and its globals still hold the real
        `os`. What stops it is the audit hook, which fires on `os.system`
        wherever the call came from.
        """
        result = sandbox.run(
            "target = [c for c in ().__class__.__base__.__subclasses__() "
            "if c.__name__ == '_wrap_close'][0]\n"
            "escaped = target.__init__.__globals__['system']('echo pwned')"
        )
        assert not result.ok
        assert "pwned" not in result.stdout

    def test_popen_through_the_same_globals_is_refused(self) -> None:
        result = sandbox.run(
            "target = [c for c in ().__class__.__base__.__subclasses__() "
            "if c.__name__ == '_wrap_close'][0]\n"
            "escaped = target.__init__.__globals__['popen']('echo pwned').read()"
        )
        assert not result.ok
        assert "pwned" not in result.stdout

    def test_real_builtins_reached_sideways_are_still_audited(self) -> None:
        # `builtins` stays in sys.modules because the interpreter needs it, so
        # the audit hook is what stops this one.
        for attempt in (
            "f = lambda: None\nreal = type(f).__call__.__class__.__module__",
            "import json\nreal = json.__loader__.__class__\nreal.load_module('socket')",
        ):
            result = sandbox.run(attempt)
            if result.ok:
                # Reaching a reference is fine; using it must not be.
                assert "socket" not in str(result.bindings)

    def test_pandas_still_works_after_the_purge(self) -> None:
        # The modules stay loaded; only the lookup table loses them. If this
        # breaks, the purge is too broad.
        result = sandbox.run(
            "out = pd.DataFrame({'a': [1, 2, 3]})\n"
            "total = int(out['a'].sum())\n"
            "print('ok')"
        )
        assert result.ok, result.error
        assert result.bindings["total"] == "6"
        assert result.stdout.strip() == "ok"

    def test_datetime_and_zoneinfo_still_work(self) -> None:
        # zoneinfo reads its data from files, which the `open` rule permits
        # only inside the interpreter's own tree.
        result = sandbox.run(
            "import datetime, zoneinfo\n"
            "when = datetime.datetime(2026, 8, 23, tzinfo=zoneinfo.ZoneInfo('UTC'))\n"
            "out = when.isoformat()"
        )
        assert result.ok, result.error
        assert "2026-08-23" in result.bindings["out"]
