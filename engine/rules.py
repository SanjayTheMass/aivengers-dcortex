"""Legality engine — deterministic checks for the 7 rules.

Semantics mirror data/rules.json and the dataset validator:
- duty period = report_utc..release_utc; duty hours = its length
- flight (block) hours = sum of leg block_hours
- windows are UTC calendar days, inclusive of the duty date
- accruals = duty_history (28 days ending 2026-09-14) + rostered duties + proposed duties
Every check returns {"rule_id", "legal", "detail"}.
"""
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta

from .db import get_con, rows

FMT = "%Y-%m-%dT%H:%M:%SZ"


def putc(s):
    return datetime.strptime(s, FMT)


def hm(hours):
    """1.33 -> '1h20m'"""
    total_min = round(hours * 60)
    return f"{total_min // 60}h{total_min % 60:02d}m"


@dataclass
class Duty:
    """One proposed or rostered duty day."""
    date: str
    report_utc: str
    release_utc: str
    duty_hours: float
    flight_hours: float
    sectors: int
    pairing_id: str = ""
    aircraft_type: str = ""
    flights: list = field(default_factory=list)

    @property
    def d(self):
        return date.fromisoformat(self.date)


def pairing_duties(con, pairing_id, from_date=None, delay_minutes=0):
    """Build Duty objects for a pairing's days (optionally from a start date,
    optionally with all times shifted by a delay)."""
    duties = []
    for day in rows(con, """SELECT date, report_utc, release_utc FROM pairing_days
                            WHERE pairing_id=? ORDER BY date""", (pairing_id,)):
        if from_date and day["date"] < from_date:
            continue
        legs = rows(con, """SELECT f.* FROM pairing_flights pf
                            JOIN flights f USING(flight_id)
                            WHERE pf.pairing_id=? AND pf.date=? ORDER BY f.dep_utc""",
                    (pairing_id, day["date"]))
        rep, rel = putc(day["report_utc"]), putc(day["release_utc"])
        if delay_minutes:
            # crew already reported on time; delay extends the duty's end only
            rel += timedelta(minutes=delay_minutes)
        duties.append(Duty(
            date=day["date"],
            report_utc=rep.strftime(FMT),
            release_utc=rel.strftime(FMT),
            duty_hours=round((rel - rep).total_seconds() / 3600, 2),
            flight_hours=round(sum(l["block_hours"] for l in legs), 2),
            sectors=len(legs),
            pairing_id=pairing_id,
            aircraft_type=legs[0]["aircraft_type"] if legs else "",
            flights=[l["flight_id"] for l in legs],
        ))
    return duties


def crew_rostered_duties(con, crew_id, exclude_pairing=None):
    """All rostered duties for a crew member from the roster tables."""
    duties = []
    for r in rows(con, """SELECT pd.pairing_id FROM pairing_crew pc
                          JOIN pairing_days pd USING(pairing_id)
                          WHERE pc.crew_id=? GROUP BY pd.pairing_id""", (crew_id,)):
        if r["pairing_id"] == exclude_pairing:
            continue
        duties.extend(pairing_duties(con, r["pairing_id"]))
    return sorted(duties, key=lambda d: d.report_utc)


def history_map(con, crew_id):
    """date -> (duty_hours, flight_hours) from the 28-day snapshot history."""
    return {date.fromisoformat(r["date"]): (r["duty_hours"], r["flight_hours"])
            for r in rows(con, "SELECT * FROM duty_history WHERE crew_id=?", (crew_id,))}


def window_sum(hist, duties, end, days, kind):
    """Sum duty (kind=0) or flight (kind=1) hours over the calendar-day window
    ending at `end` (inclusive), combining history and duties."""
    start = end - timedelta(days=days - 1)
    s = sum(v[kind] for d, v in hist.items() if start <= d <= end)
    s += sum((du.duty_hours if kind == 0 else du.flight_hours)
             for du in duties if start <= du.d <= end)
    return s


# ---------------------------------------------------------------- rule checks

def check_fdp(duty):
    limit = 13.0 - 0.5 * max(0, duty.sectors - 2)
    legal = duty.duty_hours <= limit + 1e-6
    detail = (f"FDP {duty.duty_hours}h vs limit {limit}h "
              f"({duty.sectors} sectors) on {duty.date}")
    if not legal:
        detail = (f"FDP would be {hm(duty.duty_hours)} exceeding the {limit}h limit "
                  f"({duty.sectors} sectors) by {hm(duty.duty_hours - limit)} on {duty.date}")
    return {"rule_id": "RULE-FDP-01", "legal": legal, "detail": detail}


def check_duty_7d(hist, existing, proposed):
    issues = []
    all_duties = existing + proposed
    for du in proposed:
        total = window_sum(hist, all_duties, du.d, 7, 0)
        if total > 60 + 1e-6:
            issues.append(f"would exceed 60h/7d by {hm(total - 60)} on {du.date} "
                          f"(total {round(total, 2)}h)")
    return {"rule_id": "RULE-DUTY-02", "legal": not issues,
            "detail": "; ".join(issues) if issues else "within 60h/7d on all proposed days"}


def check_flight_28d(hist, existing, proposed):
    issues = []
    all_duties = existing + proposed
    for du in proposed:
        total = window_sum(hist, all_duties, du.d, 28, 1)
        if total > 100 + 1e-6:
            issues.append(f"would exceed 100h/28d by {hm(total - 100)} on {du.date} "
                          f"(total {round(total, 2)}h)")
    return {"rule_id": "RULE-FLT-03", "legal": not issues,
            "detail": "; ".join(issues) if issues else "within 100h/28d on all proposed days"}


def check_rest(existing, proposed):
    """Min 12h between release and next report across the merged duty timeline;
    overlapping duties are also flagged here."""
    issues = []
    timeline = sorted(existing + proposed, key=lambda d: d.report_utc)
    proposed_keys = {(d.pairing_id, d.date) for d in proposed}
    for a, b in zip(timeline, timeline[1:]):
        # only flag gaps involving a proposed duty
        if (a.pairing_id, a.date) not in proposed_keys and \
           (b.pairing_id, b.date) not in proposed_keys:
            continue
        gap = (putc(b.report_utc) - putc(a.release_utc)).total_seconds() / 3600
        if gap < 0:
            issues.append(f"duty {b.pairing_id} {b.date} overlaps duty {a.pairing_id} {a.date}")
        elif gap < 12 - 1e-6:
            issues.append(f"rest between {a.pairing_id} ({a.date}) and {b.pairing_id} "
                          f"({b.date}) is {hm(gap)} < 12h")
    return {"rule_id": "RULE-REST-04", "legal": not issues,
            "detail": "; ".join(issues) if issues else "12h minimum rest satisfied"}


def check_rating(con, crew_id, aircraft_type):
    ok = bool(rows(con, "SELECT 1 FROM crew_ratings WHERE crew_id=? AND aircraft_type=?",
                   (crew_id, aircraft_type)))
    return {"rule_id": "RULE-QUAL-05", "legal": ok,
            "detail": (f"{crew_id} holds {aircraft_type} rating" if ok
                       else f"{crew_id} is NOT rated on {aircraft_type}")}


def check_certs(con, crew_id, duty_dates):
    issues = []
    certs = rows(con, "SELECT * FROM certifications WHERE crew_id=?", (crew_id,))
    for ds in duty_dates:
        d = date.fromisoformat(ds)
        for c in certs:
            # dataset semantics (per validator): a cert is valid while valid_to >= date
            if date.fromisoformat(c["valid_to"]) < d:
                issues.append(f"{c['cert_type']} invalid on {ds} "
                              f"(expired {c['valid_to']})")
    return {"rule_id": "RULE-CERT-06", "legal": not issues,
            "detail": "; ".join(sorted(set(issues))) if issues else "all certifications valid on duty dates"}


def check_base(con, crew_id, pairing_start_station, callout_utc=None, callout_date=None,
               required_report_utc=None):
    """RULE-BASE-07: reserve callout from own base only; other-base cover needs
    deadhead positioning. Per dataset semantics the reserve's on-call window must
    cover the required report time."""
    c = rows(con, "SELECT base FROM crew WHERE crew_id=?", (crew_id,))
    base = c[0]["base"] if c else None
    parts, legal, deadhead = [], True, False
    if base != pairing_start_station:
        deadhead = True
        parts.append(f"{crew_id} based {base}, pairing starts {pairing_start_station}: "
                     "deadhead positioning required (cost applies)")
    if callout_date:
        rd = rows(con, "SELECT * FROM reserve_days WHERE crew_id=? AND date=?",
                  (crew_id, callout_date))
        if not rd:
            parts.append(f"{crew_id} is not on reserve on {callout_date}")
        else:
            w = rd[0]
            t = (required_report_utc or callout_utc or "")[11:16]
            if t and not (w["window_start"] <= t <= w["window_end"]):
                legal = False
                parts.append(f"reserve on-call window {w['window_start']}-{w['window_end']}Z "
                             f"does not cover required report {t}Z")
            elif t:
                parts.append(f"required report {t}Z falls inside on-call window "
                             f"{w['window_start']}-{w['window_end']}Z")
    return {"rule_id": "RULE-BASE-07", "legal": legal, "deadhead_required": deadhead,
            "detail": "; ".join(parts) if parts else f"own-base callout ({base})"}


# ---------------------------------------------------------- orchestrator

def check_assignment(crew_id, pairing_id, from_date=None, callout_utc=None,
                     delay_minutes=0, is_reserve_callout=False):
    """Run all 7 rules for assigning `crew_id` to `pairing_id` (from a date).
    Returns overall legality plus per-rule verdicts with human-readable detail."""
    con = get_con()
    proposed = pairing_duties(con, pairing_id, from_date, delay_minutes)
    if not proposed:
        con.close()
        return {"error": f"pairing {pairing_id} has no days on/after {from_date}"}
    existing = crew_rostered_duties(con, crew_id, exclude_pairing=pairing_id)
    hist = history_map(con, crew_id)

    first_leg = rows(con, """SELECT f.dep_station FROM pairing_flights pf
                             JOIN flights f USING(flight_id)
                             WHERE pf.pairing_id=? AND pf.date=? ORDER BY f.dep_utc LIMIT 1""",
                     (pairing_id, proposed[0].date))
    start_station = first_leg[0]["dep_station"] if first_leg else None

    checks = [check_fdp(du) for du in proposed]
    # collapse FDP to one verdict (worst day)
    fdp_bad = [c for c in checks if not c["legal"]]
    fdp = fdp_bad[0] if fdp_bad else {
        "rule_id": "RULE-FDP-01", "legal": True,
        "detail": "; ".join(c["detail"] for c in checks)}

    results = [
        fdp,
        check_duty_7d(hist, existing, proposed),
        check_flight_28d(hist, existing, proposed),
        check_rest(existing, proposed),
        check_rating(con, crew_id, proposed[0].aircraft_type),
        check_certs(con, crew_id, [du.date for du in proposed]),
        check_base(con, crew_id, start_station, callout_utc,
                   proposed[0].date if (is_reserve_callout or callout_utc) else None,
                   required_report_utc=proposed[0].report_utc),
    ]
    con.close()
    return {
        "crew_id": crew_id,
        "pairing_id": pairing_id,
        "from_date": proposed[0].date,
        "proposed_duties": [
            {"date": du.date, "report_utc": du.report_utc, "release_utc": du.release_utc,
             "duty_hours": du.duty_hours, "flight_hours": du.flight_hours,
             "sectors": du.sectors, "flights": du.flights} for du in proposed],
        "legal": all(r["legal"] for r in results),
        "rules_checked": [r["rule_id"] for r in results],
        "issues": [f"{r['rule_id']}: {r['detail']}" for r in results if not r["legal"]],
        "checks": results,
        "deadhead_required": results[-1].get("deadhead_required", False),
    }
