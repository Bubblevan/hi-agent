from types import SimpleNamespace

import pytest

from evals.llm_evals.bfcl_simple_python import (
    _normalize_schema_types,
    build_provider_tools,
    extract_tool_result,
    first_turn_messages,
    score_prediction,
)


def test_normalize_schema_types_maps_nested_provider_types():
    schema = {
        "type": "dict",
        "properties": {
            "type": {"type": "string"},
            "ratio": {"type": "float"},
            "values": {"type": "tuple"},
            "anything": {"type": "any"},
        },
    }

    normalized = _normalize_schema_types(schema)

    assert normalized["type"] == "object"
    assert normalized["properties"]["type"] == {"type": "string"}
    assert normalized["properties"]["ratio"] == {"type": "number"}
    assert normalized["properties"]["values"] == {"type": "array"}
    assert normalized["properties"]["anything"] == {}


def test_build_provider_tools_rewrites_wire_names_and_preserves_mapping():
    tools, mapping = build_provider_tools(
        [
            {
                "name": "math.factorial",
                "description": "factorial",
                "parameters": {"type": "dict", "properties": {}},
            }
        ]
    )

    assert tools[0]["function"]["name"] == "math_factorial"
    assert mapping["math.factorial"] == "math_factorial"
    assert mapping["math_factorial"] == "math_factorial"
    assert tools[0]["function"]["parameters"]["type"] == "object"


def test_wire_name_collision_is_rejected():
    with pytest.raises(ValueError, match="collision"):
        build_provider_tools([{"name": "a.b"}, {"name": "a_b"}])


def test_extract_tool_result_accepts_sdk_objects_and_json_arguments():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                function=SimpleNamespace(
                    name="math.factorial",
                    arguments='{"n": 5}',
                )
            )
        ]
    )

    prediction, errors = extract_tool_result(
        message,
        {"math.factorial": "math_factorial"},
    )

    assert prediction == [{"math_factorial": {"n": 5}}]
    assert errors == []


def test_extract_tool_result_records_malformed_and_non_object_arguments():
    message = {
        "tool_calls": [
            {"function": {"name": "f", "arguments": "not-json"}},
            {"function": {"name": "g", "arguments": "[1, 2]"}},
            {"function": {"arguments": "{}"}},
        ]
    }

    prediction, errors = extract_tool_result(message, {})

    assert prediction == [{"f": {}}, {"g": {}}]
    assert len(errors) == 3
    assert "not valid JSON" in errors[0]
    assert "not an object" in errors[1]
    assert "no function name" in errors[2]


def test_irrelevance_is_valid_only_when_no_tool_call_is_emitted():
    prompt = {"function": []}

    assert score_prediction(prompt, [], None, "irrelevance", "unused")["valid"]
    failed = score_prediction(prompt, [{"search": {}}], None, "irrelevance", "unused")
    assert failed["valid"] is False
    assert failed["error_type"] == "irrelevance_error:tool_call_emitted"


def test_first_turn_messages_rejects_malformed_bfcl_questions():
    with pytest.raises(ValueError, match="at least one turn"):
        first_turn_messages([])
    with pytest.raises(ValueError, match="first turn"):
        first_turn_messages([["not-a-message"]])
