from __future__ import annotations
from jsonschema import validate as _validate, Draft202012Validator

def validate_against_schema(data, schema):
    Draft202012Validator.check_schema(schema)
    _validate(instance=data, schema=schema)
