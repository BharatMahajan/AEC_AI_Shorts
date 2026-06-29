"""Tests for script_types.py — parsing + derived fields (plan §13)."""
from __future__ import annotations

import json

import pytest

from pipeline.script_types import ScriptParseError, parse_script


def _raw(**over):
    base = {
        "title": "T",
        "hook": "Hook?",
        "lines": ["one two three", "four five"],
        "title_variants": ["a", "b"],
        "points": [{"heading": "H", "detail": "D"}],
        "flow": ["x", "y"],
        "description": "desc #AEC",
        "tags": ["t1"],
    }
    base.update(over)
    return json.dumps(base)


def test_parses_and_derives():
    s = parse_script(_raw(), bucket="cad", feature="markup assist")
    assert s.title == "T"
    assert s.bucket == "cad"
    assert s.feature_fingerprint == "cad:markup assist"
    assert s.narration == "Hook? one two three four five"
    assert s.word_count == 6
    assert s.points[0].heading == "H"


def test_strips_json_code_fences():
    fenced = "```json\n" + _raw() + "\n```"
    s = parse_script(fenced, bucket="cad", feature="x")
    assert s.title == "T"


def test_invalid_json_raises():
    with pytest.raises(ScriptParseError):
        parse_script("totally not json", bucket="cad", feature="x")


def test_missing_required_field_raises():
    with pytest.raises(ScriptParseError):
        parse_script(json.dumps({"title": "T"}), bucket="cad", feature="x")  # no hook


def test_non_object_json_raises():
    with pytest.raises(ScriptParseError):
        parse_script(json.dumps([1, 2, 3]), bucket="cad", feature="x")


def test_to_dict_includes_derived():
    s = parse_script(_raw(), bucket="cad", feature="markup assist")
    d = s.to_dict()
    assert d["narration"] == s.narration
    assert d["word_count"] == s.word_count
    assert d["points"] == [{"heading": "H", "detail": "D"}]


def test_parse_non_string_raw_raises_attribute_error():
    with pytest.raises(AttributeError):
        parse_script(None, bucket="cad", feature="x")  # type: ignore[arg-type]


def test_non_list_fields_are_coerced_to_empty_lists():
    raw = _raw(lines="not-list", title_variants="x", points="y", flow="z", tags="t")
    s = parse_script(raw, bucket="cad", feature="x")
    assert s.lines == []
    assert s.title_variants == []
    assert s.points == []
    assert s.flow == []
    assert s.tags == []


def test_points_ignore_non_dict_items():
    raw = _raw(points=[{"heading": "H", "detail": "D"}, 123, "x"])
    s = parse_script(raw, bucket="cad", feature="x")
    assert len(s.points) == 1
    assert s.points[0].heading == "H"
