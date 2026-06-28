"""Tests for the L2 writer + loop wiring with a MOCKED LLM (plan §13).

No network, no keys: a FakeLLM returns scripted JSON so we can prove convergence,
fallback, abort, repetition re-roll, and that critique feedback is injected into
the next prompt.
"""
from __future__ import annotations

import json

import pytest

from pipeline.agent_script import build_prompt, generate_script
from pipeline.config import ScriptLoopConfig
from pipeline.errors import ScriptGenerationError
from pipeline.history import History, HistoryEntry
from pipeline.script_types import parse_script
from pipeline.topic_select import TopicChoice


TOPIC = TopicChoice(
    bucket="bim_authoring",
    bucket_name="BIM authoring",
    tool_hint="Revit",
    feature="generative floorplate layout",
    fingerprint="bim_authoring:generative floorplate layout",
)


def _script_json(*, cta=True, aec=True, benefit=True, words=130) -> str:
    # Build a narration of roughly `words` words.
    filler = "Revit and Forma use BIM generative design for clash-free corridor layouts " * 1
    lines = []
    base = (
        "Autodesk Forma runs generative design across hundreds of BIM massing options "
        "scoring daylight area and clash risk inside Revit for engineers"
    )
    # pad to approx target word count
    body_words = base
    while len(body_words.split()) < words - 12:
        body_words += " plus automated room tagging and corridor coordination in Civil 3D"
    lines.append(body_words)
    if benefit:
        lines.append("This saves 40% of coordination time automatically.")
    else:
        lines.append("This is a thing that exists.")
    if cta:
        lines.append("Follow for one AEC AI workflow daily!")
    hook = "What if Revit designed your floorplate for you?"
    if not aec:
        hook = "What if a tool did stuff for you?"
        lines = ["A tool does things.", "Follow for more!"]
    return json.dumps(
        {
            "title": "Revit automates floorplans",
            "title_variants": ["AI in Revit", "Revit + Forma"],
            "hook": hook,
            "lines": lines,
            "points": [
                {"heading": "Generative massing", "detail": "Forma scores daylight automatically"},
                {"heading": "Clash detection", "detail": "Navisworks ranks clashes by severity"},
            ],
            "flow": ["model", "analyze", "coordinate"],
            "description": "AI in Revit and Forma. #AEC #BIM",
            "tags": ["revit", "bim"],
        }
    )


class FakeLLM:
    """Returns a queue of canned responses; records prompts it received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


def _cfg(**kw) -> ScriptLoopConfig:
    base = dict(max_attempts=3, pass_threshold=80.0, min_acceptable=65.0)
    base.update(kw)
    return ScriptLoopConfig(**base)


def test_first_attempt_passes():
    llm = FakeLLM([_script_json()])
    script = generate_script(TOPIC, llm=llm, cfg=_cfg())
    assert script.title
    assert len(llm.prompts) == 1


def test_converges_after_bad_then_good():
    # Attempt 1: weak (no CTA, low AEC) -> rejected; Attempt 2: good -> pass.
    bad = _script_json(cta=False, aec=False)
    good = _script_json()
    llm = FakeLLM([bad, good])
    script = generate_script(TOPIC, llm=llm, cfg=_cfg())
    assert script.title
    assert len(llm.prompts) == 2
    # The second prompt must contain critique feedback from attempt 1.
    assert "PREVIOUS ATTEMPT WAS REJECTED" in llm.prompts[1]


def test_invalid_json_then_recovers():
    llm = FakeLLM(["not json at all", _script_json()])
    script = generate_script(TOPIC, llm=llm, cfg=_cfg())
    assert script.title
    assert "STRICT JSON" in llm.prompts[1]


def test_fallback_to_best_acceptable():
    # All attempts score in [min_acceptable, pass_threshold): no CTA missing,
    # but weak hook keeps it under 80. Lower the bar so it's acceptable.
    weak = _script_json()  # strong actually; make pass bar very high instead
    llm = FakeLLM([weak])
    cfg = _cfg(max_attempts=1, pass_threshold=99.0, min_acceptable=60.0)
    script = generate_script(TOPIC, llm=llm, cfg=cfg)
    # never passes 99 but is acceptable >=60 and not fatal -> fallback returns it
    assert script.title


def test_abort_when_all_attempts_fatal():
    # Missing CTA on every attempt -> fatal -> must raise, never return.
    bad = _script_json(cta=False)
    llm = FakeLLM([bad, bad, bad])
    with pytest.raises(ScriptGenerationError):
        generate_script(TOPIC, llm=llm, cfg=_cfg())
    assert len(llm.prompts) == 3  # used full bound


def test_repetition_forces_failure(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(
        HistoryEntry(
            date="2026-06-28",
            bucket="bim_authoring",
            feature_fingerprint=TOPIC.fingerprint,
            title="t",
            video_id="v1",
        )
    )
    llm = FakeLLM([_script_json(), _script_json(), _script_json()])
    # Even though content is good, the topic repeats history -> fatal -> abort.
    with pytest.raises(ScriptGenerationError):
        generate_script(TOPIC, llm=llm, cfg=_cfg(), history=h)


def test_prompt_includes_avoid_list(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(
        HistoryEntry(
            date="2026-06-28",
            bucket="mep",
            feature_fingerprint="mep:automated duct routing",
            title="t",
            video_id="v1",
        )
    )
    llm = FakeLLM([_script_json()])
    generate_script(TOPIC, llm=llm, cfg=_cfg(), history=h)
    assert "mep:automated duct routing" in llm.prompts[0]


def test_build_prompt_contains_constraints():
    p = build_prompt(TOPIC, cfg=_cfg(), hook_style="question", avoid=[])
    assert "generative floorplate layout" in p
    assert "call-to-action" in p
    assert "STRICT JSON" in p or "STRICT JSON only" in p


def test_fallback_path_executes_when_threshold_is_unreachable():
    llm = FakeLLM([_script_json()])
    cfg = _cfg(max_attempts=1, pass_threshold=101.0, min_acceptable=60.0)
    script = generate_script(TOPIC, llm=llm, cfg=cfg)
    assert script.title == "Revit automates floorplans"
