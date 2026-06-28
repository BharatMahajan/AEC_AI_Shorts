# Final review — implementation vs. plan §2 and §18

Reviewer aid for the AI-engineering sign-off. Every loop is checked against the
seven-property §2 contract; then the §18 definition-of-done is walked item by item.

## §2 loop-contract conformance

`pipeline/loops.py` implements the contract once (`run_loop`) and is audited by
`tests/test_loops.py` (100% line+branch). L2/L3/L4 mount it, so they inherit
bounded iteration, "best-so-far" progress, one structured log per iteration, and
a deterministic fallback. L0 is a feedback edge (runs once, not a spin loop); the
Publish retry is a separate bounded loop. The table maps each property to where
it lives and the test that proves it.

### L2 — Script generate ⇄ critique  (`agent_script.py` + `critic_script.py`)
| Property | Implementation | Proof |
|---|---|---|
| Guard | topic selected + feature present | `run_loop` guard; `test_run` |
| Body | LLM writes strict-JSON script from avoid-list + last critique | `test_agent_script::test_converges_after_bad_then_good` |
| Progress | rising composite rubric score (0–100), kept as best-so-far | `test_loops::test_returns_best_artifact_not_latest` |
| Termination | `score ≥ SCRIPT_PASS_THRESHOLD` and no fatal violation | `test_critic_script::test_good_script_passes` |
| Max-iter bound | `SCRIPT_MAX_ATTEMPTS` (3) | `test_agent_script::test_abort_when_all_attempts_fatal` (3 calls) |
| Fallback | ship best if `≥ MIN_ACCEPTABLE` and not fatal, else `ScriptGenerationError` | `test_fallback_to_best_acceptable`, `test_abort_when_all_attempts_fatal` |
| Observability | per-attempt `loop_iteration` JSON + `report.l2` | `test_run`, `test_loops::test_emits_one_log_per_iteration` |

### L3 — Voice synth ⇄ QA  (`agent_voice.py` + `voice_qa.py`)
| Property | Implementation | Proof |
|---|---|---|
| Guard | non-empty narration | `run_loop` guard |
| Body | edge-tts synth → mp3; duration from mutagen | `test_agent_voice::test_passes_first_try` |
| Progress | attempt counter + duration-closeness score; rate adapted between tries | `test_adapt_slows_rate_when_too_short` |
| Termination | duration in `[MIN,MAX]` + silence ok + pronunciation applied | `test_voice_qa::test_in_range_passes` |
| Max-iter bound | `VOICE_MAX_ATTEMPTS` (2) | `test_too_short_retries_then_aborts` (2 calls) |
| Fallback | abort if `< MIN_AUDIO_SECONDS` (never render a stub); else ship best | `test_too_short_retries_then_aborts`, `test_too_long_falls_back_when_not_fatal` |
| Observability | `loop_iteration` JSON + `report.l3` | `test_run` |

### L4 — Render ⇄ QA  (`agent_video.py` + `render_qa.py`)
| Property | Implementation | Proof |
|---|---|---|
| Guard | render-props + audio present | `run_pipeline` writes props before render |
| Body | `npx remotion render` with a perf profile | `test_agent_video::test_passes_first_try` |
| Progress | attempt counter; QA checks passed; profile cost reduced each retry | `test_rerenders_with_reduced_cost_then_passes` |
| Termination | output exists + size + duration match ±tol + non-blank frame | `test_render_qa::test_passes_when_all_good` |
| Max-iter bound | `RENDER_MAX_ATTEMPTS` (2) | `test_aborts_after_cap` (2 calls) |
| Fallback | abort with `RenderError` after cap (never publish broken video) | `test_aborts_after_cap`, `test_render_failure_swallowed_then_aborts` |
| Observability | render seconds/size/delta in QA details + `report.l4` | `test_run` |

### Publish — bounded upload retry  (`agent_publish.py`)
| Property | Implementation | Proof |
|---|---|---|
| Guard | non-empty mp4 + credentials | `test_publish_aborts_*` |
| Body | resumable insert chunk | `YouTubeUploader.upload` |
| Progress | retry attempt; capped exponential backoff + jitter | `test_retry_succeeds_after_transient` (sleeps `[1,2]`) |
| Termination | API returns a `video_id` | `test_publish_appends_history_once_after_video_id` |
| Max-iter bound | `UPLOAD_MAX_RETRIES` (5), only on `{500,502,503,504}` | `test_retry_exhausts_to_upload_error` |
| Fallback | `UploadError`; history **not** appended | `test_publish_aborts_*` (history stays `[]`) |
| Observability | structured logs + `report.publish` | `test_run::test_full_run_appends_history_once` |

### L1 — Recurrence (per-run memory)  (`history.py` + `run.py`)
History is read at L2 entry and appended **once, only after a confirmed `video_id`**
(`History.append` refuses an empty id). Bound = one publish per slot (CI gate job).
Proven by `test_history`, `test_agent_publish`, and `test_run` (dry-run / abort
append nothing; full run appends exactly one).

### L0 — Learning (feedback edge)  (`analytics.py`)
Guard = enabled + key + ≥ `min_uploads`; update rule normalizes stats → bucket/hook
weights + perf_hint; re-enters via `topic_select` (weights) and the L2 prompt
(hint); fallback = empty/unbiased result; never fatal. Proven by `test_analytics`
(weights reflect performance, all no-op paths, bias reaches selection).

**Global rules:** no unbounded loop (every `run_loop` requires `max_iters ≥ 1`,
`test_invalid_max_iters_rejected`); every exit logged with a reason
(`ExitReason`); fallback never silently ships degraded content (fatal violations
block fallback in L2/L3); inner-loop fallback surfaces as a typed error the
orchestrator maps to exit code 2.

## §18 definition-of-done

| # | Criterion | Status |
|---|---|---|
| 1 | Five loops each satisfy the §2 contract, verified in tests | ✅ see table above |
| 2 | L2 converges to a quality bar or escalates deterministically; never ships sub-floor | ✅ `test_agent_script` |
| 3 | L1 reads history at start, appends once only after `video_id`; non-repetition guaranteed | ✅ `test_history`, `test_agent_publish`, `test_run` |
| 4 | L3/L4 gate on duration/quality and re-attempt within bounds before aborting | ✅ `test_agent_voice`, `test_agent_video` |
| 5 | L0 closes the learning edge: performance measurably biases the next script | ✅ `test_analytics::test_weights_bias_topic_selection` |
| 6 | AEC scripts technical, 110–150 words, 1–2 concrete features, practitioner audience; US-female energetic voice; crisp 1080×1920 fast render | ✅ rubric + taxonomy + voice config + Remotion perf profile |
| 7 | Free tools; lint + types; publish gated on green CI; `run-report.json` per run | ✅ edge-tts/Gemini free tier; ruff+mypy+pytest gate in `daily-short.yml`; report written every run |
| 8 | Reviewed/signed off vs §2 and §13 | ⏳ this document is the §2 pass; awaiting human sign-off |

### Honest gaps / notes for the reviewer
- **Coverage gap is closed.** Test coverage for `pipeline/` is now 100%, with CI
  quality gate policy at `--cov-fail-under=100`, and network/codec adapters are
  covered in the current suite framing.
- **Human sign-off remains open (DoD item 8).** Technical implementation review is
  complete; formal reviewer approvals are still required.
- **Operational go-live steps remain.** Slot operations, credential ownership,
  and publication runbook execution are the remaining pre-launch tasks.
