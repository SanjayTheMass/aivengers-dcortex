# DCORTEX
# Agentic Crew Ops Advisor

*AI-driven operational superintelligence for airline Crew Control*

## 1. Background / Business Context

dCortex builds AI agents for airline operations — a system of action for airlines.

Every airline runs on a plan. Crew are assigned to flights weeks in advance against a forecasted schedule, and on paper the day works perfectly. The day never works perfectly.

The crew called in sick at 5 a.m. Duty-hour and flight-hour clocks run out mid-rotation. Licences and medical certificates lapse. Weather closes a station for six hours. One delay cascades down an aircraft rotation and breaks four downstream flights. Each event can affect several flights and hundreds of passengers — and every fix creates new problems that must be resolved recursively, in real time.

Absorbing all of this is the **Crew Control desk**: a small team who must work out, within minutes, who is affected, which flights are now at risk, which crew can legally be moved, who can actually be reached, and what it costs.

## 2. Problem Definition

### Current Workflow

1. Identifies the affected crew member and their assignments
2. Traces which flights are now uncovered, including downstream legs in the same pairing
3. Scans the reserve pool for available, qualified, reachable crew
4. Validates each candidate against duty-hour and flight-time limits
5. Weighs cost and knock-on impact
6. Makes the call and notifies the crew

### Pain Points

- Fragmented data
- Consequence blindness
- Legality is exact arithmetic
- Expertise bottleneck
- No reasoning trail

### Tier 1 — Lookup & Retrieval (Mandatory)

- Who's on reserve at BLR tomorrow?
- How many duty hours does C-1042 have left this week?
- Which flights depart DEL this afternoon?
- List crew whose licence expires in the next 30 days.

### Tier 2 — Consequence & Simulation

- Captain C-1042 just called in sick for tomorrow — which flights are now uncrewed?
- If I move FO C-2087 onto DX412, does anyone breach a duty limit?
- Station BLR is closed 14:00–20:00 — what's the crew impact?

### Tier 3 — Recommendation & Action

- Captain C-1042 is out — what should I do?
- Ranked rule-compliant options with cost, legality status, reachability and reasoning.

## 3. Tech Stack

| Layer | Options |
|---|---|
| Backend | Python, Node.js, Java, Go |
| Frontend | React, Next.js, Streamlit, or CLI |
| Database | SQLite, PostgreSQL, MongoDB, DuckDB |
| AI | Claude, OpenAI, Gemini, LangChain, LlamaIndex, Hugging Face |
| Cloud | AWS, Azure, GCP, or local |

## 4. Resources Provided

### Synthetic Dataset

| File | Contents |
|---|---|
| flights.json | 7-day schedule, stations, flights, rotations |
| crew.json | Crew, ratings, base, seniority |
| rosters.json | Pairings and duty assignments |
| duty_clocks.json | Duty and flight accruals |
| reserve_pool.json | Reserve crew |
| certifications.json | Licence and medical validity |
| rules.json | Legality rules |
| costs.json | Callout and overtime costs |
| risk_signals.json | Disruption risk scores |
| scenarios.json | Worked disruption scenarios |
| questions.json | Example questions |

### Legality Ruleset

| Rule ID | Constraint |
|---|---|
| RULE-FDP-01 | Maximum flight duty period of 13 hours, reduced by sectors flown |
| RULE-DUTY-02 | Maximum 60 duty hours in any 7 consecutive days |
| RULE-FLT-03 | Maximum 100 flight hours in any 28 consecutive days |
| RULE-REST-04 | Minimum 12 hours rest before commencing duty |
| RULE-QUAL-05 | Crew must hold a valid rating for the assigned aircraft type |
| RULE-CERT-06 | All certifications must be valid on the duty date |
| RULE-BASE-07 | Reserve callout from base only, unless deadhead cost is applied |

### Sample Record Shapes

#### crew.json
```json
{
  "crew_id": "C-1042",
  "name": "A. Nair",
  "rank": "Captain",
  "base": "BLR",
  "ratings": ["A320"],
  "seniority": 14,
  "reachability_minutes": 90
}
```

#### duty_clocks.json
```json
{
  "crew_id": "C-1042",
  "duty_hours_7d": 48.5,
  "flight_hours_28d": 82.0,
  "last_rest_ended": "2026-09-14T22:00:00Z"
}
```

### Expected Output Shape – Tier 2

```json
{
  "query": "Captain C-1042 called in sick for 15 Sep",
  "impact": {
    "uncrewed_flights": ["DX412","DX413","DX588"],
    "pairing_broken": "P-2291",
    "downstream_risks": [
      {
        "crew_id":"C-2087",
        "rule":"RULE-DUTY-02",
        "detail":"Would exceed 60h/7d by 1h20m"
      }
    ],
    "passengers_affected":486
  }
}
```

### Expected Output Shape – Tier 3

```json
{
  "options": [
    {
      "rank": 1,
      "action": "Assign reserve C-3310",
      "legal": true,
      "rules_checked": ["RULE-FDP-01","RULE-QUAL-05","RULE-BASE-07"],
      "cost_inr": 18500
    }
  ]
}
```

## 5. Expected Output

A working prototype, demonstrated live:
1. Conversational interface — web chat, voice, or a well-designed CLI
2. Reasoning layer answering questions across as many tiers as you reach
3. Visible explanations on all non-trivial answers
4. Architecture diagram — showing the boundary you drew between LLM reasoning and
deterministic logic
5. README — setup, approach, key trade-offs, known limitations
6. Sample inputs and outputs, including at least one case your system handles poorly, with your
analysis
7. Presentation deck and live demo
Honest failure analysis scores well; overstating capability scores badly.

## 6. Assumptions & Constraints

### Mandatory
- Use provided synthetic dataset
- Natural language interface
- Explainable answers
- Grounded answers

### Optional Enhancements
- Voice interface
- Multi-turn chat
- Proactive alerting
- Crew notifications
- Chained disruptions
- Confidence signalling

## 7. Evaluation Criteria

| Criterion | Weight |
|---|---|
| AI Utilization | 20% |
| Innovation & Problem Solving | 15% |
| Technical Excellence | 15% |
| Functionality | 15% |
| User Experience | 10% |
| Presentation | 10% |
| Business Impact | 5% |
| Scalability | 5% |
| Performance | 5% |

## 8. Deliverables Checklist

- [ ] Source code repository
- [ ] Architecture diagram
- [ ] README
- [ ] Sample inputs and outputs
- [ ] Presentation deck
- [ ] Live demo

## 9. Questions

Clarifications can be raised through the event channel.

> The best submission will be the one a real crew controller would trust on a bad operational day.
