"""Replay scenarios.json Tier-3 answer keys against recommend_cover.
Run: python tests\test_scenarios.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.recommend import recommend_cover

DATA = Path(__file__).resolve().parents[1] / "data"
scenarios = {s["scenario_id"]: s for s in json.loads((DATA / "scenarios.json").read_text())}
fails = []


def check(sid, ok, note):
    print(("PASS" if ok else "FAIL"), sid, note)
    if not ok:
        fails.append(sid)


def legal_map(options):
    return {o["crew_id"]: o for o in options if o.get("crew_id")}


for sid, from_date in [("S1", "2026-09-16"), ("S2", "2026-09-15")]:
    s = scenarios[sid]
    got = recommend_cover(s["event"]["crew_id"], from_date,
                          callout_utc=s["event"]["reported_utc"],
                          pairing_id=s["event"].get("pairing_id"))
    key = s["answer_key"]
    exp_opts = legal_map(key["options"])
    got_opts = legal_map(got["options"])

    # uncovered flights
    exp_flights = set(key.get("uncovered_flights", []) or
                      key.get("uncovered_flights_day1", []) + key.get("uncovered_flights_day2", []))
    check(sid, set(got["uncovered_flights"]) == exp_flights, "uncovered flights")

    # every keyed crew option matches cost + legality; rank-1 crew matches
    same = all(c in got_opts and got_opts[c]["cost_inr"] == o["cost_inr"] and
               got_opts[c]["legal"] == o["legal"] and
               abs(got_opts[c]["delay_hours"] - o["delay_hours"]) < 0.01
               for c, o in exp_opts.items())
    check(sid, same, f"option costs/legality for {sorted(exp_opts)}")
    exp_rank1 = key["options"][0]["crew_id"]
    check(sid, got["options"][0]["crew_id"] == exp_rank1, f"rank 1 = {exp_rank1}")

    # cancellation cost
    exp_cancel = [o for o in key["options"] if o["crew_id"] is None]
    if exp_cancel:
        got_cancel = [o for o in got["options"] if o["crew_id"] is None][0]
        check(sid, got_cancel["cost_inr"] == exp_cancel[0]["cost_inr"], "cancellation cost")

    # excluded candidates flagged for the right rule
    exp_excl = {e["crew_id"]: e["reason"] for e in key.get("excluded_candidates", [])}
    got_excl = {e["crew_id"]: e["reason"] for e in got["excluded_candidates"]}
    ok = all(c in got_excl and (r.split(":")[0] in got_excl[c] or
                                "window" in r and "window" in got_excl[c])
             for c, r in exp_excl.items())
    check(sid, ok, f"exclusions {sorted(exp_excl)}")

print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(fails)}")
sys.exit(1 if fails else 0)
