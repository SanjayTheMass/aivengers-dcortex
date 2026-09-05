# Agentic Crew Ops Advisor (aivengers-dcortex)

AI-driven operational advisor for airline Crew Control. Natural-language (text **and voice**)
interface over a deterministic legality engine — the LLM never does arithmetic; every
duty-hour, FDP, rest and certification check is exact SQL/Python, grounded in the dataset.

## Architecture

```
User (text or voice)
      │
      ▼
Streamlit chat UI (ui/app.py)          FastAPI service (api/main.py)
      │  browser STT/TTS                     │  POST /chat (stateless, scale-out)
      └───────────────┬──────────────────────┘
                      ▼
        LLM agent w/ tool-use (api/agent.py)   ← provider-agnostic (OpenAI-compatible)
                      │  calls 19 tools
                      ▼
        Deterministic Ops Engine (engine/)
        ├── lookups.py    Tier 1: reserves, clocks, flights, certs, pairings, costs, risk
        ├── rules.py      RULE-FDP-01..RULE-BASE-07 exact arithmetic
        └── simulate.py   Tier 2: sick calls, reassignments, closures, delays, cancellations
                      │
                      ▼
              SQLite crewops.db  (built from data/*.json by etl/load.py)
```

## Quick start

```bash
pip install -r requirements.txt
python etl/load.py                 # build crewops.db from data/*.json
python tests/test_answers.py       # verify engine vs dataset answer keys (20/20)
copy .env.example .env             # then set AI_API_KEY (see options inside)
streamlit run ui/app.py            # chat UI with voice
# or run the API:  uvicorn api.main:app --reload
```

## AI provider

Any OpenAI-compatible endpoint works — set in `.env`:
`AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY`. Presets included for GitHub Models (free),
OpenAI, Anthropic, Gemini and local Ollama.

## Why the answers can be trusted

- **Grounded**: every number comes from a tool call over `crewops.db`; the UI shows the
  full reasoning trace (tools called, arguments, raw results).
- **Verified**: `tests/test_answers.py` replays the dataset's own `questions.json`
  answer keys against the engine — 20/20 pass.
- **Explainable**: every legality verdict carries the rule ID and the exact arithmetic
  ("RULE-DUTY-02: would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)").

## Scalability

Stateless API → horizontal replicas; SQLite → PostgreSQL by swapping the connection in
`engine/db.py`; tools are pure functions (cacheable, unit-testable); voice runs in the
browser (zero server audio load).