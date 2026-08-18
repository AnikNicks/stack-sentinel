"""Dependency-free JSON schema validator (stdlib only) — supports the subset of JSON Schema
this project actually needs: type, required, properties, enum, items, additionalProperties.

Used to validate every agent's structured output before the orchestrator is allowed to hand
it to trend_store.append_trend_entry — malformed output is rejected before it can corrupt the
longitudinal record, per the guardrails in CLAUDE.md.
"""

from __future__ import annotations

from typing import Any

_TYPE_MAP = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


class SchemaValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _validate(instance: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        py_type = _TYPE_MAP.get(expected_type)
        if py_type is None:
            errors.append(f"{path}: unknown schema type '{expected_type}'")
            return
        if expected_type == "boolean":
            if not isinstance(instance, bool):
                errors.append(f"{path}: expected boolean, got {type(instance).__name__}")
                return
        elif expected_type in ("number", "integer") and isinstance(instance, bool):
            errors.append(f"{path}: expected {expected_type}, got boolean")
            return
        elif not isinstance(instance, py_type):
            errors.append(f"{path}: expected {expected_type}, got {type(instance).__name__}")
            return

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in allowed enum {schema['enum']}")

    if expected_type == "object" or (expected_type is None and isinstance(instance, dict)):
        if not isinstance(instance, dict):
            return
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in instance:
                errors.append(f"{path}: missing required field '{field_name}'")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected additional property '{key}'")

    if expected_type == "array" and isinstance(instance, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(instance):
                _validate(item, item_schema, f"{path}[{i}]", errors)


def validate(instance: Any, schema: dict[str, Any]) -> list[str]:
    """Returns a list of error strings; empty list means valid."""
    errors: list[str] = []
    _validate(instance, schema, "$", errors)
    return errors


def validate_or_raise(instance: Any, schema: dict[str, Any]) -> None:
    errors = validate(instance, schema)
    if errors:
        raise SchemaValidationError(errors)
