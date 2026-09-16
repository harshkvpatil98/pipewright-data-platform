"""Cells of three languages sharing one namespace.

The acceptance criterion is "notebook cells share state across languages", so
these tests are mostly about the seams: SQL to Python, Python to recipe, recipe
back to Python.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest
import sqlalchemy as sa

from service_workbench import sandbox
from service_workbench.notebook import (
    MAX_FRAMES,
    Cell,
    Namespace,
    run_notebook,
)
from service_workbench.safety import SessionPolicy

from shared_python.errors import BadRequestError

#: Python cells only run where the sandbox can actually be enforced. Where it
#: cannot, the platform disables them -- which is the correct behaviour and
#: means these tests would be asserting a refusal, not a capability.
sandboxed = pytest.mark.skipif(
    not sandbox.capabilities().usable,
    reason=f"sandbox unusable here: {sandbox.capabilities().reason}",
)


@pytest.fixture()
def engine() -> Iterator[sa.Engine]:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE orders (id INTEGER, region TEXT, amount REAL)"))
        connection.execute(
            sa.text("INSERT INTO orders VALUES (1,'eu',10.0),(2,'us',20.0),(3,'eu',30.0)")
        )
    yield engine
    engine.dispose()


class TestSqlCells:
    def test_a_sql_cell_returns_rows(self, engine) -> None:
        result = run_notebook(
            [Cell(kind="sql", source="SELECT region, amount FROM orders ORDER BY id")],
            engine=engine,
        )
        cell = result.cells[0]
        assert cell.ok, cell.error
        assert cell.columns == ["region", "amount"]
        assert cell.row_count == 3

    def test_a_named_sql_cell_binds_its_result(self, engine) -> None:
        space = Namespace()
        run_notebook(
            [Cell(kind="sql", source="SELECT * FROM orders", output_name="orders")],
            engine=engine,
            namespace=space,
        )
        assert "orders" in space.frames
        assert len(space.frames["orders"]) == 3

    def test_the_last_returning_statement_is_the_result(self, engine) -> None:
        result = run_notebook(
            [Cell(kind="sql", source="SELECT 1 AS a; SELECT 2 AS b")], engine=engine
        )
        assert result.cells[0].columns == ["b"]

    def test_a_failing_statement_stops_the_notebook(self, engine) -> None:
        result = run_notebook(
            [
                Cell(kind="sql", source="SELECT * FROM orders", position=0),
                Cell(kind="sql", source="SELECT * FROM nope", position=1),
                Cell(kind="sql", source="SELECT 1", position=2),
            ],
            engine=engine,
        )
        assert result.cells[0].ok
        assert result.cells[1].error
        # Running cell 3 against state cell 2 would have produced, had it not
        # failed, gives numbers that were never true.
        assert result.cells[2].skipped

    def test_a_write_is_refused_in_a_read_only_notebook(self, engine) -> None:
        result = run_notebook([Cell(kind="sql", source="DELETE FROM orders")], engine=engine)
        assert result.cells[0].error
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar_one() == 3

    def test_a_write_runs_when_the_policy_allows(self, engine) -> None:
        result = run_notebook(
            [Cell(kind="sql", source="DELETE FROM orders WHERE id = 1")],
            engine=engine,
            policy=SessionPolicy(allow_writes=True),
        )
        assert result.cells[0].ok, result.cells[0].error
        assert "1 row(s) affected" in result.cells[0].stdout

    def test_a_sql_cell_without_a_connection_says_so(self) -> None:
        result = run_notebook([Cell(kind="sql", source="SELECT 1")])
        assert "no database connection" in result.cells[0].error


class TestRecipeCells:
    def test_a_recipe_transforms_a_named_frame(self) -> None:
        space = Namespace(frames={"raw": pd.DataFrame({"name": ["  Ada  ", "bob"]})})
        result = run_notebook(
            [
                Cell(
                    kind="recipe",
                    config={
                        "input": "raw",
                        "steps": [{"step_type": "tool", "config": {"tool": "text.trim", "column": "name"}}],
                    },
                    output_name="clean",
                )
            ],
            namespace=space,
        )
        assert result.cells[0].ok, result.cells[0].error
        assert list(space.frames["clean"]["name"]) == ["Ada", "bob"]

    def test_a_recipe_can_be_written_as_yaml_in_the_cell(self) -> None:
        # Which is what makes a notebook reviewable in a pull request.
        space = Namespace(frames={"raw": pd.DataFrame({"name": ["  Ada  "]})})
        source = "version: 1\nsteps:\n  - step: tool\n    tool: text.trim\n    with:\n      column: name"
        result = run_notebook(
            [Cell(kind="recipe", source=source, config={"input": "raw"}, output_name="clean")],
            namespace=space,
        )
        assert result.cells[0].ok, result.cells[0].error
        assert list(space.frames["clean"]["name"]) == ["Ada"]

    def test_a_recipe_naming_a_missing_frame_lists_what_exists(self) -> None:
        space = Namespace(frames={"raw": pd.DataFrame({"a": [1]})})
        result = run_notebook(
            [Cell(kind="recipe", config={"input": "ghost", "steps": []}, output_name="x")],
            namespace=space,
        )
        assert "ghost" in result.cells[0].error
        assert "raw" in result.cells[0].error

    def test_a_recipe_with_no_input_says_so(self) -> None:
        result = run_notebook([Cell(kind="recipe", config={"steps": []})])
        assert "which result it transforms" in result.cells[0].error

    def test_step_warnings_are_surfaced(self) -> None:
        space = Namespace(frames={"raw": pd.DataFrame({"n": ["1", "x"]})})
        result = run_notebook(
            [
                Cell(
                    kind="recipe",
                    config={
                        "input": "raw",
                        "steps": [{"step_type": "tool", "config": {"tool": "type.to_number", "column": "n"}}],
                    },
                )
            ],
            namespace=space,
        )
        assert "could not read" in result.cells[0].stdout


class TestMarkdownCells:
    def test_a_markdown_cell_runs_and_does_nothing(self) -> None:
        result = run_notebook([Cell(kind="markdown", source="# Notes")])
        assert result.cells[0].ok
        assert result.cells[0].rows == []


class TestNamespace:
    def test_binding_reports_shapes(self) -> None:
        space = Namespace()
        space.bind("a", pd.DataFrame({"x": [1, 2]}))
        assert space.describe() == {"a": "2 rows x 1 columns"}

    def test_an_enormous_frame_is_refused_with_a_suggestion(self) -> None:
        space = Namespace()
        with pytest.raises(BadRequestError, match="save it as a dataset"):
            space.bind("big", pd.DataFrame({"x": range(200_001)}))

    def test_too_many_frames_is_refused(self) -> None:
        space = Namespace()
        for index in range(MAX_FRAMES):
            space.bind(f"f{index}", pd.DataFrame({"x": [1]}))
        with pytest.raises(BadRequestError, match=f"up to {MAX_FRAMES}"):
            space.bind("one_too_many", pd.DataFrame({"x": [1]}))

    def test_rebinding_an_existing_name_is_allowed(self) -> None:
        space = Namespace()
        for index in range(MAX_FRAMES):
            space.bind(f"f{index}", pd.DataFrame({"x": [1]}))
        space.bind("f0", pd.DataFrame({"x": [1, 2]}))
        assert len(space.frames["f0"]) == 2


class TestCellValidation:
    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="not a kind of cell"):
            Cell(kind="cobol", source="")

    def test_a_name_that_is_not_an_identifier_is_refused(self) -> None:
        with pytest.raises(BadRequestError, match="cannot be used as a name"):
            Cell(kind="sql", source="SELECT 1", output_name="my result")


@sandboxed
class TestPythonCells:
    def test_a_python_cell_reads_a_frame_from_a_sql_cell(self, engine) -> None:
        result = run_notebook(
            [
                Cell(kind="sql", source="SELECT * FROM orders", output_name="orders", position=0),
                Cell(kind="python", source="total = float(orders['amount'].sum())", position=1),
            ],
            engine=engine,
        )
        assert result.cells[1].ok, result.cells[1].error
        assert "60" in result.cells[1].stdout

    def test_a_python_cell_publishes_a_frame_the_next_recipe_reads(self, engine) -> None:
        space = Namespace()
        result = run_notebook(
            [
                Cell(
                    kind="python",
                    source="derived = pd.DataFrame({'name': ['  Ada  ']})",
                    output_name="derived",
                    position=0,
                ),
                Cell(
                    kind="recipe",
                    config={
                        "input": "derived",
                        "steps": [{"step_type": "tool", "config": {"tool": "text.trim", "column": "name"}}],
                    },
                    output_name="clean",
                    position=1,
                ),
            ],
            namespace=space,
        )
        assert all(cell.ok for cell in result.cells), [c.error for c in result.cells]
        assert list(space.frames["clean"]["name"]) == ["Ada"]

    def test_a_failing_python_cell_stops_the_notebook(self) -> None:
        result = run_notebook(
            [
                Cell(kind="python", source="1 / 0", position=0),
                Cell(kind="python", source="x = 1", position=1),
            ]
        )
        assert result.cells[0].error
        assert result.cells[1].skipped


class TestPythonCellsAreGated:
    def test_they_are_refused_where_the_sandbox_cannot_be_enforced(self) -> None:
        result = run_notebook([Cell(kind="python", source="x = 1")])
        if sandbox.capabilities().usable:
            assert result.cells[0].ok
        else:
            # The roadmap's rule, visible from the notebook: disabled with a
            # stated reason rather than run unsafely.
            assert "Python cells are disabled" in result.cells[0].error
            assert "memory limit" in result.cells[0].error


class TestTheRunIsBounded:
    """Per-cell limits alone are not enough.

    Twenty cells each sitting just inside their own budget still hold an HTTP
    connection for minutes. Bounding the whole run is what makes a synchronous
    notebook defensible instead of a way to tie up the gateway.
    """

    def test_a_notebook_stops_when_its_budget_is_spent(self, engine) -> None:
        cells = [Cell(kind="sql", source="SELECT 1", position=index) for index in range(5)]
        # A zero budget is spent before the first cell finishes, so everything
        # after cell one reports why it never started.
        result = run_notebook(cells, engine=engine, budget_seconds=0)
        assert result.cells[0].ok
        assert all(cell.skipped for cell in result.cells[1:])
        assert "more than 0 seconds" in result.cells[1].error

    def test_a_generous_budget_runs_everything(self, engine) -> None:
        cells = [Cell(kind="sql", source="SELECT 1", position=index) for index in range(3)]
        result = run_notebook(cells, engine=engine, budget_seconds=120)
        assert all(cell.ok for cell in result.cells)

    def test_the_default_budget_is_stated_rather_than_implied(self) -> None:
        from service_workbench.notebook import MAX_RUN_SECONDS

        assert MAX_RUN_SECONDS == 120
