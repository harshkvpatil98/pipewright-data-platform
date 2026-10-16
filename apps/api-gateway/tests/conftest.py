from __future__ import annotations

import sys
from pathlib import Path

# The suite runs with --import-mode=importlib, which puts no test folder on the
# path; the importers' tests share `conversion_harness.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
