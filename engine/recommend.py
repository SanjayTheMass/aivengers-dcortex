"""Tier 3 — ranked, rule-compliant cover recommendations with costs and reasoning.

Candidate order of preference (mirrors the dataset's worked scenarios):
1. Own-base reserve callout (cheapest, no delay)
2. Day-off callout at the pairing's start base
3. Other-base reserve + deadhead positioning (deadhead cost + delay cost)
4. Cancel the remaining pairing legs (last resort)
Options are ranked: legal first, then lowest cost, then lowest delay.
"""
import math
from datetime import timedelta

from .db import get_con, rows
from .rules import FMT, putc, check_assignment
from .simulate import simulate_sick_call

PILOT_RANKS = ("Captain", "First Officer")


def _callout_cost(costs, rank, kind):
    if rank in PILOT_RANKS:
        return costs["reserve_callout_pilot"] if kind == "reserve" else costs["dayoff_callout_pilot"]
    return costs["reserve_callout_cabin"] if kind == "reserve" else costs["dayoff_callout_cabin"]


def recommend_cover(crew_id, from_date, callout_utc=None, pairing_id=None):
    """Ranked options to cover the pairing(s) lost when `crew_id` is out from `from_date`.
    Optionally scope to one pairing_id."""
    con = get_con()
    impact = simulate_sick_call(crew_id, from_date, pairing_id=pairing_id)
    if not impact["pairings_broken"]:
        con.close()
        return {"error": f"{crew_id} has no assignments on/after {from_date}"}
    pairing_id = impact["pairings_broken"][0]
    rank = impact["rank_needed"]
    costs = {r["key"]: r["value_inr"] for r in rows(con, "SELECT * FROM costs")}

    # pairing start context
    first = rows(con, """SELECT f.dep_station, f.dep_utc, pd.report_utc
                         FROM pairing_days pd
                         JOIN pairing_flights pf ON pf.pairing_id=pd.pairing_id AND pf.date=pd.date
                         JOIN flights f ON f.flight_id=pf.flight_id
                         WHERE pd.pairing_id=? AND pd.date>=?
                         ORDER BY pd.date, f.dep_utc LIMIT 1""", (pairing_id, from_date))[0]
    station, first_dep, report = first["dep_station"], putc(first["dep_utc"]), first["report_utc"]
    n_flights = len(impact["uncrewed_flights"])

    options, excluded = [], []

    def consider(cand_id, action, base_cost, delay_hours=0.0, is_reserve=False):
        chk = check_assignment(cand_id, pairing_id, from_date=from_date,
                               callout_utc=callout_utc, is_reserve_callout=is_reserve)
        if "error" in chk:
            return
        if not chk["legal"]:
            excluded.append({"crew_id": cand_id, "reason": "; ".join(chk["issues"])})
            return
        cost = base_cost
        if delay_hours:
            cost += delay_hours * costs["delay_cost_per_duty_hour"]
        options.append({
            "action": action, "crew_id": cand_id, "legal": True,
            "rules_checked": chk["rules_checked"],
            "cost_inr": round(cost), "delay_hours": delay_hours,
            "reasoning": _reasoning(con, cand_id, is_reserve, delay_hours, chk),
        })

    # ---- 1. own-base reserves ----
    own_reserves = rows(con, """SELECT r.crew_id FROM reserve_days r JOIN crew c USING(crew_id)
                                WHERE r.base=? AND r.date=? AND c.rank=?""",
                        (station, from_date, rank))
    for r in own_reserves:
        consider(r["crew_id"], f"Assign {rank} {r['crew_id']} (reserve callout)",
                 _callout_cost(costs, rank, "reserve"), is_reserve=True)

    # ---- 2. day-off callouts at the start base ----
    dayoff = rows(con, """
        SELECT c.crew_id FROM crew c
        WHERE c.rank=? AND c.base=? AND c.status='active' AND c.crew_id<>?
          AND c.crew_id NOT IN (SELECT crew_id FROM reserve_days WHERE date=?)
          AND c.crew_id NOT IN (
            SELECT pc.crew_id FROM pairing_crew pc
            JOIN pairing_days pd ON pd.pairing_id=pc.pairing_id
            WHERE pd.date>=? AND pd.pairing_id=?)""",
        (rank, station, crew_id, from_date, from_date, pairing_id))
    for r in dayoff:
        consider(r["crew_id"], f"Assign {rank} {r['crew_id']} (day-off callout)",
                 _callout_cost(costs, rank, "dayoff"))

    # ---- 3. other-base reserves + deadhead ----
    other = rows(con, """SELECT r.crew_id, r.base FROM reserve_days r JOIN crew c USING(crew_id)
                         WHERE r.base<>? AND r.date=? AND c.rank=?""",
                 (station, from_date, rank))
    for r in other:
        dh = rows(con, """SELECT flight_no, arr_utc FROM flights
                          WHERE dep_station=? AND arr_station=? AND date=?
                          ORDER BY dep_utc LIMIT 1""", (r["base"], station, from_date))
        if not dh:
            excluded.append({"crew_id": r["crew_id"],
                             "reason": f"no positioning flight {r['base']}->{station} on {from_date}"})
            continue
        # crew can report ~1h after the positioning flight lands
        ready = putc(dh[0]["arr_utc"]) + timedelta(hours=1)
        delay = max(0.0, math.ceil((ready - first_dep).total_seconds() / 3600))
        consider(r["crew_id"],
                 f"Assign {rank} {r['crew_id']} (reserve callout + deadhead {dh[0]['flight_no']} "
                 f"from {r['base']}, first departure delayed ~{delay:.1f}h)",
                 _callout_cost(costs, rank, "reserve") + costs["deadhead_positioning"],
                 delay_hours=float(delay), is_reserve=True)

    # ---- 4. cancellation fallback ----
    options_sorted = sorted(options, key=lambda o: (o["cost_inr"], o["delay_hours"], o["crew_id"]))
    options_sorted.append({
        "action": f"Cancel all {n_flights} flights of the pairing", "crew_id": None,
        "legal": True, "rules_checked": [], "delay_hours": 0.0,
        "cost_inr": round(n_flights * costs["cancellation_per_flight"]),
        "reasoning": f"Last resort: {impact['passengers_affected']} passengers affected.",
    })
    for i, o in enumerate(options_sorted, 1):
        o["rank"] = i
    con.close()
    return {
        "query": f"{rank} {crew_id} out from {from_date} (pairing {pairing_id})",
        "pairing_id": pairing_id,
        "uncovered_flights": impact["uncrewed_flights"],
        "passengers_affected": impact["passengers_affected"],
        "required_report_utc": report,
        "options": options_sorted,
        "excluded_candidates": excluded,
    }


def _reasoning(con, cand_id, is_reserve, delay_hours, chk):
    c = rows(con, "SELECT * FROM crew WHERE crew_id=?", (cand_id,))[0]
    ratings = [r["aircraft_type"] for r in rows(
        con, "SELECT aircraft_type FROM crew_ratings WHERE crew_id=?", (cand_id,))]
    bits = [f"{c['base']}-based", f"{'/'.join(ratings)}-rated",
            f"reachable in {c['reachability_minutes']} min"]
    if is_reserve:
        bits.insert(0, "on reserve")
    if delay_hours:
        bits.append(f"deadhead delays first departure ~{delay_hours:.1f}h")
    if chk["deadhead_required"]:
        bits.append("deadhead cost applies (RULE-BASE-07)")
    return ", ".join(bits) + "; all 7 rules pass."
