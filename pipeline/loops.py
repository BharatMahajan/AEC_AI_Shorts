"""loops.py — the reusable loop primitive enforcing the §2 contract.

Every control loop in the system (L2 script, L3 voice, L4 render) is expressed
through :func:`run_loop`, so the loop *semantics* — bounded iteration, monotonic
progress on a "best so far" measure, structured per-iteration logging, and a
deterministic fallback on exhaustion — are implemented and audited exactly once.

Contract (plan §2), mapped to arguments:

    Guard               -> ``guard()``        : entry predicate
    Body                -> ``body(attempt, feedback)`` : produces an artifact
    Progress measure    -> ``Evaluation.score`` (kept as "best so far")
    Termination         -> ``evaluate(...).passed``
    Max-iteration bound -> ``max_iters``
    Fallback/escalation -> ``on_exhausted(best)``
    Observability       -> one structured log record per iteration

Key design choice: the returned artifact is the **best scoring** attempt, not
the latest. This directly defends against "quality oscillation" (plan §17):
regenerating can never make the shipped result worse than an earlier attempt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

from .errors import LoopExhaustedError
from .logging_setup import get_logger, log_event

A = TypeVar("A")  # artifact type produced by the loop body


# --------------------------------------------------------------------------- #
# Evaluation result returned by an ``evaluate`` callable
# --------------------------------------------------------------------------- #
@dataclass
class Evaluation:
    """Verdict on one artifact: did it pass, how good is it, and why not."""

    score: float
    passed: bool
    violations: list[str] = field(default_factory=list)
    feedback: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Exit reasons (logged reason codes — plan §2 "every loop exit is logged")
# --------------------------------------------------------------------------- #
class ExitReason:
    PASSED = "passed"
    GUARD_FAILED = "guard_failed"
    FALLBACK_ACCEPTED = "fallback_accepted"
    EXHAUSTED = "exhausted"


@dataclass
class Result(Generic[A]):
    """Outcome of a loop run: the best artifact and a logged exit reason."""

    artifact: Optional[A]
    evaluation: Optional[Evaluation]
    exit_reason: str
    attempts: int
    history: list[Evaluation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_reason in (ExitReason.PASSED, ExitReason.FALLBACK_ACCEPTED)


def run_loop(
    name: str,
    *,
    body: Callable[[int, Optional[Evaluation]], A],
    evaluate: Callable[[A], Evaluation],
    max_iters: int,
    guard: Optional[Callable[[], bool]] = None,
    adapt: Optional[Callable[[A, Evaluation], None]] = None,
    on_exhausted: Optional[Callable[["Result[A]"], "Result[A]"]] = None,
    logger_name: str = "pipeline.loops",
) -> Result[A]:
    """Run a bounded, observable feedback loop.

    Parameters
    ----------
    name:
        Loop identifier used in every log record (e.g. ``"L2.script"``).
    body:
        ``body(attempt, last_evaluation)`` -> artifact. Receives the previous
        evaluation so it can incorporate critique feedback. ``last_evaluation``
        is ``None`` on the first attempt.
    evaluate:
        ``evaluate(artifact)`` -> :class:`Evaluation`. Pure verdict function.
    max_iters:
        Hard cap on iterations (>= 1). A loop without a finite bound is a defect.
    guard:
        Optional entry predicate. If it returns falsey, the loop never runs and
        the result carries ``ExitReason.GUARD_FAILED``.
    adapt:
        Optional hook called between attempts with ``(artifact, evaluation)`` so
        callers can mutate external/adaptive state (e.g. lower render scale,
        apply pronunciation fixes). The change to inputs is what makes the next
        iteration genuine progress rather than an identical retry.
    on_exhausted:
        Called when the bound is hit without a pass. Receives the provisional
        result (carrying the best artifact). It may return a result with a
        different ``exit_reason`` (e.g. promote to ``FALLBACK_ACCEPTED``) or
        raise a typed error. If omitted, a :class:`LoopExhaustedError` is raised.

    Returns
    -------
    Result
        The best-scoring artifact seen and the logged exit reason.
    """
    if max_iters < 1:
        raise ValueError(f"loop '{name}': max_iters must be >= 1 (got {max_iters})")

    logger = get_logger(logger_name)

    if guard is not None and not guard():
        log_event(logger, "loop_guard_failed", loop=name, exit_reason=ExitReason.GUARD_FAILED)
        return Result(artifact=None, evaluation=None, exit_reason=ExitReason.GUARD_FAILED, attempts=0)

    best_artifact: Optional[A] = None
    best_eval: Optional[Evaluation] = None
    last_eval: Optional[Evaluation] = None
    history: list[Evaluation] = []

    for attempt in range(1, max_iters + 1):
        artifact = body(attempt, last_eval)
        evaluation = evaluate(artifact)
        history.append(evaluation)
        last_eval = evaluation

        # Track the best-so-far (monotonic progress measure).
        is_best = best_eval is None or evaluation.score > best_eval.score
        if is_best:
            best_artifact = artifact
            best_eval = evaluation

        log_event(
            logger,
            "loop_iteration",
            loop=name,
            attempt=attempt,
            max_iters=max_iters,
            score=evaluation.score,
            passed=evaluation.passed,
            best_score=best_eval.score if best_eval else None,
            violations=evaluation.violations,
        )

        if evaluation.passed:
            log_event(
                logger,
                "loop_exit",
                loop=name,
                attempt=attempt,
                exit_reason=ExitReason.PASSED,
                score=evaluation.score,
            )
            return Result(
                artifact=artifact,
                evaluation=evaluation,
                exit_reason=ExitReason.PASSED,
                attempts=attempt,
                history=history,
            )

        # Not passed and attempts remain -> adapt inputs before next body call.
        if attempt < max_iters and adapt is not None:
            adapt(artifact, evaluation)

    # Bound reached without a pass.
    provisional = Result(
        artifact=best_artifact,
        evaluation=best_eval,
        exit_reason=ExitReason.EXHAUSTED,
        attempts=max_iters,
        history=history,
    )

    if on_exhausted is not None:
        final = on_exhausted(provisional)
        log_event(
            logger,
            "loop_exit",
            loop=name,
            attempt=max_iters,
            exit_reason=final.exit_reason,
            best_score=best_eval.score if best_eval else None,
        )
        return final

    log_event(
        logger,
        "loop_exit",
        loop=name,
        attempt=max_iters,
        exit_reason=ExitReason.EXHAUSTED,
        best_score=best_eval.score if best_eval else None,
    )
    raise LoopExhaustedError(
        f"loop '{name}' exhausted {max_iters} attempts; "
        f"best score={best_eval.score if best_eval else 'n/a'}"
    )
