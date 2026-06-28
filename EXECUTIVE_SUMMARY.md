# AEC AI Shorts — Executive Technical Summary

## Audience
Council review packet for:
- Engineering Manager
- Enterprise Architect
- Development Manager

## 1) Executive Position
AEC AI Shorts is a loop-engineered automation system that produces one short-form AEC AI video per publishing slot using free-tool infrastructure.

The core architecture principle is **control-loop reliability**, not linear stage chaining:
- L0: Learning loop (across runs)
- L1: Recurrence loop (per run)
- L2: Script generate-critique loop
- L3: Voice QA loop
- L4: Render quality-gate loop
- Publish retry loop (bounded transient handling)

Operationally, this design reduces silent failure, enforces bounded convergence, and produces auditable run artifacts for governance.

## 2) System Architecture
```mermaid
flowchart LR
  CI[GitHub Actions Scheduler] --> RUN[run.py Orchestrator]

  RUN --> A1[Agent 1: Script]
  RUN --> A2[Agent 2: Voice]
  RUN --> A3[Agent 3: Video]
  RUN --> A4[Agent 4: Publish]

  A1 -->|build/script.json| B[(build/)]
  A2 -->|build/voice.mp3| B
  A3 -->|build/render-props.json + build/out.mp4| B
  RUN -->|build/run-report.json| B

  A4 --> YT[(YouTube)]
  A4 -->|append after video_id| H[(state/scripts_created.json)]

  G[Gemini API] --> A1
  T[edge-tts] --> A2
  R[Remotion CLI] --> A3
  Y[YouTube Data API] --> A4

  H --> RUN
  B --> RUN
```

### Architecture Notes
- No always-on server tier.
- No database dependency.
- State boundary is explicit and small: `state/scripts_created.json` + `build/`.
- Failure domains are isolated behind bounded loops and typed errors.

## 3) Loop-Engineering Contract
Every major stage loop is implemented via a common primitive (`run_loop`) with identical semantics:
- Guard predicate
- Body action
- Progress metric (best-so-far)
- Termination predicate
- Hard max-iteration cap
- Deterministic fallback or abort
- Structured iteration + exit observability

```mermaid
stateDiagram-v2
  [*] --> Guard
  Guard --> ExitGuard: guard false
  Guard --> Body: guard true

  Body --> Evaluate
  Evaluate --> ExitPass: pass
  Evaluate --> Adapt: fail & attempts < max
  Adapt --> Body

  Evaluate --> Exhausted: fail & attempts == max
  Exhausted --> Fallback
  Fallback --> ExitFallback

  ExitGuard --> [*]
  ExitPass --> [*]
  ExitFallback --> [*]
```

## 4) How Agents Work in Tandem
```mermaid
sequenceDiagram
  participant RUN as run.py
  participant T as Topic Select (L1)
  participant S as Script Loop (L2)
  participant V as Voice Loop (L3)
  participant R as Render Loop (L4)
  participant P as Publish Retry
  participant H as History

  RUN->>T: select non-repeating topic (history + weights)
  T-->>RUN: TopicChoice

  RUN->>S: generate_script()
  S-->>RUN: Script
  RUN->>RUN: write build/script.json

  RUN->>V: synthesize_voice()
  V-->>RUN: VoiceArtifact
  RUN->>RUN: write build/voice.mp3

  RUN->>RUN: build_render_props()
  RUN->>RUN: write build/render-props.json

  RUN->>R: render_video()
  R-->>RUN: build/out.mp4

  RUN->>P: publish_short()
  P-->>RUN: video_id, url

  RUN->>H: append HistoryEntry only after video_id
  RUN->>RUN: write build/run-report.json
```

### Tandem Model (Implementation Reality)
- Only Script agent calls the LLM.
- Voice, Video, and Publish are deterministic controllers around adapters.
- Cross-agent handoff is file-contract based, which improves traceability and replayability.

## 5) Loop Topology and Data Feedback
```mermaid
flowchart TD
  subgraph L0[L0 Learning Loop - Across Runs]
    STATS[YouTube Stats] --> W[Topic/Hook Weights]
  end

  subgraph L1[L1 Recurrence Loop - Per Run]
    HIST[(History JSON)] --> TOP[Topic Select]

    subgraph L2[L2 Script Loop]
      S1[Write] --> S2[Critique] --> S1
    end

    subgraph L3[L3 Voice QA]
      V1[Synthesize] --> V2[Validate] --> V1
    end

    subgraph L4[L4 Render Gate]
      R1[Render] --> R2[Verify] --> R1
    end

    subgraph PBL[Publish Retry Loop]
      P1[Upload] --> P2[Retry/Backoff] --> P1
    end

    TOP --> L2 --> L3 --> L4 --> PBL
  end

  W --> L2
  PBL -->|publish success| HIST
  PBL -->|performance| STATS
```

## 6) Technical Deep Dive by Loop

### L0 Learning Loop
- Implemented in analytics path (`compute_learning`).
- Produces bucket weights used by topic selection and script prompting.
- Safe no-op behavior when disabled or insufficient stats.

### L1 Recurrence Loop
- Encoded in orchestration and history append invariant.
- Non-repetition enforced via history read + dedup logic before script generation.
- History append occurs only after confirmed `video_id`.

### L2 Script Loop
- Module: `pipeline/agent_script.py`.
- Writer and critic iterate through `run_loop`.
- On exhaustion: accepts best acceptable output or aborts with typed error.

### L3 Voice QA Loop
- Module: `pipeline/agent_voice.py`.
- Real duration probes and QA gates drive retries.
- Rate adaptation between attempts improves convergence.

### L4 Render Gate Loop
- Module: `pipeline/agent_video.py`.
- Rendering retries reduce cost profile on each attempt to survive transient runner faults.
- Final failure aborts run; no broken video proceeds.

### Publish Retry Loop
- Module: `pipeline/agent_publish.py`.
- Bounded retries over transient classes, capped exponential backoff.
- On success: writes immutable history entry for recurrence + learning.

## 7) Data Contracts and Artifact Flow
| Contract | Producer | Consumer | Purpose |
|---|---|---|---|
| `build/script.json` | Script loop | Voice loop / run audit | Script artifact for narration and traceability |
| `build/voice.mp3` | Voice loop | Render loop | Real audio source for timing |
| `build/render-props.json` | run orchestrator | Remotion renderer | Python-TS boundary contract |
| `build/out.mp4` | Render loop | Publish loop | Publishable output asset |
| `build/run-report.json` | run orchestrator | CI artifact / reviewers | Loop attempts, exits, outcomes |
| `state/scripts_created.json` | Publish loop | Topic selection, analytics | Recurrence memory and learning ledger |

## 8) Quality and Governance Signals
- Test inventory (collected): **199 tests**.
- Pipeline behavior is strongly test-oriented via dependency injection and mockable adapters.
- Run observability is explicit with structured events and a persisted run report.

### Governance Note
Documentation and review artifacts in the repo frame quality posture at full loop-level verification. The active CI workflow currently contains `--cov-fail-under=90` in `.github/workflows/daily-short.yml`, which should be aligned with council-approved quality policy before launch freeze.

## 9) Enterprise Architecture Assessment

### Strengths
- Deterministic orchestration with bounded retries.
- Clear data lineage and replayable artifacts.
- Minimal infrastructure footprint.
- Strong separation of business logic from external adapters.

### Design Trade-offs
- CI scheduler gate is implementation-critical for one-slot enforcement.
- External API boundaries remain operational risk surfaces (managed by retries + alerts).
- Stateless architecture simplifies ops but shifts reliability burden to strict artifact contracts.

## 10) Recommended Council Decisions
1. Approve loop-engineering pattern as the project control backbone.
2. Approve architecture for production pilot under artifact-based audit.
3. Align CI quality threshold and policy text as a single source of truth.
4. Approve operational runbook ownership for scheduler, secrets, and incident response.

## 11) Presentation Diagram (Council Slide Friendly)
```mermaid
flowchart LR
  subgraph CONTROL[Loop-Engineered Control System]
    L0[L0 Learning] --> L1[L1 Recurrence]
    L1 --> L2[L2 Script]
    L2 --> L3[L3 Voice]
    L3 --> L4[L4 Render]
    L4 --> PB[Publish Retry]
    PB --> L1
    PB --> L0
  end

  subgraph ACTORS[Agents]
    A1[Script Agent]
    A2[Voice Agent]
    A3[Video Agent]
    A4[Publish Agent]
  end

  L2 --- A1
  L3 --- A2
  L4 --- A3
  PB --- A4

  ACTORS --> ART[(build/ + state/)]
  ART --> OBS[run-report + logs]
```

---
Prepared from codebase modules in `pipeline/`, workflow definitions in `.github/workflows/`, and repository documentation.
