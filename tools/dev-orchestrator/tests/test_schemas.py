"""Artifact schemas and the validator."""

from __future__ import annotations

import json

import pytest

from pw_dev.schemas import SCHEMA_IDS, load_schema, schema_path
from pw_dev.schemas.validate import SchemaError, validate, validate_artifact, validator_backend
from pw_dev.testing import make_spec


def test_every_registered_schema_loads_and_is_valid_json():
    for schema_id in SCHEMA_IDS:
        schema = load_schema(schema_id)
        assert schema["type"] == "object"
        assert schema_path(schema_id).is_file()


def test_every_schema_is_in_the_strict_subset_both_providers_accept():
    """`codex --output-schema` and `claude --json-schema` both run in strict mode.

    Strict structured output requires every property to be listed in `required`
    and every object to forbid extra keys. A schema that drifts out of that
    subset is rejected by the provider at call time, which is a long way from
    here — so it is checked at rest.
    """
    def walk(node, path):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" or "properties" in node:
            properties = set(node.get("properties", {}))
            if properties:
                required = set(node.get("required", []))
                missing = sorted(properties - required)
                assert not missing, f"{path}: properties not in required: {missing}"
                assert node.get("additionalProperties") is False, (
                    f"{path}: must set additionalProperties: false"
                )
        for key, child in node.items():
            if key in ("properties", "$defs"):
                for name, sub in child.items():
                    walk(sub, f"{path}.{name}")
            elif key == "items":
                walk(child, f"{path}[]")
            elif key in ("anyOf", "oneOf", "allOf"):
                for index, sub in enumerate(child):
                    walk(sub, f"{path}<{index}>")

    for schema_id in SCHEMA_IDS:
        walk(load_schema(schema_id), schema_id)


def test_every_schema_node_declares_a_type():
    """OpenAI's strict mode rejects a property that has only `const` or `enum`.

    Found by a real `codex exec --output-schema` call, which returned
    HTTP 400 `invalid_json_schema`: "In context=('properties', 'schema_version'),
    schema must have a 'type' key." Reading the schema would not have found it.
    """
    def walk(node, path):
        if not isinstance(node, dict):
            return
        if ("properties" in node or "const" in node or "enum" in node
                or "items" in node) and "type" not in node:
            raise AssertionError(f"{path} has no 'type'; strict mode requires one")
        for key in ("properties", "$defs"):
            for name, child in (node.get(key) or {}).items():
                walk(child, f"{path}.{name}")
        if "items" in node:
            walk(node["items"], f"{path}[]")
        for key in ("anyOf", "oneOf", "allOf"):
            for index, child in enumerate(node.get(key) or []):
                walk(child, f"{path}<{index}>")

    for schema_id in SCHEMA_IDS:
        walk(load_schema(schema_id), schema_id)


def test_a_valid_specification_passes():
    validate_artifact(make_spec(), "phase_spec/v1")


def test_every_error_is_reported_not_just_the_first():
    """A model that got three fields wrong should be told all three at once."""
    with pytest.raises(SchemaError) as excinfo:
        validate_artifact({"schema_version": "phase_spec/v1"}, "phase_spec/v1")
    assert len(excinfo.value.errors) > 10


def test_a_wrong_schema_version_is_rejected_before_the_body_is_read():
    with pytest.raises(SchemaError, match="declares"):
        validate_artifact({"schema_version": "phase_spec/v2"}, "phase_spec/v1")


def test_an_unexpected_property_is_rejected():
    spec = make_spec()
    spec["surprise"] = True
    with pytest.raises(SchemaError, match="unexpected property"):
        validate_artifact(spec, "phase_spec/v1")


def test_a_bad_enum_value_is_rejected():
    spec = make_spec()
    spec["tasks"][0]["role"] = "sysadmin"
    with pytest.raises(SchemaError, match="not one of"):
        validate_artifact(spec, "phase_spec/v1")


def test_a_nested_type_error_names_its_path():
    spec = make_spec()
    spec["tasks"][0]["depends_on"] = "T-00"
    with pytest.raises(SchemaError) as excinfo:
        validate_artifact(spec, "phase_spec/v1")
    assert any("tasks[0].depends_on" in error for error in excinfo.value.errors)


def test_null_unions_accept_both_members():
    spec = make_spec()
    spec["tasks"][0]["notes"] = None
    validate_artifact(spec, "phase_spec/v1")
    spec["tasks"][0]["notes"] = "a note"
    validate_artifact(spec, "phase_spec/v1")


def test_a_boolean_is_not_an_integer():
    schema = {"type": "object", "additionalProperties": False,
              "required": ["n"], "properties": {"n": {"type": "integer"}}}
    validate({"n": 3}, schema)
    with pytest.raises(SchemaError):
        validate({"n": True}, schema)


def test_the_review_schema_requires_the_binding_fields():
    """An approval that does not name a tree cannot gate anything."""
    schema = load_schema("review_findings/v1")
    for field in ("base_commit", "candidate_fingerprint", "spec_digest", "run_id"):
        assert field in schema["required"]


def test_the_evidence_schema_distinguishes_every_outcome():
    outcomes = load_schema("verification_evidence/v1")["properties"]["outcome"]["enum"]
    assert set(outcomes) == {"pass", "fail", "skip", "not_run", "infra_unavailable",
                             "timeout", "error"}


def test_the_receipt_schema_can_say_ci_did_not_run():
    statuses = load_schema("publication_receipt/v1")["properties"]["ci_status"]["enum"]
    assert "not_triggered" in statuses


def test_a_finding_can_be_labelled_a_preference():
    """So a speculative opinion cannot be dressed up as a defect."""
    kinds = (load_schema("review_findings/v1")["properties"]["findings"]["items"]
             ["properties"]["kind"]["enum"])
    assert "preference" in kinds


def test_the_backend_in_use_is_reported():
    assert validator_backend() in ("jsonschema", "builtin")


def test_schemas_serialise_for_a_provider_flag():
    """They are passed on the command line, so they have to survive a round trip."""
    for schema_id in SCHEMA_IDS:
        encoded = json.dumps(load_schema(schema_id), separators=(",", ":"))
        assert json.loads(encoded) == load_schema(schema_id)
