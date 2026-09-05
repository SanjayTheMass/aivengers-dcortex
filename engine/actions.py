"""Agentic ACTIONS — the only module allowed to mutate crewops.db.

- crewops_bkp.db is a pristine snapshot: created once by ensure_backup(),
  never modified afterwards.
- revert_to_backup() restores crewops.db from it (SQLite online backup API,
  safe even with other open connections).
- Every executor validates first, then returns:
    {"ok": True, "summary": str, "changes": [{"table","action","before","after"}, ...]}
  or {"error": str}. Nothing is written when an error is returned.
"""
import sqlite3

from .db import get_con, rows, DB_PATH
from .rules import check_assignment

BKP_PATH = DB_PATH.parent / "crewops_bkp.db"


def ensure_backup():
    """Create the pristine backup once. Never overwrites an existing one."""
    if not BKP_PATH.exists():
        src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(BKP_PATH)
        src.backup(dst)
        dst.close()
        src.close()
    return str(BKP_PATH)


def revert_to_backup():
    """Replace crewops.db content with the pristine crewops_bkp.db snapshot."""
    if not BKP_PATH.exists():
        return {"error": "crewops_bkp.db not found — nothing to revert to"}
    src, dst = sqlite3.connect(BKP_PATH), sqlite3.connect(DB_PATH)
    src.backup(dst)
    dst.close()
    src.close()
    return {"ok": True, "summary": "crewops.db restored from crewops_bkp.db"}


def record_sick_call(crew_id, from_date, **_):
    """Mark crew sick: crew.status -> 'sick', drop their reserve days from that date."""
    con = get_con()
    try:
        crew = rows(con, "SELECT * FROM crew WHERE crew_id=?", (crew_id,))
        if not crew:
            return {"error": f"unknown crew {crew_id}"}
        if crew[0]["status"] == "sick":
            return {"error": f"{crew_id} is already marked sick"}
        reserves = rows(con, "SELECT * FROM reserve_days WHERE crew_id=? AND date>=?",
                        (crew_id, from_date))
        changes = [{"table": "crew", "action": "update",
                    "before": {"crew_id": crew_id, "status": crew[0]["status"]},
                    "after": {"crew_id": crew_id, "status": "sick"}}]
        changes += [{"table": "reserve_days", "action": "delete", "before": r, "after": None}
                    for r in reserves]
        with con:
            con.execute("UPDATE crew SET status='sick' WHERE crew_id=?", (crew_id,))
            con.execute("DELETE FROM reserve_days WHERE crew_id=? AND date>=?",
                        (crew_id, from_date))
        return {"ok": True,
                "summary": f"{crew_id} marked sick from {from_date}; "
                           f"{len(reserves)} reserve day(s) removed",
                "changes": changes}
    finally:
        con.close()


def apply_cover(pairing_id, out_crew_id, in_crew_id, from_date=None, **_):
    """Replace out_crew with in_crew on a pairing. Re-checks all 7 legality rules
    first and refuses if the assignment is illegal. Also removes the incoming
    crew's reserve days on the pairing's remaining dates."""
    chk = check_assignment(in_crew_id, pairing_id, from_date=from_date)
    if chk.get("error"):
        return chk
    if not chk["legal"]:
        return {"error": f"assignment illegal, not applied: {'; '.join(chk['issues'])}"}
    con = get_con()
    try:
        out_row = rows(con, "SELECT * FROM pairing_crew WHERE pairing_id=? AND crew_id=?",
                       (pairing_id, out_crew_id))
        if not out_row:
            return {"error": f"{out_crew_id} is not assigned to {pairing_id}"}
        if rows(con, "SELECT 1 FROM pairing_crew WHERE pairing_id=? AND crew_id=?",
                (pairing_id, in_crew_id)):
            return {"error": f"{in_crew_id} is already on {pairing_id}"}
        role = out_row[0]["role"]
        in_rank = rows(con, "SELECT rank, status FROM crew WHERE crew_id=?", (in_crew_id,))
        if not in_rank:
            return {"error": f"unknown crew {in_crew_id}"}
        if in_rank[0]["rank"] != role:
            return {"error": f"rank mismatch: {in_crew_id} is a {in_rank[0]['rank']}, "
                             f"pairing slot requires {role}"}
        if in_rank[0]["status"] != "active":
            return {"error": f"{in_crew_id} is not active (status: {in_rank[0]['status']})"}
        dates = [d["date"] for d in rows(
            con, "SELECT date FROM pairing_days WHERE pairing_id=?" +
                 (" AND date>=?" if from_date else ""),
            (pairing_id, from_date) if from_date else (pairing_id,))]
        freed = rows(con, f"""SELECT * FROM reserve_days WHERE crew_id=?
                              AND date IN ({','.join('?' * len(dates))})""",
                     [in_crew_id] + dates) if dates else []
        changes = [{"table": "pairing_crew", "action": "update",
                    "before": dict(out_row[0]),
                    "after": {"pairing_id": pairing_id, "crew_id": in_crew_id, "role": role}}]
        changes += [{"table": "reserve_days", "action": "delete", "before": r, "after": None}
                    for r in freed]
        with con:
            con.execute("DELETE FROM pairing_crew WHERE pairing_id=? AND crew_id=?",
                        (pairing_id, out_crew_id))
            con.execute("INSERT INTO pairing_crew (pairing_id, crew_id, role) VALUES (?,?,?)",
                        (pairing_id, in_crew_id, role))
            for r in freed:
                con.execute("DELETE FROM reserve_days WHERE crew_id=? AND date=?",
                            (in_crew_id, r["date"]))
        return {"ok": True,
                "summary": f"{in_crew_id} covers {pairing_id} as {role} "
                           f"(replacing {out_crew_id}); rules checked: "
                           f"{', '.join(chk['rules_checked'])} — all pass",
                "changes": changes}
    finally:
        con.close()


def cancel_pairing_flights(pairing_id, from_date, **_):
    """Cancellation fallback: remove the pairing's flight legs from `from_date`
    (pairing_flights rows deleted; flights rows kept for the record)."""
    con = get_con()
    try:
        legs = rows(con, "SELECT * FROM pairing_flights WHERE pairing_id=? AND date>=?",
                    (pairing_id, from_date))
        if not legs:
            return {"error": f"no flights on {pairing_id} on/after {from_date}"}
        changes = [{"table": "pairing_flights", "action": "delete", "before": r, "after": None}
                   for r in legs]
        with con:
            con.execute("DELETE FROM pairing_flights WHERE pairing_id=? AND date>=?",
                        (pairing_id, from_date))
        return {"ok": True,
                "summary": f"cancelled {len(legs)} flight leg(s) of {pairing_id} "
                           f"from {from_date}",
                "changes": changes}
    finally:
        con.close()
