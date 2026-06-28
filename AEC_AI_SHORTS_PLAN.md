# Loop-Engineered Design — "AI in AEC" Daily YouTube Shorts

**For:** AI Engineering team review.
**Author role:** automation expert.
**Status:** implementation-ready design (blueprint, no code yet).
**Design lens:** this system is specified as a set of **explicit, bounded, observable feedback loops**. Every loop in this document has a formal contract (§2). The four "agents" are the actors; the *loops* are the engineering.

---

## 0. Executive summary

A fully-automatic, free-tool system that publishes one ~50–60s vertical YouTube Short per slot about **AI in the AEC industry** (Revit, AutoCAD, Civil 3D, Navisworks/ACC, project controls, structural/MEP, transport, water treatment, digital twins, generative design, etc.).

It is built as **five nested feedback loops**, not a linear pipeline:

| Loop | Name | Scope | Closes the feedback by… |
|---|---|---|---|
| **L0** | Learning loop | across runs (weeks) | published performance → topic/hook weights → next script |
| **L1** | Recurrence loop | one per slot (daily) | `scripts_created.json` memory → guarantees non-repetition next run |
| **L2** | Script generate↔critique loop | within a run | LLM writer ⇄ evaluator rubric → regenerate until quality bar or cap |
| **L3** | Voice QA loop | within a run | synthesize → validate duration/pronunciation → re-synthesize with fixes |
| **L4** | Render quality-gate loop | within a run | render → verify frames/duration → re-render with adjusted props |

Four agents do the work — **Script, Voice, Video, Publish** — wired as a deterministic orchestration where only Script (and its critic) call an LLM. The deterministic majority is what makes the loops **testable and convergent**, which is the core requirement for presenting loops to an engineering team: every loop must provably terminate and provably make progress.

---

## 1. Why "loops," not a "pipeline"

A naive chain `Script → Voice → Video → Publish` is a DAG: one pass, no self-correction. Real-world content automation fails on the long tail — a weak hook, a 9-second audio glitch, a blank render frame, a repeated topic. **Loop engineering** replaces "hope each stage is perfect" with "each stage iterates against an acceptance test until it converges or escalates."

The system therefore has:
- an **inner control loop** around each fallible stage (L2–L4),
- a **per-run memory loop** (L1),
- an **outer learning loop** (L0),
- and **bounded retry loops** inside network calls (upload/LLM/TTS).

Each loop is engineered with the same contract so the whole system is uniformly auditable.

---

## 2. The loop contract (applies to every loop in this design)

Every loop **must** declare these seven properties. Reviewers should check each loop against this table.

| Property | Meaning | Why it matters |
|---|---|---|
| **Guard** | entry condition — when the loop is allowed to start | prevents work on invalid state |
| **Body** | the action performed each iteration | the unit of work |
| **Progress measure** | a monotonic quantity that changes each iteration (e.g. attempt count, rising quality score) | proves the loop moves toward exit, not in circles |
| **Termination condition** | success predicate that exits the loop | defines "good enough" |
| **Max-iteration bound** | hard cap on iterations | guarantees halting; no infinite spin / runaway cost |
| **Fallback / escalation** | what happens if the cap is hit without success | converts "stuck" into a deterministic, safe outcome |
| **Observability** | structured logs/metrics emitted each iteration (attempt #, scores, exit reason) | makes the loop debuggable and reviewable in prod |

**Global rules:**
- No loop may be unbounded. A loop without a max-iteration bound is a defect.
- Every loop exit (success *or* fallback) is logged with a reason code.
- A loop's fallback must never silently publish degraded content — it either ships an acceptable lower-tier output **or** aborts the run with a typed error + alert. Which one is a per-loop policy (declared below).
- Loops compose: an inner loop's fallback is an outer loop's input signal.

---

## 3. Loop topology (with feedback edges)

```
        ┌───────────────────────────── L0: LEARNING LOOP (across runs) ───────────────────────────┐
        │  YouTube stats ─▶ performance scorer ─▶ topic/hook weights ─▶ (influences L2 next run)    │
        └───────────────────────────────────────────▲──────────────────────────────────────────────┘
                                                     │ weights + perf hint
   scheduler ─▶┌──────────────────────────── L1: RECURRENCE LOOP (per run) ─────────────────────────┐
               │                                                                                     │
               │  read scripts_created.json (memory)                                                 │
               │            │                                                                         │
               │            ▼                                                                         │
               │   ┌──── L2: SCRIPT↔CRITIQUE ────┐   ┌─ L3: VOICE QA ─┐   ┌─ L4: RENDER GATE ─┐       │
               │   │ write ─▶ evaluate ─▶ pass?  │   │ tts ─▶ verify  │   │ render ─▶ verify  │       │
               │   │   ▲          │  no(refine)  │   │  ▲       │ no   │   │  ▲         │ no    │       │
               │   │   └──────────┘              │   │  └───────┘      │   │  └─────────┘       │       │
               │   └──────────────┬──────────────┘   └────────┬───────┘   └─────────┬─────────┘       │
               │      script.json │           voice.mp3+caps  │     out.mp4         │                 │
               │                  ▼                           ▼                     ▼                 │
               │            (Agent 1)                    (Agent 2)              (Agent 3)              │
               │                                                                   │                  │
               │                                                                   ▼                  │
               │                                                          Agent 4: PUBLISH            │
               │                                                       (bounded upload-retry loop)    │
               │                                                                   │                  │
               │   append produced script + perf placeholder to scripts_created.json ◀──────────────┐│
               └────────────────────────────────────────────────────────────────────────────────────┘
                                          (memory updated → next run's L1 cannot repeat)
```

Legend: L2/L3/L4 are inner control loops; L1 is the per-run memory loop; L0 is the outer learning loop. Every "no" edge is a feedback edge that re-enters the loop body with adjusted inputs.

---

## 4. Architecture layers (unchanged foundation, loop-instrumented)

1. **Python orchestration** (`pipeline/`) — agents + loop controllers.
2. **Remotion renderer** (`remotion/`) — visuals, performance-tuned.
3. **GitHub Actions** — free scheduler/runtime; fires L1, commits memory back.

No web server, no DB. State = `state/scripts_created.json` + `build/` artifacts. Agents exchange **typed files** (atomic writes), so any loop/agent can run in isolation or later move to its own worker/queue (scale path in §12).

### 4.1 Repository layout (loop-aware modules in **bold**)

```
aec-ai-shorts/
├── pipeline/
│   ├── config.py            # single source of truth incl. all loop bounds/thresholds
│   ├── errors.py            # typed exceptions + bounded retry/backoff decorator
│   ├── loops.py             # ★ generic loop runner enforcing the §2 contract
│   ├── history.py           # scripts_created.json (L1 memory + L0 ledger)
│   ├── topics_aec.py        # AEC taxonomy + rotation
│   ├── topic_select.py      # non-repeat selection (consumes L0 weights)
│   ├── fetch_news.py        # AEC RSS + news search grounding
│   ├── agent_script.py      # Agent 1 — writer
│   ├── critic_script.py     # ★ L2 evaluator (rubric + optional LLM judge)
│   ├── agent_voice.py       # Agent 2 — edge-tts US female  (★ L3 controller)
│   ├── voice_qa.py          # ★ L3 verifier (duration, pronunciation, silence)
│   ├── render_props.py      # typed render-props.json builder
│   ├── thumbnail.py         # Pillow thumbnail (best-effort)
│   ├── agent_video.py       # Agent 3 — Remotion driver (★ L4 controller)
│   ├── render_qa.py         # ★ L4 verifier (duration match, blank-frame, size)
│   ├── agent_publish.py     # Agent 4 — upload + history append (★ retry loop)
│   ├── analytics.py         # ★ L0 — stats → weights + perf hint
│   ├── preflight.py / notify.py / healthcheck.py / logging_setup.py
│   └── run.py               # orchestrator (sequences L1; mounts L2/L3/L4)
├── remotion/src/{index.ts, Root.tsx, Short.tsx, scenes/, theme/}
├── state/scripts_created.json
├── tests/  build/  .github/workflows/  requirements*.txt  README.md
```

### 4.2 Generic loop runner (`loops.py`) — the reusable primitive

A single, tested helper implements the §2 contract so every loop is consistent:

> `run_loop(name, guard, body, evaluate, max_iters, on_exhausted, adapt) -> Result`
> — checks `guard`; iterates `body`→`evaluate` while not passing and `attempt < max_iters`; calls `adapt(feedback)` between attempts to change inputs (so progress is real, not a retry of the identical call); logs `{name, attempt, score, decision}` each pass; on exhaustion runs `on_exhausted` (fallback or raise). Returns the best artifact + the exit reason.

Centralizing this means reviewers audit loop semantics **once**, and every stage inherits provable termination + observability.

---

## 5. L2 — Script generate ↔ critique loop (the heart of quality)

**Agents:** Agent 1 (writer, LLM) ⇄ `critic_script` (evaluator).

This replaces "generate once and hope" with an evaluator-in-the-loop that regenerates with targeted feedback until the script meets an explicit bar.

### 5.1 Loop contract

| Property | Value |
|---|---|
| **Guard** | a non-repeated AEC sub-topic selected (via history + L0 weights) and a news/grounding pool present |
| **Body** | LLM writes a strict-JSON script for the chosen feature, given the avoid-list + last-attempt critique |
| **Progress measure** | rising **composite rubric score** (0–100); also attempt counter |
| **Termination** | score ≥ `SCRIPT_PASS_THRESHOLD` (e.g. 80) **and** no hard-rule violation |
| **Max-iter bound** | `SCRIPT_MAX_ATTEMPTS` (e.g. 3) |
| **Fallback** | ship the highest-scoring attempt **if** ≥ `SCRIPT_MIN_ACCEPTABLE` (e.g. 65); else **abort run** with `ScriptGenerationError` + alert (never publish a bad script) |
| **Observability** | per attempt: score breakdown, violated rules, chosen hook style, fingerprint, decision |

### 5.2 Evaluator rubric (`critic_script`) — deterministic first, LLM optional

Deterministic checks (cheap, fully unit-testable) carry most of the weight:
- **Word count** in 110–150 (target ~50–60s). Hard rule.
- **Non-repetition:** feature-fingerprint Jaccard vs last K entries < threshold. Hard rule (re-roll on fail).
- **AEC vocabulary density:** ≥ N domain terms from a curated lexicon (BIM, LOD, clash, corridor, RFI, takeoff, parametric, point cloud, digital twin, hydraulic model, BOQ…). Scored.
- **Concreteness:** names a real tool **and** a specific feature **and** a quantified/explicit benefit. Scored (regex/keyword heuristics).
- **Hook strength:** first line ends in `! / ?` or matches hook-style template; length cap. Scored.
- **CTA present**, no emojis in spoken lines, pronounceable acronyms. Hard rules.
- **Optional LLM-as-judge** (same free Gemini, 1 cheap call): rates clarity/excitement/accuracy 0–10; folded into the composite. Disabled by a flag for deterministic CI runs.

The critic returns `{score, passed, violations[], feedback}`; `feedback` is fed back into the next prompt ("previous attempt scored 72; weak hook and only 1 AEC term — strengthen both"). **This is what makes iteration converge instead of randomly retry.**

### 5.3 Domain specifics carried into the body
- **Audience:** AEC engineers, regional team leads, consultants — write to a practitioner.
- **Taxonomy buckets** (extensible): BIM authoring (Revit/Forma/generative design), CAD (AutoCAD AI), Civil/infra (Civil 3D), coordination/clash (Navisworks/ACC), project controls (P6/MSP, cost/risk ML), reality capture & digital twins (Scan-to-BIM), structural, MEP routing/energy, transport (traffic/pavement ML), water/environmental (treatment optimization, hydraulic ML, leakage detection), site ops (CV safety, drones, robotics), docs/specs (RFI/submittal/spec LLMs), GIS/planning.
- Each script covers **1–2 concrete AI features** from one bucket.
- **Output schema:** `title`, `title_variants[2]`, `hook`, `lines[]`, `points[]{heading,detail}`, `flow[]`, `description`(+AEC hashtags), `tags[]`, plus derived `narration`, `bucket`, `accent`, `hook_style`, `feature_fingerprint`.

**Acceptance:** mocked-LLM tests prove: convergence (low→high score exits), max-iter fallback to best-acceptable, abort when all attempts below floor, hard-rule re-roll on repetition, feedback actually injected into the next prompt.

---

## 6. L1 — Recurrence loop (per-run memory)

**Loop body = one full run.** Memory = `scripts_created.json`.

| Property | Value |
|---|---|
| **Guard** | scheduler slot open (gate de-dup, §11) |
| **Body** | run L2→L3→L4→Publish for one Short |
| **Progress measure** | run completes a stage sequence; memory grows by ≤1 entry |
| **Termination** | one successful publish, or typed abort |
| **Max-iter bound** | exactly **one publish per slot** (enforced by the CI gate) |
| **Fallback** | on any stage abort: do **not** append history, fire alert, exit non-zero (slot can be retried by next poll within tolerance window) |
| **Observability** | run id, slot key, chosen topic, exit code, durations |

**Invariant:** history is read at L2 entry and appended **only** after a confirmed `video_id` (end of Publish). This is the closed edge that guarantees the *next* run's L2 cannot repeat this run — the defining feedback of L1.

---

## 7. L3 — Voice QA loop

**Agent 2 (edge-tts, US female) controlled by `voice_qa`.**

| Property | Value |
|---|---|
| **Guard** | `script.json` present with non-empty `narration` |
| **Body** | synthesize narration → `voice.mp3` + `captions.json` |
| **Progress measure** | attempt count; verifier pass-set size |
| **Termination** | duration in [15s, ~70s] **and** no long leading/trailing silence **and** pronunciation lexicon applied |
| **Max-iter bound** | `VOICE_MAX_ATTEMPTS` (e.g. 2) |
| **Fallback** | if duration < `MIN_AUDIO_SECONDS` after cap → **abort** (never render a 9-second Short); if only minor issues → ship best attempt |
| **Adapt between iters** | apply pronunciation substitutions ("Civil 3D"→"Civil three D", expand/normalize acronyms), nudge `TTS_RATE` if too short/long |
| **Observability** | measured duration (from **mutagen**, not word timings), attempt, applied substitutions, exit reason |

- **Voice:** `en-US-JennyNeural` default (clear, warm), `en-US-AriaNeural` alt (more animated); excitement via `TTS_RATE +8%`, `TTS_PITCH +6Hz`, `TTS_VOLUME +10%` (all env-overridable).
- **Duration is the source of truth for video length** and comes from the real MP3.

**Acceptance:** duration-from-mutagen tested; too-short triggers re-attempt then abort; substitution map applied and unit-tested.

---

## 8. L4 — Render quality-gate loop

**Agent 3 (Remotion) controlled by `render_qa`.**

| Property | Value |
|---|---|
| **Guard** | `render-props.json` + `voice.mp3` exist |
| **Body** | `npx remotion render` with the performance profile → `out.mp4` |
| **Progress measure** | attempt count; QA checks passed |
| **Termination** | output exists, non-zero size, **duration matches audio** (±0.5s), passes **blank-frame / not-all-black** sample check |
| **Max-iter bound** | `RENDER_MAX_ATTEMPTS` (e.g. 2) |
| **Fallback** | attempt 2 lowers cost (e.g. drop scale/concurrency) to dodge transient OOM/GL faults; if still failing → **abort** with `RenderError` + alert |
| **Adapt between iters** | toggle `REMOTION_GL`, reduce `REMOTION_SCALE`/`CONCURRENCY`, retry |
| **Observability** | render seconds, output size, duration delta, sampled-frame luma, exit reason |

### 8.1 Performance profile (quality + speed, free runners)
1080×1920@30fps; all knobs are `REMOTION_*` env/CI Variables:

| Knob | Default | Effect |
|---|---|---|
| `REMOTION_CONCURRENCY` | `cpu-1` (CI 2) | parallel frames |
| `REMOTION_SCALE` | `0.75` (codec-safe-snapped) | render smaller → encode; big speedup, minimal phone-visible loss |
| `JPEG_QUALITY` | `68` | fast frame capture |
| `CODEC`/`CRF`/`X264_PRESET` | `h264`/`24`/`veryfast` | speed vs size |
| `PIXEL_FORMAT`/`AUDIO_CODEC` | `yuv420p`/`aac` | device compatibility |
| `GL` | `swangle` | headless backend |
| caches | `~/.remotion`, `~/.cache/remotion`, `node_modules` | no per-run browser re-download |

GPU-cheap scenes only (CSS gradients/transforms/springs; **no `filter:blur`**). Scene design: Hook → Feature Cards (the 1–2 features) → Workflow diagram (from `flow`, ideal for clash→resolve→coordinate) → CTA, with always-on large captions from `lines` (never gated on word timings), progress bar, per-bucket pattern/accent. Target: 55s Short renders in a few minutes on a 2-core runner.

**Acceptance:** `tsc --noEmit` + `npx remotion bundle` clean; QA loop tested with a mocked renderer (duration-mismatch → re-render → pass/abort).

---

## 9. Agent 4 — Publish + the bounded retry loop

| Property | Value |
|---|---|
| **Guard** | non-empty `out.mp4` + valid upload credentials |
| **Body** | resumable YouTube Data API v3 upload chunk |
| **Progress measure** | bytes uploaded; retry attempt |
| **Termination** | API returns a `video_id` |
| **Max-iter bound** | `_MAX_RETRIES` (e.g. 5) on `{500,502,503,504}` + transport errors, capped exponential backoff + jitter |
| **Fallback** | raise `UploadError` + alert; history **not** appended |
| **Post-success (closes L1 & seeds L0)** | append entry to `scripts_created.json`: `{date, bucket, feature_fingerprint, title, title_variants, hook_style, script_lines, narration, video_id, url, published_at, duration_seconds, perf:{} }`; commit back in CI |

- Category 28 (Science & Tech), `selfDeclaredMadeForKids=false`.
- `REVIEW_BEFORE_PUBLISH=true` → upload **private** as an SME-accuracy gate (recommended for a technical AEC audience).
- Best-effort custom thumbnail (never fatal).

---

## 10. L0 — Learning loop (closed, across runs)

The outer loop that makes the system improve, not just repeat.

| Property | Value |
|---|---|
| **Guard** | `ENABLE_ANALYTICS=true` + `YT_DATA_API_KEY` + ≥ N past uploads with `video_id` |
| **Body** | fetch public stats (views/retention proxy) for recent uploads |
| **Feedback signal** | per-bucket and per-hook-style performance scores |
| **Update rule** | normalize → `weights[bucket]`, `weights[hook]`; write a short `perf_hint` (top titles) |
| **Where it re-enters** | `topic_select` biases bucket choice; L2 prompt receives `perf_hint` ("lean into what worked") |
| **Termination** | runs once per run, before L2 (non-iterative; it's a feedback *edge*, not a spin loop) |
| **Fallback** | any failure → empty weights/hint (system runs unbiased); never fatal |
| **Observability** | logged weights snapshot per run |

This is the edge from "what got watched" → "what we make next," completing the control system.

---

## 11. Orchestration, CI & scheduling

- `run.py` stages: `script | voice | video | publish | all` (+ `--no-render`/`--no-upload`). Each stage mounts its loop via `loops.run_loop`. Exit codes **0/2/1**; typed errors → alerts.
- **`daily-short.yml`**: poll cron (`*/15 * * * *`) + a **gate job** that permits exactly one publish per IST slot (inspects prior successful runs) — this *is* L1's max-iteration bound. `workflow_dispatch` for manual. Test job (must pass) → publish job (Node 20 + Python 3.11, ffmpeg, `remotion browser ensure`, cache Remotion deps+browser, run 4 stages, commit `scripts_created.json`). `REMOTION_*` Variables passed through.
- **`healthcheck.yml`** weekly: refresh YouTube token (catches ~7-day OAuth test-mode expiry) + cheap Gemini call; alert on failure.

---

## 12. Scalability (single channel now, multi-tenant lift documented)

- **Config-driven loop bounds/thresholds** — retune behavior with zero code change.
- **Stateless stages + typed file contracts** — any loop/agent can become a separate worker or queue consumer; `loops.py` semantics travel with it.
- **Multi-tenant lift:** key `scripts_created.json` path, secrets namespace, taxonomy, channel, and L0 weights by `tenant_id`; swap the Actions trigger for scheduler→queue→worker pool. No loop logic changes.
- **Idempotent & retry-safe:** re-running a stage overwrites only its artifact; history mutates once, post-publish.
- **Observability:** structured per-iteration logs + a per-run summary (loop attempts, scores, exit reasons) — the basis for dashboards.

---

## 13. Test strategy — prove the loops, not just the functions

Network/LLM/render mocked. Target **≥95% line+branch** on `pipeline/` (CI `--cov-fail-under`). Loop-specific test classes:

| Area | Tests |
|---|---|
| **`loops.py` (core)** | terminates at success; respects max-iter; calls `adapt` between attempts; runs `on_exhausted`; emits one log per iteration; never exceeds bound (property test) |
| **L2 script/critique** | score rises across attempts → exit; fallback to best-acceptable; abort below floor; repetition hard-rule re-roll; feedback injected into next prompt; rubric scoring unit tests; AEC-vocab + concreteness detectors |
| **L1 recurrence** | history read-at-start/append-at-end ordering; append exactly once and only after `video_id`; abort path appends nothing; corruption-tolerant read; fingerprint dedup |
| **L3 voice** | duration from mutagen; too-short → re-attempt → abort; pronunciation substitutions; silence trim check |
| **L4 render** | duration-match gate; blank-frame detection; re-render with reduced cost on failure; abort after cap (mocked renderer) |
| **Publish retry** | transient codes retried, eventual success; max-retries → `UploadError`; body/privacy fields; thumbnail best-effort |
| **L0 learning** | stats→weights normalization; perf_hint; safe no-op on failure; weights actually bias selection + reach the prompt |
| **Infra** | atomic write; bounded backoff decorator; exit-code mapping; preflight; notify never raises |
| **Contract** | `render-props.json` producer ↔ zod schema parity (golden file) |
| **E2E dry-run** | `run.py --no-render --no-upload` on fixtures: artifacts + pending-history shape + all loop exit reasons logged |
| **Renderer build-gate** | `tsc --noEmit` + `npx remotion bundle`; CI smoke render asserts non-empty MP4 + duration match |

Plus lint (`ruff`), types (`mypy`), and the coverage gate. **Publish is blocked unless all pass.**

---

## 14. Loop observability & review aids (for the AI eng team)

Each loop emits a structured record; a run produces a `build/run-report.json` summarizing:
`{run_id, slot, topic/bucket, L2:{attempts, final_score, exit}, L3:{attempts, duration, exit}, L4:{attempts, render_s, duration_delta, exit}, publish:{retries, video_id}, history_appended:bool}`.
This is the artifact to inspect in review and to later feed dashboards/alerts. Reviewers can verify, per run, that every loop terminated for a declared reason and within its bound.

---

## 15. Credentials (one-time, human)

1. Gemini key from a **personal** account (corporate often `limit:0`) → `GEMINI_API_KEY`.
2. YouTube Data API v3 + **Desktop OAuth client**; **publish consent screen to Production** (test tokens expire ~7 days).
3. `python auth/get_token.py client_secret.json` → `YT_CLIENT_ID/SECRET/REFRESH_TOKEN` secrets.
4. Optional `YT_DATA_API_KEY` (L0), `SLACK_WEBHOOK_URL` (alerts).
5. CI Variables for toggles + all loop bounds/thresholds + `REMOTION_*`.
6. Manual dispatch once to verify the full chain.

---

## 16. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold + config + **`loops.py`** + errors/logging + history | loop runner contract tests green |
| M1 | AEC taxonomy + topic_select + fetch_news | non-repeat selection + on-topic pool tested |
| M2 | **L2** writer + critic (rubric, re-roll, fallback) | convergence/fallback/abort tests green; SME reviews sample scripts |
| M3 | **L3** voice + QA | real 50–60s MP3; short-audio loop + pronunciation tested |
| M4 | render_props + **L4** Remotion + perf profile + QA | `tsc`+bundle clean; duration-gate + re-render tested; CI smoke render fast |
| M5 | **Publish** + retry loop + history append + orchestrator | upload retry tested; history-append-once tested; exit codes |
| M6 | **L0** analytics + weights→selection/prompt | weights bias verified end-to-end (mocked) |
| M7 | CI gate/test/publish/commit + healthcheck + run-report.json | manual dispatch publishes; slot de-dup works; report emitted |
| M8 | Coverage ≥95% + lint + mypy + docs + **AI-eng review** | CI green; every loop checked against §2; sign-off |

---

## 17. Risks & mitigations

| Risk | Mitigation (loop-aware) |
|---|---|
| Technical inaccuracy (credibility-critical for AEC) | L2 concreteness/vocab rubric + optional LLM judge + `REVIEW_BEFORE_PUBLISH` SME gate + source in description |
| Loop non-termination / runaway cost | §2 contract: every loop bounded + fallback; `loops.py` property-tested for halting |
| Quality oscillation (regenerate worse) | L2 keeps best-scoring attempt; progress measure is "best so far," not "latest" |
| Topic exhaustion | large extensible taxonomy + fingerprint dedup + L0 weighting + hook rotation |
| TTS mispronunciation | L3 pronunciation lexicon + duration/silence gates |
| Slow/low-quality render | L4 perf profile + adaptive cost reduction on retry; GPU-cheap scenes |
| Token expiry / quota | Production consent + weekly healthcheck + LLM model fallback |
| Monetization expectation | out of scope; pipeline only produces/publishes |

---

## 18. Definition of done

- Five loops (L0–L4) each satisfy the §2 contract: declared guard, body, progress measure, termination, **bound**, fallback, observability — verified in tests.
- L2 converges to a quality bar or escalates deterministically; never publishes a sub-floor script.
- L1 reads history at start, appends once only after a confirmed `video_id`; non-repetition guaranteed.
- L3/L4 gate on duration/quality and re-attempt within bounds before aborting.
- L0 closes the learning edge: performance measurably biases the next script.
- AEC scripts are technical, compact (110–150 words), cover 1–2 concrete features, target engineers/leads/consultants; US-female energetic voice; crisp sleek 1080×1920 video rendered fast.
- Free tools; ≥95% coverage + lint + types; publish gated on green CI; `run-report.json` emitted per run.
- Reviewed and signed off by the AI engineering team against §2 and §13.

---

*Every loop here is bounded, makes monotonic progress, exits for a logged reason, and has a deterministic fallback. That property — not the four-agent chain — is what makes this a loop-engineered system rather than a pipeline.*
