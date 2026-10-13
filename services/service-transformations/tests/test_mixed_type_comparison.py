"""Comparing a column that mixes text and numbers says so (A7, found by the worker).

A scheduled recipe compared a column holding "n/a" next to numbers with a
number, and failed with pandas' "'>' not supported between instances of
'float' and 'str'" in the log and nothing a person could act on. The step
validators catch the plain filter case first; this holds the expression
evaluator to the same words for every other way of getting there.
"""

from __future__ import annotations

import pandas as pd
import pytest

from service_transformations.ir import pandas_backend
from service_transformations.ir.expressions import Call, Column, Literal
from shared_python.types import FLOAT64
from service_transformations.ir.nodes import IRError


def test_a_mixed_column_compared_with_a_number_is_explained() -> None:
    frame = pd.DataFrame({"amount": [120.0, "n/a", 80.0]})
    expression = Call("gt", (Column("amount"), Literal(100.0, FLOAT64)))
    with pytest.raises(IRError) as caught:
        pandas_backend.evaluate(expression, frame)
    message = str(caught.value)
    assert "The column 'amount' holds text and numbers together, so it cannot be compared with 100.0" in message
    assert "not supported between" not in message


def test_a_clean_column_still_compares() -> None:
    frame = pd.DataFrame({"amount": [120.0, 80.0]})
    result = pandas_backend.evaluate(Call("gt", (Column("amount"), Literal(100.0, FLOAT64))), frame)
    assert list(result) == [True, False]
