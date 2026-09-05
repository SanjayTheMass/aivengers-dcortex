"""ETL: load data/*.json into a normalized SQLite database (crewops.db).

Run:  python etl/load.py
Idempotent: drops and recreates all tables each run.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = ROOT / "crewops.db"

SCHEMA = """
DROP TABLE IF EXISTS crew;
DROP TABLE IF EXISTS crew_ratings;
DROP TABLE IF EXISTS flights;
DROP TABLE IF EXISTS pairings;
DROP TABLE IF EXISTS pairing_days;
DROP TABLE IF EXISTS pairing_flights;
DROP TABLE IF EXISTS pairing_crew;
DROP TABLE IF EXISTS duty_clocks;
DROP TABLE IF EXISTS duty_history;
DROP TABLE IF EXISTS reserve_days;
DROP TABLE IF EXISTS certifications;
DROP TABLE IF EXISTS rules;
DROP TABLE IF EXISTS costs;
DROP TABLE IF EXISTS risk_signals;
DROP TABLE IF EXISTS flagged_exceptions;

CREATE TABLE flagged_exceptions (
    crew_id TEXT NOT NULL,
    date TEXT NOT NULL,
    rule TEXT NOT NULL,
    note TEXT,
    PRIMARY KEY (crew_id, date, rule)
);

CREATE TABLE crew (
    crew_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rank TEXT NOT NULL,
    base TEXT NOT NULL,
    seniority INTEGER,
    reachability_minutes INTEGER,
    status TEXT
);

CREATE TABLE crew_ratings (
    crew_id TEXT NOT NULL REFERENCES crew(crew_id),
    aircraft_type TEXT NOT NULL,
    PRIMARY KEY (crew_id, aircraft_type)
);

CREATE TABLE flights (
    flight_id TEXT PRIMARY KEY,
    flight_no TEXT NOT NULL,
    date TEXT NOT NULL,
    dep_station TEXT NOT NULL,
    arr_station TEXT NOT NULL,
    dep_utc TEXT NOT NULL,
    arr_utc TEXT NOT NULL,
    block_hours REAL NOT NULL,
    aircraft TEXT,
    aircraft_type TEXT,
    seats INTEGER
);

CREATE TABLE pairings (
    pairing_id TEXT PRIMARY KEY,
    aircraft TEXT
);

CREATE TABLE pairing_days (
    pairing_id TEXT NOT NULL REFERENCES pairings(pairing_id),
    date TEXT NOT NULL,
    report_utc TEXT NOT NULL,
    release_utc TEXT NOT NULL,
    PRIMARY KEY (pairing_id, date)
);

CREATE TABLE pairing_flights (
    pairing_id TEXT NOT NULL,
    date TEXT NOT NULL,
    flight_id TEXT NOT NULL REFERENCES flights(flight_id),
    seq INTEGER NOT NULL,
    PRIMARY KEY (pairing_id, date, flight_id)
);

CREATE TABLE pairing_crew (
    pairing_id TEXT NOT NULL REFERENCES pairings(pairing_id),
    crew_id TEXT NOT NULL REFERENCES crew(crew_id),
    role TEXT NOT NULL,
    PRIMARY KEY (pairing_id, crew_id)
);

CREATE TABLE duty_clocks (
    crew_id TEXT PRIMARY KEY REFERENCES crew(crew_id),
    as_of_utc TEXT,
    duty_hours_7d REAL,
    flight_hours_28d REAL,
    last_rest_ended TEXT
);

CREATE TABLE duty_history (
    crew_id TEXT NOT NULL REFERENCES crew(crew_id),
    date TEXT NOT NULL,
    duty_hours REAL NOT NULL,
    flight_hours REAL NOT NULL,
    PRIMARY KEY (crew_id, date)
);

CREATE TABLE reserve_days (
    crew_id TEXT NOT NULL REFERENCES crew(crew_id),
    base TEXT NOT NULL,
    date TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    PRIMARY KEY (crew_id, date)
);

CREATE TABLE certifications (
    crew_id TEXT NOT NULL REFERENCES crew(crew_id),
    cert_type TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    PRIMARY KEY (crew_id, cert_type)
);

CREATE TABLE rules (
    rule_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    params_json TEXT
);

CREATE TABLE costs (
    key TEXT PRIMARY KEY,
    value_inr REAL
);

CREATE TABLE risk_signals (
    crew_id TEXT PRIMARY KEY REFERENCES crew(crew_id),
    as_of_utc TEXT,
    disruption_risk_score REAL,
    drivers_json TEXT
);

CREATE INDEX idx_flights_dep ON flights(dep_station, date);
CREATE INDEX idx_flights_arr ON flights(arr_station, date);
CREATE INDEX idx_reserve_base_date ON reserve_days(base, date);
CREATE INDEX idx_pcrew_crew ON pairing_crew(crew_id);
CREATE INDEX idx_pdays_date ON pairing_days(date);
CREATE INDEX idx_certs_valid ON certifications(valid_to);
CREATE INDEX idx_dhist_date ON duty_history(crew_id, date);
"""


def load_json(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def main():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    # --- crew + ratings ---
    for c in load_json("crew.json"):
        con.execute(
            "INSERT INTO crew VALUES (?,?,?,?,?,?,?)",
            (c["crew_id"], c["name"], c["rank"], c["base"],
             c.get("seniority"), c.get("reachability_minutes"), c.get("status")),
        )
        for r in c.get("ratings", []):
            con.execute("INSERT INTO crew_ratings VALUES (?,?)", (c["crew_id"], r))

    # --- flights ---
    for f in load_json("flights.json"):
        con.execute(
            "INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f["flight_id"], f["flight_no"], f["date"], f["dep_station"],
             f["arr_station"], f["dep_utc"], f["arr_utc"], f["block_hours"],
             f.get("aircraft"), f.get("aircraft_type"), f.get("seats")),
        )

    # --- rosters (pairings + flagged exceptions) ---
    rosters = load_json("rosters.json")
    for x in rosters.get("flagged_exceptions", []):
        con.execute("INSERT INTO flagged_exceptions VALUES (?,?,?,?)",
                    (x["crew_id"], x["date"], x["rule"], x.get("note")))
    for p in rosters["pairings"]:
        con.execute("INSERT INTO pairings VALUES (?,?)",
                    (p["pairing_id"], p.get("aircraft")))
        for day in p.get("days", []):
            con.execute(
                "INSERT INTO pairing_days VALUES (?,?,?,?)",
                (p["pairing_id"], day["date"], day["report_utc"], day["release_utc"]),
            )
            for i, fid in enumerate(day.get("flights", [])):
                con.execute(
                    "INSERT INTO pairing_flights VALUES (?,?,?,?)",
                    (p["pairing_id"], day["date"], fid, i),
                )
        for m in p.get("crew", []):
            con.execute(
                "INSERT OR IGNORE INTO pairing_crew VALUES (?,?,?)",
                (p["pairing_id"], m["crew_id"], m["role"]),
            )

    # --- duty clocks + daily history ---
    for d in load_json("duty_clocks.json"):
        con.execute(
            "INSERT INTO duty_clocks VALUES (?,?,?,?,?)",
            (d["crew_id"], d.get("as_of_utc"), d.get("duty_hours_7d"),
             d.get("flight_hours_28d"), d.get("last_rest_ended")),
        )
        for h in d.get("daily_history", []):
            con.execute(
                "INSERT INTO duty_history VALUES (?,?,?,?)",
                (d["crew_id"], h["date"], h["duty_hours"], h["flight_hours"]),
            )

    # --- reserve pool (one row per date) ---
    for r in load_json("reserve_pool.json"):
        w = r["oncall_window_utc"]
        for date in r.get("dates", []):
            con.execute(
                "INSERT INTO reserve_days VALUES (?,?,?,?,?)",
                (r["crew_id"], r["base"], date, w["start"], w["end"]),
            )

    # --- certifications ---
    for c in load_json("certifications.json"):
        con.execute(
            "INSERT INTO certifications VALUES (?,?,?,?)",
            (c["crew_id"], c["cert_type"], c["valid_from"], c["valid_to"]),
        )

    # --- rules ---
    for r in load_json("rules.json")["rules"]:
        con.execute(
            "INSERT INTO rules VALUES (?,?,?)",
            (r["rule_id"], r["text"], json.dumps(r.get("params", {}))),
        )

    # --- costs (flatten scalar keys) ---
    for k, v in load_json("costs.json").items():
        if isinstance(v, (int, float)):
            con.execute("INSERT INTO costs VALUES (?,?)", (k, v))

    # --- risk signals ---
    for r in load_json("risk_signals.json"):
        con.execute(
            "INSERT INTO risk_signals VALUES (?,?,?,?)",
            (r["crew_id"], r.get("as_of_utc"), r.get("disruption_risk_score"),
             json.dumps(r.get("drivers", []))),
        )

    con.commit()

    # summary
    for t in ["crew", "crew_ratings", "flights", "pairings", "pairing_days",
              "pairing_flights", "pairing_crew", "duty_clocks", "duty_history",
              "reserve_days", "certifications", "rules", "costs", "risk_signals",
              "flagged_exceptions"]:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:18s} {n:6d} rows")
    con.close()
    print(f"\nDatabase written to {DB_PATH}")


if __name__ == "__main__":
    main()
