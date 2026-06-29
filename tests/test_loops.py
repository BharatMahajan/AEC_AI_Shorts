"""Tests for the core loop primitive (plan §13: "prove the loops").

These are the contract tests every reviewer audits once: termination at success,
respect for the max-iteration bound, adapt called between attempts, on_exhausted
invoked, one log per iteration, and "best so far" (not "latest") returned.
"""
from __future__ import annotations

import logging

import pytest

from pipeline.errors import LoopExhaustedError
from pipeline.loops import Evaluation, ExitReason, Result, run_loop


def _passing_eval(score: float) -> Evaluation:
    return Evaluation(score=score, passed=True)


def _failing_eval(score: float, fb: str = "") -> Evaluation:
    return Evaluation(score=score, passed=False, feedback=fb)


def test_exits_immediately_on_first_pass():
    calls = {"body": 0}

    def body(attempt, last):
        calls["body"] += 1
        return {"attempt": attempt}

    res = run_loop(
        "t.pass",
        body=body,
        evaluate=lambda a: _passing_eval(90.0),
        max_iters=5,
    )
    assert res.ok
    assert res.exit_reason == ExitReason.PASSED
    assert res.attempts == 1
    assert calls["body"] == 1


def test_respects_max_iters_and_raises_without_fallback():
    calls = {"body": 0}

    def body(attempt, last):
        calls["body"] += 1
        return attempt

    with pytest.raises(LoopExhaustedError):
        run_loop(
            "t.exhaust",
            body=body,
            evaluate=lambda a: _failing_eval(10.0),
            max_iters=3,
        )
    assert calls["body"] == 3  # never exceeds the bound


def test_score_rises_then_passes_convergence():
    # Simulates a generate<->critique loop converging: 50 -> 70 -> 85 (pass>=80).
    scores = iter([50.0, 70.0, 85.0])

    def evaluate(a):
        s = next(scores)
        return Evaluation(score=s, passed=s >= 80.0)

    res = run_loop(
        "t.converge",
        body=lambda attempt, last: attempt,
        evaluate=evaluate,
        max_iters=3,
    )
    assert res.exit_reason == ExitReason.PASSED
    assert res.attempts == 3
    assert res.evaluation.score == 85.0


def test_adapt_called_between_attempts_with_feedback():
    seen_feedback = []

    def body(attempt, last):
        seen_feedback.append(None if last is None else last.feedback)
        return attempt

    def adapt(artifact, evaluation):
        # adapt mutates nothing here; we just assert it runs between attempts
        adapt.count += 1

    adapt.count = 0  # type: ignore[attr-defined]

    with pytest.raises(LoopExhaustedError):
        run_loop(
            "t.adapt",
            body=body,
            evaluate=lambda a: _failing_eval(10.0, fb=f"fix-{a}"),
            adapt=adapt,
            max_iters=3,
        )
    # adapt runs after attempts 1 and 2, but NOT after the final attempt 3.
    assert adapt.count == 2
    # Body receives previous evaluation feedback on attempts 2 and 3.
    assert seen_feedback == [None, "fix-1", "fix-2"]


def test_returns_best_artifact_not_latest():
    # Scores go 80 (best) then 30; loop must keep the 80 artifact on exhaustion.
    seq = iter([("good", 80.0), ("bad", 30.0)])

    def body(attempt, last):
        return next(seq)

    def evaluate(a):
        return _failing_eval(a[1])  # never "passes" the 90 bar

    def on_exhausted(provisional: Result):
        # Promote best to fallback acceptance.
        return Result(
            artifact=provisional.artifact,
            evaluation=provisional.evaluation,
            exit_reason=ExitReason.FALLBACK_ACCEPTED,
            attempts=provisional.attempts,
            history=provisional.history,
        )

    res = run_loop(
        "t.best",
        body=body,
        evaluate=evaluate,
        on_exhausted=on_exhausted,
        max_iters=2,
    )
    assert res.exit_reason == ExitReason.FALLBACK_ACCEPTED
    assert res.artifact == ("good", 80.0)  # best artifact, not latest "bad"
    assert res.evaluation.score == 80.0


def test_guard_failure_short_circuits():
    calls = {"body": 0}

    def body(attempt, last):
        calls["body"] += 1
        return attempt

    res = run_loop(
        "t.guard",
        body=body,
        evaluate=lambda a: _passing_eval(99.0),
        guard=lambda: False,
        max_iters=3,
    )
    assert res.exit_reason == ExitReason.GUARD_FAILED
    assert not res.ok
    assert calls["body"] == 0


def test_invalid_max_iters_rejected():
    with pytest.raises(ValueError):
        run_loop(
            "t.bad",
            body=lambda a, last: a,
            evaluate=lambda a: _passing_eval(1.0),
            max_iters=0,
        )


def test_emits_one_log_per_iteration(caplog):
    with caplog.at_level(logging.INFO, logger="pipeline.loops"):
        with pytest.raises(LoopExhaustedError):
            run_loop(
                "t.log",
                body=lambda a, last: a,
                evaluate=lambda a: _failing_eval(5.0),
                max_iters=3,
            )
    iteration_logs = [r for r in caplog.records if r.getMessage() == "loop_iteration"]
    assert len(iteration_logs) == 3


@pytest.mark.parametrize("bound", [1, 2, 5, 10])
def test_never_exceeds_bound_property(bound):
    calls = {"n": 0}

    def body(attempt, last):
        calls["n"] += 1
        return attempt

    with pytest.raises(LoopExhaustedError):
        run_loop(
            "t.prop",
            body=body,
            evaluate=lambda a: _failing_eval(0.0),
            max_iters=bound,
        )
    assert calls["n"] 