"""Pipewright's development orchestrator.

An OpenAI planner and independent reviewer, Claude implementation workers, and a
deterministic controller that owns run state, scheduling, verification and Git
publication.

This package is development tooling. It is not part of the Pipewright product
runtime, and nothing here is imported by the gateway or any service — in
particular `service-intelligence` remains what it says it is: deterministic
analysis with no model calls.
"""

__version__ = "1.0.0"
