"""A recipe's Python step runs in the notebook's sandbox (E1).

Where the sandbox holds its limits (Linux) the step runs and its result goes
on; where it cannot (macOS refuses the memory limit), the step is refused
with the sandbox's own reason, never run unsafely.
"""

from __future__ import annotations

import pandas as pd
import pytest

from shared_python.errors import BadRequestError

from service_transformations.executor import apply_transformation_steps
from service_transformations.steps.context import StepContext
from service_workbench import sandbox  # registers the runner, as the gateway does

ORDERS = pd.DataFrame({"id": range(1, 9), "region": list("nnsswwnn"), "amount": [5, 7, 3, 9, 1, 2, 8, 4]})


def run(frame: pd.DataFrame, **config):
    return apply_transformation_steps(frame, [{"step_type": "tool", "config": {"tool": "code.python", **config}}],
                                      StepContext())


def test_the_python_step_runs_in_the_sandbox_or_says_why_not() -> None:
    if not sandbox.capabilities().usable:
        with pytest.raises(BadRequestError) as refused:
            run(ORDERS, code="result = data")
        assert str(refused.value) == sandbox.capabilities().reason
        pytest.skip(f"The sandbox is not usable here, as stated: {sandbox.capabilities().reason}")
    out, _ = run(ORDERS, code="result = data[data.amount > 4].assign(big=True)")
    assert out["id"].tolist() == [1, 2, 4, 7] and out["big"].all()


def test_a_python_step_that_fails_says_how() -> None:
    if not sandbox.capabilities().usable:
        pytest.skip(f"The sandbox is not usable here, as stated: {sandbox.capabilities().reason}")
    with pytest.raises(BadRequestError, match="The Python step stopped"):
        run(ORDERS, code="raise ValueError('no')")
    with pytest.raises(BadRequestError, match="left no table"):
        run(ORDERS, code="del data")
