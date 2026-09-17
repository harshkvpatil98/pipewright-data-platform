"""Independently executed verification. Agents request IDs; the controller runs commands."""

from .registry import Check, Registry, PIPEWRIGHT_CHECKS
from .runner import Outcome, VerificationRunner

__all__ = ["Check", "Registry", "PIPEWRIGHT_CHECKS", "Outcome", "VerificationRunner"]
