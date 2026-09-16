"""How verified a connector is, for the extraction service.

The extraction service predates the connector SDK and drives its databases
directly, so it does not go through the SDK's specs. It should still say what
the SDK knows: a source written from vendor documentation and never executed is
a fact about the numbers a run produces, and the run is where somebody is
looking when the numbers matter.

Kept behind a lookup that fails soft. Extraction working is more important than
extraction knowing about tiers, so a missing or unregistered connector type
produces no note rather than an error.
"""

from __future__ import annotations


def note_for(connector_type: str) -> str | None:
    """A sentence to attach to a test or a run, or None when there is nothing to say.

    Returns None for verified connectors: a warning that appears on every run
    regardless of tier is a warning people stop reading.
    """
    try:
        from service_connectors.registry import get

        spec = get(connector_type).spec
    except Exception:  # noqa: BLE001 - an unknown type is simply not annotated
        return None

    if spec.tier.verified:
        return None
    return (
        f"{spec.label} is {spec.tier.label.lower()}: {spec.tier.explanation}"
    )
