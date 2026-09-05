"""Human-in-the-loop action layer.

The agent can only PROPOSE actions (propose() -> pending_actions row).
Nothing touches crewops.db until the user explicitly approves — via the
Streamlit Yes button or POST /actions/{id}/approve. Every applied action is
recorded in change_log (appstate.db); reverting the DB clears the log.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import actions as X
from .sessions import _con, _now, rows

# action name -> (executor, human label)
REGISTRY = {
    "record_sick_call": (X.record_sick_call, "Record sick call"),
    "apply_cover": (X.apply_cover, "Apply cover assignment"),
    "cancel_pairing_flights": (X.cancel_pairing_flights, "Cancel pairing flights"),
}


def propose(action, params, summary, session_id=None):
    if action not in REGISTRY:
        return {"error": f"unknown action '{action}'"}
    # dedupe: identical action already awaiting approval -> return it
    for a in list_pending():
        if a["action"] == action and a["params"] == params:
            return {"action_id": a["id"], "action": action, "params": params,
                    "summary": a["summary"], "status": "awaiting_user_approval",
                    "note": "Already proposed and still awaiting the user's approval."}
    aid = uuid.uuid4().hex[:12]
    with _con() as con:
        con.execute("""INSERT INTO pending_actions (id,session_id,action,params,summary,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (aid, session_id, action, json.dumps(params), summary, _now()))
    return {"action_id": aid, "action": action, "params": params, "summary": summary,
            "status": "awaiting_user_approval",
            "note": "NOT applied yet. The user must approve this action (Yes button) "
                    "before the database is changed."}


def list_pending(session_id=None):
    q = "SELECT * FROM pending_actions WHERE status='pending'"
    args = ()
    if session_id:
        q += " AND session_id=?"
        args = (session_id,)
    with _con() as con:
        out = rows(con, q + " ORDER BY created_at", args)
    for a in out:
        a["params"] = json.loads(a["params"])
    return out


def get_action(aid):
    with _con() as con:
        r = rows(con, "SELECT * FROM pending_actions WHERE id=?", (aid,))
    if r:
        r[0]["params"] = json.loads(r[0]["params"])
    return r[0] if r else None


def approve(aid):
    """User said YES: execute against crewops.db and record in the change log."""
    a = get_action(aid)
    if not a:
        return {"error": "action not found"}
    if a["status"] != "pending":
        return {"error": f"action already {a['status']}"}
    X.ensure_backup()  # guarantee a pristine snapshot exists before first write
    fn, _label = REGISTRY[a["action"]]
    result = fn(**a["params"])
    if result.get("error"):
        _resolve(aid, "rejected")
        return {"action_id": aid, "status": "failed", "error": result["error"]}
    _resolve(aid, "approved")
    with _con() as con:
        con.execute("""INSERT INTO change_log (action_id,action,summary,changes,created_at)
                       VALUES (?,?,?,?,?)""",
                    (aid, a["action"], result["summary"],
                     json.dumps(result["changes"]), _now()))
    return {"action_id": aid, "status": "applied", "summary": result["summary"],
            "changes": result["changes"]}


def reject(aid):
    a = get_action(aid)
    if not a:
        return {"error": "action not found"}
    if a["status"] != "pending":
        return {"error": f"action already {a['status']}"}
    _resolve(aid, "rejected")
    return {"action_id": aid, "status": "rejected"}


def _resolve(aid, status):
    with _con() as con:
        con.execute("UPDATE pending_actions SET status=?, resolved_at=? WHERE id=?",
                    (status, _now(), aid))


def change_log():
    with _con() as con:
        out = rows(con, "SELECT * FROM change_log ORDER BY id")
    for c in out:
        c["changes"] = json.loads(c["changes"])
    return out


def revert():
    """Restore crewops.db from crewops_bkp.db, then clear the change log
    and any still-pending proposals (they referred to the mutated state)."""
    result = X.revert_to_backup()
    if result.get("error"):
        return result
    with _con() as con:
        n = con.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
        con.execute("DELETE FROM change_log")
        con.execute("UPDATE pending_actions SET status='rejected', resolved_at=? "
                    "WHERE status='pending'", (_now(),))
    return {"ok": True, "summary": result["summary"], "change_log_entries_cleared": n}
