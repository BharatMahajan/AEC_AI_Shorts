"""Tests for the L2 critic rubric + detectors (plan §13)."""
from __future__ import annotations

from pipeline.config import ScriptLoopConfig
from pipeline.critic_script import (
    count_aec_terms,
    evaluate_script,
    has_benefit,
    has_cta,
    has_emoji,
    hook_is_strong,
    names_tool,
)
from pipeline.history import History, HistoryEntry
from pipeline.script_types import Script, ScriptPoint


def _good_script() -> Script:
    return Script(
        title="Revit just automated your floorplans",
        hook="What if Revit laid out your floorplate for you?",
        lines=[
            "Autodesk Forma now uses generative design to test hundreds of massing "
            "options in minutes, scoring each one for daylight, views and floor area "
            "efficiency before you ever open a BIM model.",
            "Inside Revit, AI assisted room tagging places hundreds of tags "
            "automatically, while parametric families adapt to the layout that "
            "generative design recommends for the corridor and core.",
            "Then Navisworks runs ML prioritized clash detection across the structural "
            "and MEP models, grouping the clashes by severity so the coordination team "
            "resolves the worst conflicts first instead of chasing every minor clash.",
            "Across the workflow this saves roughly 40% of coordination time, so "
            "engineers spend less time on BIM cleanup and far more time on real design "
            "decisions that actually matter for the project.",
            "Follow for one practical AEC AI workflow every single day!",
        ],
        points=[
            ScriptPoint("Generative massing", "Forma scores daylight and BIM area automatically"),
            ScriptPoint("Clash detection", "Navisworks prioritizes clashes by severity"),
        ],
        flow=["model", "analyze", "coordinate"],
        description="AI in Revit and Forma. #AEC #BIM #Revit",
        tags=["revit", "bim", "ai"],
        bucket="bim_authoring",
        hook_style="question",
        feature_fingerprint="bim_authoring:generative floorplate layout",
    )


def _cfg(**kw) -> ScriptLoopConfig:
    return ScriptLoopConfig(**kw)


def test_detectors():
    assert names_tool("we use Revit here") is True
    assert names_tool("nothing relevant") is False
    assert has_benefit("this saves 40% of your time")
    assert has_benefit("models faster automatically")
    assert not has_benefit("this exists")
    assert has_cta("follow for more")
    assert not has_cta("the end of the script")
    assert has_emoji("great \U0001F680")
    assert not has_emoji("great")
    assert hook_is_strong("Is this the future?")
    assert not hook_is_strong("this is a statement with no punch")
    assert not hook_is_strong("x" * 120)
    assert count_aec_terms("Revit BIM clash corridor") >= 3


def test_good_script_passes():
    ev = evaluate_script(_good_script(), cfg=_cfg())
    assert ev.passed, ev.violations
    assert ev.score >= 80
    assert ev.details["fatal"] is False


def test_missing_cta_is_fatal():
    s = _good_script()
    s.lines = s.lines[:-1]  # drop the "Follow..." line
    s.description = "no call to action here. #AEC"
    ev = evaluate_script(s, cfg=_cfg())
    assert not ev.passed
    assert ev.details["fatal"] is True
    assert any("call-to-action" in v for v in ev.violations)


def test_emoji_in_lines_is_fatal():
    s = _good_script()
    s.lines.append("amazing stuff \U0001F389")
    ev = evaluate_script(s, cfg=_cfg())
    assert ev.details["fatal"] is True
    assert any("emoji" in v for v in ev.violations)


def test_repetition_against_history_is_fatal(tmp_path):
    h = History(tmp_path / "hist.json")
    h.append(
        HistoryEntry(
            date="2026-06-28",
            bucket="bim_authoring",
            feature_fingerprint="bim_authoring:generative floorplate layout",
            title="t",
            video_id="v1",
        )
    )
    ev = evaluate_script(_good_script(), cfg=_cfg(), history=h)
    assert ev.details["fatal"] is True
    assert any("repeat" in v for v in ev.violations)


def test_low_aec_density_flagged():
    s = _good_script()
    s.hook = "What if a thing did stuff for you?"
    s.lines = ["A tool does things.", "It is nice.", "Follow for more!"]
    s.points = []
    ev = evaluate_script(s, cfg=_cfg())
    assert not ev.passed
    assert any("AEC terms" in v for v in ev.violations)


def test_llm_judge_blend_changes_score():
    class HighJudge:
        def judge(self, script):
            return {"clarity": 10, "excitement": 10, "accuracy": 10}

    class LowJudge:
        def judge(self, script):
            return {"clarity": 0, "excitement": 0, "accuracy": 0}

    cfg = _cfg(use_llm_judge=True)
    high = evaluate_script(_good_script(), cfg=cfg, judge=HighJudge())
    low = evaluate_script(_good_script(), cfg=cfg, judge=LowJudge())
    assert high.score > low.score


def test_judge_failure_is_non_fatal():
    class BrokenJudge:
        def judge(self, script):
            raise RuntimeError("api down")

    ev = evaluate_script(_good_script(), cfg=_cfg(use_llm_judge=True), judge=BrokenJudge())
    assert ev.score > 0


def test_word_count_far_above_max_is_fatal():
    s = _good_script()
    # Inflate word count well past the upper fatal threshold.
    s.lines = s.lines * 10
    ev = evaluate_script(s, cfg=_cfg())
    assert any("word_count=" in v for v in ev.violations)
    assert ev.details["fatal"] is True


def test_hook_style_match_without_punctuation_flags_lack_of_punch():
    s = _good_script()
    s.hook = "this hook has no punctuation"
    s.hook_style = "question"
    ev = evaluate_script(s, cfg=_cfg())
    assert "hook lacks ! or ? punch" in ev.violations
    assert ev.details["sub_scores"]["hook"] == 8.0


def test_unknown_style_and_no_punctuation_is_weak_hook():
    s = _good_script()
    s.hook = "plain statement"
    s.hook_style = "unknown-style"
    ev = evaluate_script(s, cfg=_cfg())
    assert "weak hook" in ev.violations
    assert ev.details["sub_scores"]["hook"] == 0.0
