"""Strict extraction schema (spec/03, Extraction schema) and a local validator.

Flat object, every key required, `additionalProperties: false` on every object,
no oneOf/allOf. "none" is the sentinel for an absent answer or misconception.
"""

from __future__ import annotations

STEPS = (
    "base_rate", "likelihood", "false_positive_count", "total_positive", "posterior",
    "restated_given", "hypothetical", "self_correction", "other",
)
REASONING_CODES = ("valid", "misconception", "other_wrong", "vague")
MISCONCEPTION_NAMES = (
    "transposed_conditional", "base_rate_neglect", "ignores_prior", "ignores_data", "none",
)


def _object(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


EXTRACTION_SCHEMA = _object({
    "committed_answer_text": {"type": "string"},
    "reasoning_quotes": {
        "type": "array",
        "items": _object({
            "quote": {"type": "string"},
            "step": {"type": "string", "enum": list(STEPS)},
        }),
    },
    "reasoning_code": {"type": "string", "enum": list(REASONING_CODES)},
    "misconception_name": {"type": "string", "enum": list(MISCONCEPTION_NAMES)},
    "self_corrected": {"type": "boolean"},
})

SCHEMA_NAME = "answer_extraction"


class SchemaError(ValueError):
    pass


def validate_extraction(value) -> None:
    """Raise SchemaError unless `value` matches EXTRACTION_SCHEMA exactly."""
    _validate(value, EXTRACTION_SCHEMA, "$")


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _validate(value, schema: dict, where: str) -> None:
    kind = schema["type"]
    if type(value) is not _TYPES[kind]:
        raise SchemaError(f"{where}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{where}: {value!r} is not an allowed value")
    if kind == "object":
        if set(value) != set(schema["required"]):
            raise SchemaError(f"{where}: missing or additional keys")
        for key, child in schema["properties"].items():
            _validate(value[key], child, f"{where}.{key}")
    elif kind == "array":
        for i, item in enumerate(value):
            _validate(item, schema["items"], f"{where}[{i}]")
