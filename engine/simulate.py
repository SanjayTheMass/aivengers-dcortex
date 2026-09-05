"""Tier 2 — consequence & simulation tools. Pure reads; never mutate the DB."""
from datetime import datetime, timedelta

from .db import get_con, rows
from .rules import (FMT, putc, check_assignment, pairing_duties,
                    crew_rostered_duties, history_map, window_sum, check_fdp, Duty)


def simulate_sick_call(crew_id, from_date, reported_utc=None, pairing_id=None):
    """Crew member unavailable from a date: uncrewed flights (per day),
    broken pairings, passengers affected, and remaining-crew context.
    If pairing_id is given, the sickness is scoped to that pairing only."""
    con = get_con()
    q = """SELECT DISTINCT pd.pairing_id FROM pairing_crew pc
           JOIN pairing_days pd USING(pairing_id)
           WHERE pc.crew_id=? AND pd.date>=?"""
    params = [crew_id, from_date]
    if pairing_id:
        q += " AND pd.pairing_id=?"
        params.append(pairing_id)
    pairings = rows(con, q, params)
    impact = {"query": f"{crew_id} unavailable from {from_date}",
              "uncrewed_flights": [], "flights_by_day": {},
              "pairings_broken": [], "passengers_affected": 0,
              "remaining_crew": []}
    for p in pairings:
        pid = p["pairing_id"]
        impact["pairings_broken"].append(pid)
        for du in pairing_duties(con, pid, from_date):
            impact["flights_by_day"][du.date] = du.flights
            impact["uncrewed_flights"].extend(du.flights)
            seats = rows(con, """SELECT SUM(f.seats) s FROM pairing_flights pf
                                 JOIN flights f USING(flight_id)
                                 WHERE pf.pairing_id=? AND pf.date=?""", (pid, du.date))
            impact["passengers_affected"] += seats[0]["s"] or 0
        impact["remaining_crew"].extend(rows(con, """
            SELECT pc.crew_id, pc.role FROM pairing_crew pc
            WHERE pc.pairing_id=? AND pc.crew_id != ?""", (pid, crew_id)))
    role = rows(con, "SELECT rank FROM crew WHERE crew_id=?", (crew_id,))
    impact["rank_needed"] = role[0]["rank"] if role else None
    con.close()
    return impact


def simulate_reassignment(crew_id, pairing_id, from_date=None, callout_utc=None,
                          is_reserve_callout=False):
    """Would assigning crew_id to pairing_id breach any rule? Full per-rule detail."""
    return check_assignment(crew_id, pairing_id, from_date=from_date,
                            callout_utc=callout_utc,
                            is_reserve_callout=is_reserve_callout)


def simulate_station_closure(station, date, start_hhmm, end_hhmm):
    """Flights unable to depart from or arrive at a closed station in the window."""
    start = f"{date}T{start_hhmm}:00Z"
    end = f"{date}T{end_hhmm}:00Z"
    con = get_con()
    affected = rows(con, """
        SELECT *, CASE WHEN dep_station=? AND dep_utc>=? AND dep_utc<=?
                       THEN 'departure blocked' ELSE 'arrival blocked' END AS reason
        FROM flights
        WHERE (dep_station=? AND dep_utc>=? AND dep_utc<=?)
           OR (arr_station=? AND arr_utc>=? AND arr_utc<=?)
        ORDER BY dep_utc""",
        (station, start, end, station, start, end, station, start, end))
    flight_ids = [f["flight_id"] for f in affected]
    pairings = rows(con, f"""
        SELECT DISTINCT pairing_id FROM pairing_flights
        WHERE flight_id IN ({','.join('?' * len(flight_ids))})""", flight_ids) \
        if flight_ids else []
    crew_affected = rows(con, f"""
        SELECT DISTINCT pc.crew_id, pc.role, pc.pairing_id FROM pairing_crew pc
        WHERE pc.pairing_id IN ({','.join('?' * len(pairings))})""",
        [p["pairing_id"] for p in pairings]) if pairings else []
    con.close()
    return {
        "station": station, "closure_window_utc": [start, end],
        "affected_flights": [{"flight_id": f["flight_id"], "dep_utc": f["dep_utc"],
                              "arr_utc": f["arr_utc"], "route": f"{f['dep_station']}-{f['arr_station']}",
                              "seats": f["seats"], "reason": f["reason"]} for f in affected],
        "affected_flight_ids": flight_ids,
        "passengers_at_risk": sum(f["seats"] or 0 for f in affected),
        "pairings_affected": [p["pairing_id"] for p in pairings],
        "crew_affected": crew_affected,
    }


def simulate_delay(aircraft, date, delay_minutes):
    """Shift a tail's whole day by N minutes; re-check FDP (and duty windows)
    for the rostered crew."""
    con = get_con()
    pairings = rows(con, """
        SELECT p.pairing_id FROM pairings p JOIN pairing_days pd USING(pairing_id)
        WHERE p.aircraft=? AND pd.date=?""", (aircraft, date))
    out = {"aircraft": aircraft, "date": date, "delay_minutes": delay_minutes,
           "pairings": []}
    for p in pairings:
        pid = p["pairing_id"]
        base = [d for d in pairing_duties(con, pid) if d.date == date]
        delayed = [d for d in pairing_duties(con, pid, delay_minutes=delay_minutes)
                   if d.date == date]
        crew = rows(con, "SELECT crew_id, role FROM pairing_crew WHERE pairing_id=?", (pid,))
        entry = {"pairing_id": pid, "crew": crew, "days": []}
        for b, du in zip(base, delayed):
            fdp = check_fdp(du)
            # delayed release also extends duty hours in the 7d window
            crew_duty_checks = []
            for m in crew:
                hist = history_map(con, m["crew_id"])
                existing = crew_rostered_duties(con, m["crew_id"], exclude_pairing=pid)
                total = window_sum(hist, existing + [du], du.d, 7, 0)
                crew_duty_checks.append({
                    "crew_id": m["crew_id"], "role": m["role"],
                    "duty_7d_total": round(total, 2),
                    "legal": total <= 60 + 1e-6})
            entry["days"].append({
                "date": du.date,
                "original": {"report_utc": b.report_utc, "release_utc": b.release_utc,
                             "duty_hours": b.duty_hours},
                "delayed": {"report_utc": du.report_utc, "release_utc": du.release_utc,
                            "duty_hours": du.duty_hours},
                "fdp_check": fdp,
                "duty_7d_checks": crew_duty_checks,
            })
        out["pairings"].append(entry)
    con.close()
    return out


def simulate_cancellation(flight_id):
    """Passengers affected and direct cancellation cost for one leg."""
    con = get_con()
    f = rows(con, "SELECT * FROM flights WHERE flight_id=?", (flight_id,))
    cost = rows(con, "SELECT value_inr FROM costs WHERE key='cancellation_per_flight'")
    con.close()
    if not f:
        return {"error": f"unknown flight {flight_id}"}
    return {"flight_id": flight_id, "passengers": f[0]["seats"],
            "cancellation_cost_inr": cost[0]["value_inr"],
            "route": f"{f[0]['dep_station']}-{f[0]['arr_station']}",
            "dep_utc": f[0]["dep_utc"]}


def earliest_next_report(release_utc):
    """RULE-REST-04: release + 12h."""
    t = putc(release_utc) + timedelta(hours=12)
    return {"release_utc": release_utc, "earliest_next_report_utc": t.strftime(FMT),
            "rule": "RULE-REST-04 (min 12h rest)"}


def get_duty_totals(end_date, days=7, min_hours=0.0):
    """Duty-hour totals per crew over the window ending end_date, combining
    history and rostered duties (Q26-style)."""
    con = get_con()
    crew = rows(con, "SELECT crew_id, name, rank FROM crew WHERE status='active'")
    out = []
    from datetime import date as _date
    end = _date.fromisoformat(end_date)
    for c in crew:
        hist = history_map(con, c["crew_id"])
        duties = crew_rostered_duties(con, c["crew_id"])
        total = window_sum(hist, duties, end, days, 0)
        if total >= min_hours:
            out.append({"crew_id": c["crew_id"], "name": c["name"], "rank": c["rank"],
                        "duty_hours": round(total, 2)})
    con.close()
    return sorted(out, key=lambda x: -x["duty_hours"])
