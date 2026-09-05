"""Tool registry: JSON-schema definitions + dispatch map for the agent.
Every tool is a deterministic engine function — the LLM never does arithmetic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import lookups as L
from engine import simulate as S
from engine.recommend import recommend_cover

TOOLS = [
    # ---------- Tier 1 ----------
    {"name": "get_reserves",
     "description": "List reserve crew at a base on a date with on-call windows, ratings and reachability. Optionally filter to windows covering a required report time (HH:MM UTC) and/or rank.",
     "parameters": {"type": "object", "properties": {
         "station": {"type": "string", "description": "Base IATA code, e.g. BLR"},
         "date": {"type": "string", "description": "YYYY-MM-DD"},
         "callout_utc_time": {"type": "string", "description": "HH:MM UTC the on-call window must cover (use the required report time)"},
         "rank": {"type": "string", "enum": ["Captain", "First Officer", "Senior Cabin Crew", "Cabin Crew"]}},
         "required": ["station", "date"]}},
    {"name": "get_duty_remaining",
     "description": "Duty-hour (60h/7d) and flight-hour (100h/28d) accruals and headroom for a crew member from the snapshot clocks.",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string"}}, "required": ["crew_id"]}},
    {"name": "get_departures",
     "description": "Find flights. Filter by departure station, arrival station, date (YYYY-MM-DD), UTC window, or flight number.",
     "parameters": {"type": "object", "properties": {
         "station": {"type": "string", "description": "departure station"},
         "arr_station": {"type": "string"},
         "date": {"type": "string"},
         "from_utc": {"type": "string", "description": "ISO UTC lower bound on departure"},
         "to_utc": {"type": "string"},
         "flight_no": {"type": "string"}}}},
    {"name": "get_expiring_certs",
     "description": "Certifications expiring within N days of a date.",
     "parameters": {"type": "object", "properties": {
         "as_of_date": {"type": "string"}, "days": {"type": "integer", "default": 30}},
         "required": ["as_of_date"]}},
    {"name": "get_crew_profile",
     "description": "Full crew profile: rank, base, ratings, certifications, duty clock, reserve days, disruption-risk score.",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string"}}, "required": ["crew_id"]}},
    {"name": "get_pairing",
     "description": "Pairing detail: days with report/release times, ordered flights, assigned crew and roles.",
     "parameters": {"type": "object", "properties": {
         "pairing_id": {"type": "string"}}, "required": ["pairing_id"]}},
    {"name": "get_pairings_for_crew",
     "description": "Which pairings/dates a crew member is rostered on (optionally one date).",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string"}, "date": {"type": "string"}},
         "required": ["crew_id"]}},
    {"name": "get_pairing_for_aircraft",
     "description": "The pairing operating a given aircraft tail (e.g. VT-DXA) on a date.",
     "parameters": {"type": "object", "properties": {
         "aircraft": {"type": "string"}, "date": {"type": "string"}},
         "required": ["aircraft", "date"]}},
    {"name": "get_crew_by_filter",
     "description": "List crew by base, rank and/or aircraft rating.",
     "parameters": {"type": "object", "properties": {
         "base": {"type": "string"}, "rank": {"type": "string"},
         "rating": {"type": "string"}}}},
    {"name": "get_costs",
     "description": "Cost table in INR: reserve/day-off callouts, deadhead, delay per hour, cancellation, hotel.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_rules",
     "description": "The legality ruleset with parameters (RULE-FDP-01 .. RULE-BASE-07).",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_risk_signals",
     "description": "Crew disruption-risk scores with drivers, highest first.",
     "parameters": {"type": "object", "properties": {
         "min_score": {"type": "number", "default": 0.0}}}},
    # ---------- Tier 2 ----------
    {"name": "simulate_sick_call",
     "description": "Crew member unavailable from a date: which flights become uncrewed (per day), broken pairings, passengers affected, remaining crew, rank needed for cover.",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string"}, "from_date": {"type": "string"}},
         "required": ["crew_id", "from_date"]}},
    {"name": "simulate_reassignment",
     "description": "Check ALL 7 legality rules for assigning a crew member to a pairing (optionally from a date, as a reserve callout). Returns per-rule verdicts with exact arithmetic detail and whether deadhead positioning is needed.",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string"}, "pairing_id": {"type": "string"},
         "from_date": {"type": "string"},
         "callout_utc": {"type": "string", "description": "ISO UTC time the call is made"},
         "is_reserve_callout": {"type": "boolean"}},
         "required": ["crew_id", "pairing_id"]}},
    {"name": "simulate_station_closure",
     "description": "Flights, pairings, crew and passengers affected by a station closure window.",
     "parameters": {"type": "object", "properties": {
         "station": {"type": "string"}, "date": {"type": "string"},
         "start_hhmm": {"type": "string", "description": "HH:MM UTC"},
         "end_hhmm": {"type": "string"}},
         "required": ["station", "date", "start_hhmm", "end_hhmm"]}},
    {"name": "simulate_delay",
     "description": "Delay an aircraft's day by N minutes: recomputes FDP vs limit and 7-day duty totals for the rostered crew.",
     "parameters": {"type": "object", "properties": {
         "aircraft": {"type": "string", "description": "tail, e.g. VT-DXA"},
         "date": {"type": "string"}, "delay_minutes": {"type": "integer"}},
         "required": ["aircraft", "date", "delay_minutes"]}},
    {"name": "simulate_cancellation",
     "description": "Passengers affected and direct cost of cancelling one flight leg.",
     "parameters": {"type": "object", "properties": {
         "flight_id": {"type": "string", "description": "e.g. DX404-2026-09-16"}},
         "required": ["flight_id"]}},
    {"name": "earliest_next_report",
     "description": "Earliest legal next report time after a duty release (RULE-REST-04, 12h).",
     "parameters": {"type": "object", "properties": {
         "release_utc": {"type": "string", "description": "ISO UTC, e.g. 2026-09-16T15:30:00Z"}},
         "required": ["release_utc"]}},
    {"name": "get_duty_totals",
     "description": "Duty-hour totals per crew over a window ending on a date (history + rostered plan), optionally only those above a threshold.",
     "parameters": {"type": "object", "properties": {
         "end_date": {"type": "string"}, "days": {"type": "integer", "default": 7},
         "min_hours": {"type": "number", "default": 0}},
         "required": ["end_date"]}},
    # ---------- Tier 3 ----------
    {"name": "recommend_cover",
     "description": "TIER 3: ranked rule-compliant options to cover a sick/unavailable crew member's pairing: own-base reserves, day-off callouts, other-base reserve + deadhead, cancellation fallback. Each option has cost (INR), delay, rules checked, reasoning; illegal candidates listed with the exact rule breach. ALWAYS use this for 'what should I do' / recovery questions.",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string", "description": "the unavailable crew member"},
         "from_date": {"type": "string", "description": "first date they are out, YYYY-MM-DD"},
         "callout_utc": {"type": "string", "description": "ISO UTC time the sick call was made"},
         "pairing_id": {"type": "string", "description": "optional: scope to this pairing only"}},
         "required": ["crew_id", "from_date"]}},
    # ---------- Tier 4: ACTIONS (human-in-the-loop) ----------
    {"name": "propose_record_sick_call",
     "description": "ACTION (requires user approval): propose marking a crew member sick from a date. Call this PROACTIVELY whenever a sick call is reported (not hypothetical), alongside simulate_sick_call and recommend_cover. Updates crew status and removes their reserve days once the USER approves. Never applied automatically — tell the user to click Yes/approve.",
     "parameters": {"type": "object", "properties": {
         "crew_id": {"type": "string"}, "from_date": {"type": "string"}},
         "required": ["crew_id", "from_date"]}},
    {"name": "propose_apply_cover",
     "description": "ACTION (requires user approval): propose replacing out_crew_id with in_crew_id on a pairing. Call this IMMEDIATELY when the user picks one of the recommend_cover options. All 7 legality rules plus rank/status are re-checked at apply time; illegal assignments are refused. Never applied automatically — tell the user to click Yes/approve.",
     "parameters": {"type": "object", "properties": {
         "pairing_id": {"type": "string"},
         "out_crew_id": {"type": "string", "description": "crew member being replaced"},
         "in_crew_id": {"type": "string", "description": "crew member taking over"},
         "from_date": {"type": "string", "description": "optional YYYY-MM-DD"}},
         "required": ["pairing_id", "out_crew_id", "in_crew_id"]}},
    {"name": "propose_cancel_pairing_flights",
     "description": "ACTION (requires user approval): propose cancelling a pairing's flight legs from a date (last-resort option). Never applied automatically — tell the user to click Yes/approve.",
     "parameters": {"type": "object", "properties": {
         "pairing_id": {"type": "string"}, "from_date": {"type": "string"}},
         "required": ["pairing_id", "from_date"]}},
    {"name": "get_change_log",
     "description": "List all database changes applied so far (approved actions with before/after detail). Empty after a revert to the original database.",
     "parameters": {"type": "object", "properties": {}}},
]


def _propose(action):
    from . import actions as A

    def _fn(**params):
        label = A.REGISTRY[action][1]
        detail = ", ".join(f"{k}={v}" for k, v in params.items())
        return A.propose(action, params, f"{label}: {detail}")
    return _fn


def _get_change_log():
    from . import actions as A
    return {"changes_applied": A.change_log()}

DISPATCH = {
    "get_reserves": L.get_reserves,
    "get_duty_remaining": L.get_duty_remaining,
    "get_departures": L.get_departures,
    "get_expiring_certs": L.get_expiring_certs,
    "get_crew_profile": L.get_crew_profile,
    "get_pairing": L.get_pairing,
    "get_pairings_for_crew": L.get_pairings_for_crew,
    "get_pairing_for_aircraft": L.get_pairing_for_aircraft,
    "get_crew_by_filter": L.get_crew_by_filter,
    "get_costs": L.get_costs,
    "get_rules": L.get_rules,
    "get_risk_signals": L.get_risk_signals,
    "simulate_sick_call": S.simulate_sick_call,
    "simulate_reassignment": S.simulate_reassignment,
    "simulate_station_closure": S.simulate_station_closure,
    "simulate_delay": S.simulate_delay,
    "simulate_cancellation": S.simulate_cancellation,
    "earliest_next_report": S.earliest_next_report,
    "get_duty_totals": S.get_duty_totals,
    "recommend_cover": recommend_cover,
    "propose_record_sick_call": _propose("record_sick_call"),
    "propose_apply_cover": _propose("apply_cover"),
    "propose_cancel_pairing_flights": _propose("cancel_pairing_flights"),
    "get_change_log": _get_change_log,
}


def openai_tool_specs():
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["parameters"]}} for t in TOOLS]
