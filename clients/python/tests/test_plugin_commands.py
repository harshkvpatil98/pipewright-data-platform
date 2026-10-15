"""``pipewright plugin new`` and ``pipewright plugin check`` (X1): no server needed."""

from __future__ import annotations

import json

from pipewright.cli import main


def test_new_writes_a_plugin_that_check_passes(tmp_path, capsys) -> None:
    assert main(["plugin", "new", "starter", "--into", str(tmp_path), "--publisher", "Ana"]) == 0
    assert (tmp_path / "starter" / "plugin.py").is_file()
    capsys.readouterr()
    assert main(["plugin", "check", str(tmp_path / "starter")]) == 0
    out = capsys.readouterr().out
    assert "starter 0.1.0: passes. It adds: tool starter.initials" in out and "FAIL" not in out


def test_check_says_what_fails_and_exits_two(tmp_path, capsys) -> None:
    main(["plugin", "new", "starter", "--into", str(tmp_path)])
    source = tmp_path / "starter" / "starter_plugin" / "__init__.py"
    source.write_text(source.read_text().replace('expect=("AL", "GBH")', 'expect=("AL", "XYZ")'))
    capsys.readouterr()
    assert main(["--json", "plugin", "check", str(tmp_path / "starter")]) == 2
    report = json.loads(capsys.readouterr().out)
    [failure] = [item for item in report["checks"] if not item["passed"]]
    assert failure["name"] == "its example gives what it says" and "not 'XYZ'" in failure["detail"]


def test_new_will_not_write_over_a_plugin_and_check_refuses_what_does_not_load(tmp_path, capsys) -> None:
    main(["plugin", "new", "starter", "--into", str(tmp_path)])
    assert main(["plugin", "new", "starter", "--into", str(tmp_path)]) == 1
    assert main(["plugin", "check", "no_such_module:plugin"]) == 1
    assert "It does not load: ModuleNotFoundError" in capsys.readouterr().err
