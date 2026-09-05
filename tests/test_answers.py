"""Replay questions.json (Tier 1 & 2) against the engine and compare with
the dataset's expected answers. Run: python tests\test_answers.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import lookups as L
from engine import simulate as S

DATA = Path(__file__).resolve().parents[1] / "data"
qs = {q["question_id"]: q for q in json.loads((DATA / "questions.json").read_text())}

results = []


def check(qid, got, ok, note=""):
    exp = qs[qid]["expected_answer"]
    results.append((qid, ok, note))
    mark = "PASS" if ok else "FAIL"
    print(f"{mark} {qid}: {qs[qid]['prompt'][:70]}")
    if not ok:
        print(f"   expected: {json.dumps(exp)[:300]}")
        print(f"   got:      {json.dumps(got, default=str)[:300]}")


# ---- Tier 1 ----
# Q01 reserves at BLR 2026-09-15
got = L.get_reserves("BLR", "2026-09-15")
exp = qs["Q01"]["expected_answer"]
ok = {(e["crew_id"], e["window"]["start"], e["window"]["end"]) for e in exp} == \
     {(g["crew_id"], g["window_start"], g["window_end"]) for g in got}
check("Q01", got, ok)

# Q02 duty hours + headroom for C-1042
got = L.get_duty_remaining("C-1042")
exp = qs["Q02"]["expected_answer"]
ok = abs(got["duty_hours_7d"] - exp["duty_hours_7d"]) < 0.05 and \
     abs(got["duty_headroom_7d"] - exp["headroom_hours"]) < 0.05
check("Q02", got, ok)

# Q03 departures DEL 2026-09-15 (expected uses flight numbers)
got = [f["flight_no"] for f in L.get_departures("DEL", "2026-09-15")]
exp = qs["Q03"]["expected_answer"]
check("Q03", got, set(got) == set(exp))

# Q04 certs expiring within 30 days of 2026-09-15
got = L.get_expiring_certs("2026-09-15", 30)
exp = qs["Q04"]["expected_answer"]
exp_set = {(e["crew_id"], e["cert_type"]) for e in exp}
got_set = {(g["crew_id"], g["cert_type"]) for g in got}
check("Q04", sorted(got_set), exp_set == got_set)

# Q05 aircraft + seats for DX412 on 2026-09-15
got = L.get_departures(date="2026-09-15", flight_no="DX412")
exp = qs["Q05"]["expected_answer"]
ok = got and got[0]["aircraft"] == exp["aircraft"] and got[0]["seats"] == exp["seats"]
check("Q05", got, bool(ok))

# Q08 crew of P-2291
got = L.get_pairing("P-2291")["crew"]
exp = qs["Q08"]["expected_answer"]
exp_set = {(e["crew_id"], e["role"]) for e in exp}
check("Q08", got, {(g["crew_id"], g["role"]) for g in got} == exp_set)

# Q10 flight count on 2026-09-16
got = len(L.get_departures(date="2026-09-16"))
check("Q10", got, got == qs["Q10"]["expected_answer"])

# Q16 risk score C-1042
got = L.get_crew_profile("C-1042")
exp = qs["Q16"]["expected_answer"]
check("Q16", got.get("disruption_risk_score"),
      abs(got.get("disruption_risk_score", -1) - exp["score"]) < 1e-6 and
      got.get("risk_drivers") == exp["drivers"])

# ---- Tier 2 ----
# Q17 C-1042 sick 15 Sep -> uncrewed flights
got = S.simulate_sick_call("C-1042", "2026-09-15")
exp = qs["Q17"]["expected_answer"]
ok = set(got["flights_by_day"].get("2026-09-15", [])) == set(exp["day1"]) and \
     set(got["flights_by_day"].get("2026-09-16", [])) == set(exp["day2_also_at_risk"])
check("Q17", got["flights_by_day"], ok)

# Q18 C-2087 covering P-2291 -> DUTY-02 breach detail
got = S.simulate_reassignment("C-2087", "P-2291", from_date="2026-09-15")
exp = qs["Q18"]["expected_answer"]
ok = got["legal"] == exp["legal"] and \
     any("60h/7d" in i and "1h20m" in i for i in got["issues"]) and \
     any("1h05m" in i for i in got["issues"])
check("Q18", got["issues"], ok)

# Q19 BLR closed 08:00-14:00 17 Sep
got = S.simulate_station_closure("BLR", "2026-09-17", "08:00", "14:00")
exp = set(qs["Q19"]["expected_answer"])
check("Q19", got["affected_flight_ids"], set(got["affected_flight_ids"]) == exp)

# Q20 VT-DXA delayed 90 min on 16 Sep -> FDP breach (12.75h vs 12.0h limit)
got = S.simulate_delay("VT-DXA", "2026-09-16", 90)
exp = qs["Q20"]["expected_answer"]
day = got["pairings"][0]["days"][0]
ok = (not day["fdp_check"]["legal"]) == exp["breach"] and \
     abs(day["delayed"]["duty_hours"] - exp["fdp_after_delay"]) < 0.02
check("Q20", day, ok)

# Q21 C-2210 (DEL) covering P-2291 with positioning -> legal, deadhead required
got = S.simulate_reassignment("C-2210", "P-2291", from_date="2026-09-15")
exp = qs["Q21"]["expected_answer"]
check("Q21", {"legal": got["legal"], "deadhead": got["deadhead_required"]},
      got["legal"] == exp["legal"] and got["deadhead_required"] is True)

# Q22 C-5417 rostered VT-DXB duty 19 Sep (cert lapse)
prs = L.get_pairings_for_crew("C-5417", "2026-09-19")
got = S.simulate_reassignment("C-5417", prs[0]["pairing_id"], from_date="2026-09-19") if prs else {}
exp = qs["Q22"]["expected_answer"]
ok = got and got["legal"] is False and any("RULE-CERT-06" in i for i in got["issues"])
check("Q22", got.get("issues"), ok)

# Q23 earliest next report after 15:30Z release 16 Sep
got = S.earliest_next_report("2026-09-16T15:30:00Z")
check("Q23", got, got["earliest_next_report_utc"] == qs["Q23"]["expected_answer"])

# Q24 reserve C-3305 full P-2291
got = S.simulate_reassignment("C-3305", "P-2291", from_date="2026-09-15",
                              is_reserve_callout=True)
exp = qs["Q24"]["expected_answer"]
ok = got["legal"] == exp["legal"] and any("8h15m" in i for i in got["issues"])
check("Q24", got["issues"], ok)

# Q25 DX404 16 Sep cancellation
got = S.simulate_cancellation("DX404-2026-09-16")
exp = qs["Q25"]["expected_answer"]
check("Q25", got, got["passengers"] == exp["passengers"] and
      got["cancellation_cost_inr"] == exp["cost_inr"])

# Q26 crew with >=45h duty in 7d ending 2026-09-15
got = S.get_duty_totals("2026-09-15", 7, 45.0)
exp = qs["Q26"]["expected_answer"]
exp_map = {e["crew_id"]: e["duty_hours_7d_incl_15sep_plan"] for e in exp}
got_map = {g["crew_id"]: g["duty_hours"] for g in got}
ok = set(got_map) == set(exp_map) and \
     all(abs(got_map[k] - v) < 0.05 for k, v in exp_map.items())
check("Q26", got_map, ok)

# Q27 reserve captains whose window covers the required report (03:00Z) 16 Sep, ATR72-qualified
got = L.get_reserves("BLR", "2026-09-16", callout_utc_time="03:00", rank="Captain")
exp = qs["Q27"]["expected_answer"]
eligible = [g["crew_id"] for g in got if "ATR72" in g["ratings"]]
check("Q27", eligible, set(eligible) == set(exp["eligible"]))

# Q29 HYD closed 05:00-09:00 19 Sep
got = S.simulate_station_closure("HYD", "2026-09-19", "05:00", "09:00")
exp = qs["Q29"]["expected_answer"]
exp_ids = set(exp if isinstance(exp[0], str) else [e["flight_id"] for e in exp])
check("Q29", got["affected_flight_ids"], set(got["affected_flight_ids"]) == exp_ids)

# ---- summary ----
fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
sys.exit(1 if fails else 0)
