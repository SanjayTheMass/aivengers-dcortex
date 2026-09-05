"""Tier 1 — deterministic lookup tools. Each returns JSON-serializable data
with enough identifiers for the agent to cite its sources."""
import json
from .db import get_con, rows


def get_reserves(station, date, callout_utc_time=None, rank=None):
    """Reserve crew at a base on a date, with on-call windows.
    callout_utc_time ('HH:MM') filters to windows covering that time."""
    con = get_con()
    out = rows(con, """
        SELECT r.crew_id, c.name, c.rank, r.base, r.window_start, r.window_end,
               c.reachability_minutes
        FROM reserve_days r JOIN crew c USING(crew_id)
        WHERE r.base=? AND r.date=?
        ORDER BY c.rank, r.window_start""", (station, date))
    if callout_utc_time:
        out = [r for r in out if r["window_start"] <= callout_utc_time <= r["window_end"]]
    if rank:
        out = [r for r in out if r["rank"] == rank]
    for r in out:
        r["ratings"] = [x["aircraft_type"] for x in rows(
            con, "SELECT aircraft_type FROM crew_ratings WHERE crew_id=?", (r["crew_id"],))]
    con.close()
    return out


def get_duty_remaining(crew_id):
    """Duty/flight-hour headroom from the snapshot clocks (RULE-DUTY-02, RULE-FLT-03)."""
    con = get_con()
    r = rows(con, "SELECT * FROM duty_clocks WHERE crew_id=?", (crew_id,))
    con.close()
    if not r:
        return {"error": f"unknown crew {crew_id}"}
    c = r[0]
    return {
        "crew_id": crew_id,
        "as_of_utc": c["as_of_utc"],
        "duty_hours_7d": c["duty_hours_7d"],
        "duty_headroom_7d": round(60 - c["duty_hours_7d"], 2),
        "flight_hours_28d": c["flight_hours_28d"],
        "flight_headroom_28d": round(100 - c["flight_hours_28d"], 2),
        "last_rest_ended": c["last_rest_ended"],
        "rules": ["RULE-DUTY-02", "RULE-FLT-03"],
    }


def get_departures(station=None, date=None, from_utc=None, to_utc=None,
                   arr_station=None, flight_no=None):
    """Flights filtered by any combination of dep/arr station, date, UTC window, flight no."""
    q, p = "SELECT * FROM flights WHERE 1=1", []
    if station:
        q += " AND dep_station=?"; p.append(station)
    if arr_station:
        q += " AND arr_station=?"; p.append(arr_station)
    if date:
        q += " AND date=?"; p.append(date)
    if flight_no:
        q += " AND flight_no=?"; p.append(flight_no)
    if from_utc:
        q += " AND dep_utc>=?"; p.append(from_utc)
    if to_utc:
        q += " AND dep_utc<=?"; p.append(to_utc)
    con = get_con()
    out = rows(con, q + " ORDER BY dep_utc", p)
    con.close()
    return out


def get_expiring_certs(as_of_date, days=30):
    """Certifications expiring within N days of a date."""
    con = get_con()
    out = rows(con, """
        SELECT ct.crew_id, c.name, c.rank, c.base, ct.cert_type, ct.valid_to
        FROM certifications ct JOIN crew c USING(crew_id)
        WHERE ct.valid_to >= ? AND ct.valid_to <= date(?, '+' || ? || ' days')
        ORDER BY ct.valid_to""", (as_of_date, as_of_date, days))
    con.close()
    return out


def get_crew_profile(crew_id):
    """Full crew profile: bio, ratings, certs, clocks, reserve days, risk score."""
    con = get_con()
    c = rows(con, "SELECT * FROM crew WHERE crew_id=?", (crew_id,))
    if not c:
        con.close()
        return {"error": f"unknown crew {crew_id}"}
    out = c[0]
    out["ratings"] = [x["aircraft_type"] for x in rows(
        con, "SELECT aircraft_type FROM crew_ratings WHERE crew_id=?", (crew_id,))]
    out["certifications"] = rows(
        con, "SELECT cert_type, valid_from, valid_to FROM certifications WHERE crew_id=?",
        (crew_id,))
    out["duty_clock"] = (rows(con, "SELECT * FROM duty_clocks WHERE crew_id=?", (crew_id,)) or [None])[0]
    out["reserve_days"] = rows(
        con, "SELECT date, window_start, window_end FROM reserve_days WHERE crew_id=? ORDER BY date",
        (crew_id,))
    risk = rows(con, "SELECT * FROM risk_signals WHERE crew_id=?", (crew_id,))
    if risk:
        out["disruption_risk_score"] = risk[0]["disruption_risk_score"]
        out["risk_drivers"] = json.loads(risk[0]["drivers_json"])
    con.close()
    return out


def get_pairing(pairing_id):
    """Pairing detail: days, flights (ordered), crew and roles."""
    con = get_con()
    p = rows(con, "SELECT * FROM pairings WHERE pairing_id=?", (pairing_id,))
    if not p:
        con.close()
        return {"error": f"unknown pairing {pairing_id}"}
    out = p[0]
    out["days"] = rows(con, """
        SELECT date, report_utc, release_utc FROM pairing_days
        WHERE pairing_id=? ORDER BY date""", (pairing_id,))
    for d in out["days"]:
        d["flights"] = rows(con, """
            SELECT f.* FROM pairing_flights pf JOIN flights f USING(flight_id)
            WHERE pf.pairing_id=? AND pf.date=? ORDER BY pf.seq""",
            (pairing_id, d["date"]))
    out["crew"] = rows(con, """
        SELECT pc.crew_id, pc.role, c.name, c.base FROM pairing_crew pc
        JOIN crew c USING(crew_id) WHERE pc.pairing_id=? ORDER BY pc.role""",
        (pairing_id,))
    con.close()
    return out


def get_pairings_for_crew(crew_id, date=None):
    """Which pairings/dates a crew member works."""
    con = get_con()
    q = """SELECT pd.pairing_id, pd.date, pd.report_utc, pd.release_utc, pc.role
           FROM pairing_crew pc JOIN pairing_days pd USING(pairing_id)
           WHERE pc.crew_id=?"""
    p = [crew_id]
    if date:
        q += " AND pd.date=?"; p.append(date)
    out = rows(con, q + " ORDER BY pd.date", p)
    con.close()
    return out


def get_pairing_for_aircraft(aircraft, date):
    """Pairing operating a given tail on a given date."""
    con = get_con()
    out = rows(con, """
        SELECT p.pairing_id, pd.date, pd.report_utc, pd.release_utc
        FROM pairings p JOIN pairing_days pd USING(pairing_id)
        WHERE p.aircraft=? AND pd.date=?""", (aircraft, date))
    con.close()
    return out


def get_crew_by_filter(base=None, rank=None, rating=None, status="active"):
    """List crew by base/rank/rating."""
    q = """SELECT DISTINCT c.* FROM crew c
           LEFT JOIN crew_ratings r ON r.crew_id=c.crew_id WHERE 1=1"""
    p = []
    if base:
        q += " AND c.base=?"; p.append(base)
    if rank:
        q += " AND c.rank=?"; p.append(rank)
    if rating:
        q += " AND r.aircraft_type=?"; p.append(rating)
    if status:
        q += " AND c.status=?"; p.append(status)
    con = get_con()
    out = rows(con, q + " ORDER BY c.crew_id", p)
    con.close()
    return out


def get_costs():
    """Cost table (INR)."""
    con = get_con()
    out = {r["key"]: r["value_inr"] for r in rows(con, "SELECT * FROM costs")}
    con.close()
    return out


def get_rules():
    """Legality ruleset with parameters."""
    con = get_con()
    out = rows(con, "SELECT * FROM rules")
    for r in out:
        r["params"] = json.loads(r.pop("params_json") or "{}")
    con.close()
    return out


def get_risk_signals(min_score=0.0):
    """Disruption-risk scores, highest first."""
    con = get_con()
    out = rows(con, """
        SELECT rs.crew_id, c.name, c.rank, rs.disruption_risk_score, rs.drivers_json
        FROM risk_signals rs JOIN crew c USING(crew_id)
        WHERE rs.disruption_risk_score >= ?
        ORDER BY rs.disruption_risk_score DESC""", (min_score,))
    for r in out:
        r["drivers"] = json.loads(r.pop("drivers_json"))
    con.close()
    return out
