# Agentic Crew Ops Advisor (aivengers-dcortex)

AI-driven operational advisor for airline Crew Control. Natural-language (text **and voice**)
interface over a **deterministic legality engine** - the LLM never does arithmetic; every
duty-hour, FDP, rest and certification check is exact SQL/Python, grounded in the dataset.
On top of answers, the system takes **agentic action**: it proposes database-changing
operations (record sick call, apply cover, cancel flights) that execute **only after
explicit human approval**, with a full audit trail and one-click revert.

> Full install/deploy instructions: **[SETUP.md](SETUP.md)**

---

## Architecture

```
User (text or voice)
      │
      ▼
React frontend (frontend/, Vercel)        Streamlit UI (ui/app.py, alt)
      │  same-origin /api proxy                │
      └─────────────────┬──────────────────────┘
                        ▼
        FastAPI service (api/main.py) — EC2, systemd
        sessions · history · chat · actions · change log · revert
                        │
                        ▼
        LLM agent w/ tool-use (api/agent.py)   ← provider-agnostic (OpenAI-compatible)
                        │  24 tools — the ONLY way the LLM touches data
                        ▼
        Deterministic Ops Engine (engine/)
        ├── lookups.py    Tier 1: reserves, clocks, flights, certs, pairings, costs, risk
        ├── rules.py      RULE-FDP-01..RULE-BASE-07 exact arithmetic
        ├── simulate.py   Tier 2: sick calls, reassignments, closures, delays, cancellations
        ├── recommend.py  Tier 3: ranked, legal, costed cover options
        └── actions.py    Agentic writes — gated behind human approval
                        │
                        ▼
              SQLite crewops.db  (built from data/*.json by etl/load.py)
              + pristine crewops_bkp.db snapshot for one-click revert
```

**The boundary:** the LLM decides *which* tools to call and narrates results; it is
never trusted with math, legality verdicts, or writes. All arithmetic is deterministic
code, and all writes require a human click.

---

## Coverage of the problem statement

### Tier 1 — Lookup & Retrieval ✅

| Question | Tool |
|---|---|
| Who's on reserve at BLR tomorrow? | `get_reserves` |
| Duty hours left for C-1042 this week? | `get_duty_remaining` (exact vs RULE-DUTY-02) |
| Flights departing DEL this afternoon? | `get_departures` |
| Licences expiring in 30 days? | `get_expiring_certs` |

Plus crew profiles, pairings, costs, rules and risk signals — 12 lookup tools in total.

### Tier 2 — Consequence & Simulation ✅

| Scenario                                             | Tool |
|------------------------------------------------------|---|
| Captain called in sick - which flights are uncrewed? | `simulate_sick_call` → uncrewed flights, broken pairing, downstream rule risks, passengers affected |
| Move FO C-2087 onto a pairing - any breach?          | `simulate_reassignment` → per-rule verdicts with exact margins |
| Station closed 08:00–14:00Z - impact?                | `simulate_station_closure` |
| Delay / cancellation ripple                          | `simulate_delay`, `simulate_cancellation` |

Output matches the expected Tier 2 shape: uncrewed flights, `pairing_broken`,
`downstream_risks` with rule IDs and exact overage ("would exceed 60h/7d by 1h20m"),
and passenger counts.

### Tier 3 — Recommendation & Action ✅

**"Captain C-1042 is out - what should I do?"** → `recommend_cover` returns **ranked,
rule-compliant options with cost, legality status, reachability and reasoning**:

1. Own-base reserve callout (cheapest, no delay)
2. Day-off callout at the pairing's start base
3. Other-base reserve + deadhead positioning (deadhead + delay cost)
4. Cancel remaining pairing legs (last resort)

Every option carries: legality verdict per rule checked (`rules_checked`), cost in INR
from `costs.json`, reachability delay, and an excluded-candidates list *with the exact
rule and margin that disqualified each one*. Ranking is deterministic: legal first,
then lowest cost, then lowest delay — mirroring the dataset's worked scenarios.

**Then it acts.** See "Agentic actions" below — the advisor doesn't stop at
recommending; it can execute the chosen option under human control.

---

## How each pain point is solved

| Pain point | Solution |
|---|---|
| **Fragmented data** | 10 JSON sources ETL'd into one queryable SQLite DB; the agent joins crew, rosters, clocks, certs, costs and risk in a single conversation. |
| **Consequence blindness** | Simulation tools trace the *full* ripple: broken pairings → uncrewed downstream legs → rule breaches for candidate fixes → passengers affected. |
| **Legality is exact arithmetic** | All seven rules (FDP-01…BASE-07) are deterministic code with exact margins — the LLM never computes a limit; it only reports what the engine returns. |
| **Expertise bottleneck** | Any controller can ask in plain language (typed or spoken); the system encodes the senior controller's playbook (candidate order, costing, legality) in `recommend.py`. |
| **No reasoning trail** | Every answer ships with an expandable reasoning trace (each tool call, its arguments, raw results) and every verdict cites its rule ID and arithmetic. Applied actions land in a persistent change log. |

---

## Agentic actions — human-in-the-loop by design

The differentiating feature beyond Tier 3: the advisor can **change the operational
state**, but a strict approval gate ensures nothing runs without a human decision.

**Flow:**

1. The agent *proposes* - `propose_record_sick_call`, `propose_apply_cover`,
   `propose_cancel_pairing_flights` create a `pending_actions` row. The tool result
   explicitly tells the model "NOT applied yet - the user must approve".
2. The UI surfaces a **Pending action card** with the summary, action name and params,
   and **Yes, apply / No, reject** buttons.
3. Only on **approve** does the executor in `engine/actions.py` touch `crewops.db`.
   Identical duplicate proposals are deduped.
4. Every applied action is written to a **change log** (what changed, when, row-level
   detail) — visible in the sidebar.
5. **One-click revert**: `crewops_bkp.db` is a pristine snapshot taken before the first
   write; reverting restores it, clears the log and rejects stale proposals.

This is the "system of action" pattern: LLM proposes → deterministic executor applies →
human authorizes → audit trail records → revert guarantees safety during demos and ops.

---

## Additional features

- **Voice in / voice out** - browser speech recognition for input, TTS for spoken
  summaries (the agent produces a separate concise spoken answer).
- **Multi-turn, multi-chat sessions** - persistent conversations stored server-side,
  rename/clear/delete, auto-titling from the first message.
- **Reasoning trace on every non-trivial answer** - full tool-call transparency.
- **Provider-agnostic AI** - any OpenAI-compatible endpoint (GitHub Models, OpenAI,
  Anthropic, Gemini, Ollama) via three `.env` values.
- **Two frontends** - deployed React app (Vercel) + Streamlit for local demos.
- **Cloud deployment** - FastAPI on EC2 under systemd (`deploy/setup-ec2.sh`), React
  on Vercel with an `/api` rewrite (no CORS exposure).
- **Verified against the dataset** - `tests/test_answers.py` replays `questions.json`
  answer keys through the engine: **20/20 pass**; `tests/test_scenarios.py` replays the
  worked disruption scenarios.

---

## Why the answers can be trusted

- **Grounded**: every number comes from a tool call over `crewops.db`; the UI shows the
  full reasoning trace (tools called, arguments, raw results).
- **Verified**: the dataset's own answer keys pass 20/20 against the engine.
- **Explainable**: every legality verdict carries the rule ID and the exact arithmetic
  ("RULE-DUTY-02: would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)").
- **Safe to act**: no write happens without explicit human approval, and everything is
  logged and revertible.

## Key trade-offs & known limitations

- **SQLite** keeps the demo self-contained; swap to PostgreSQL via `engine/db.py` for
  concurrent multi-controller use.
- **Single-disruption recommendations**: `recommend_cover` solves one broken pairing at
  a time; chained multi-disruption optimization (e.g. a closure breaking five pairings
  at once) is simulated but not jointly optimized.
- **LLM phrasing variance**: numbers are always exact (engine-sourced), but narrative
  wording varies between runs; the trace is the ground truth.
- **Handled poorly (honest failure)**: ambiguous relative dates ("next Friday") depend
  on the model inferring the dataset's 2026 window — the engine validates dates, but a
  misparse produces a correct answer to the wrong day; the trace makes this visible.

## Scalability

Stateless chat core → horizontal replicas behind a load balancer; SQLite → PostgreSQL by
swapping one connection module; tools are pure functions (cacheable, unit-testable);
voice runs in the browser (zero server audio load).
