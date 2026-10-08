"""Jolpica-F1 (Ergast-compatible) importer.

Parsing is pure (plain JSON in, plain dicts out); `sync_season` does the upserts.
Never called on page requests except the admin "Sync from API" POST.
"""
import json
import math
import time
from pathlib import Path

import requests

from .. import db

BASE_URL = "https://api.jolpi.ca/ergast/f1/"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
PAGE = 100  # Jolpica's max page size


# ---------------------------------------------------------------- fetching

def fetch_json(path, params=None, use_cache=False):
    """GET BASE_URL+path. Raw responses are always written to data/cache/; read back only if use_cache."""
    key = path.replace("/", "_") + "".join(f"_{k}{v}" for k, v in sorted((params or {}).items()))
    cache_file = CACHE_DIR / key
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    time.sleep(0.3)  # be polite to the free API
    resp = requests.get(BASE_URL + path, params=params, timeout=30,
                        headers={"User-Agent": "f1fantasy-coursework/1.0"})
    resp.raise_for_status()
    data = resp.json()
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # read-only filesystem in production is fine
    return data


def fetch_races_paginated(path, list_key, fetch):
    """Follow limit/offset until offset >= total, merging races split across pages."""
    by_round, offset = {}, 0
    while True:
        mr = fetch(path, {"limit": PAGE, "offset": offset})["MRData"]
        for race in mr["RaceTable"]["Races"]:
            merged = by_round.setdefault(race["round"], {**race, list_key: []})
            merged[list_key].extend(race.get(list_key, []))
        offset += PAGE
        if offset >= int(mr["total"]):
            return list(by_round.values())


# ---------------------------------------------------------------- pure parsing

def round_half(x):
    return math.floor(x * 2 + 0.5) / 2


def driver_price(rank):
    return 4.5 if rank is None else round_half(max(4.5, 30.0 - (rank - 1) * 1.3))


def constructor_price(rank):
    return 5.0 if rank is None else round_half(max(5.0, 25.0 - (rank - 1) * 2.0))


def parse_calendar(races):
    return [
        {
            "round": int(r["round"]),
            "name": r["raceName"],
            "circuit": r["Circuit"]["circuitName"],
            "country": r["Circuit"].get("Location", {}).get("country"),
            "race_date": r["date"],
            "has_sprint": 1 if "Sprint" in r else 0,
        }
        for r in races
    ]


def _int_or_none(v):
    return int(v) if v not in (None, "") and str(v).isdigit() else None


def parse_results(races, list_key, session_type):
    """Flatten Races[].<list_key>[] into result rows keyed by refs."""
    rows = []
    for race in races:
        for res in race.get(list_key, []):
            rows.append({
                "round": int(race["round"]),
                "session_type": session_type,
                "driver_ref": res["Driver"]["driverId"],
                "constructor_ref": res["Constructor"]["constructorId"],
                # positionText is "R", "D", "W"... when not classified
                "position": _int_or_none(res.get("positionText")),
                "grid": _int_or_none(res.get("grid")),
                "points": res.get("points", "0"),
                "status": (res.get("status") or "")[:50] or None,
            })
    return rows


def latest_constructor(result_rows):
    """driver_ref -> constructor_ref from their most recent session (sprint precedes the GP in a round)."""
    order = {"sprint": 0, "race": 1}
    latest = {}
    for row in sorted(result_rows, key=lambda r: (r["round"], order[r["session_type"]])):
        latest[row["driver_ref"]] = row["constructor_ref"]
    return latest


def standings_ranks(data, list_key, entity_key, id_key):
    lists = data["MRData"]["StandingsTable"]["StandingsLists"]
    if not lists:
        return {}
    return {
        s[entity_key][id_key]: int(s["position"])
        for s in lists[0][list_key]
        if str(s.get("position", "")).isdigit()
    }


def fallback_code(family_name):
    letters = "".join(c for c in family_name.upper() if "A" <= c <= "Z")
    return (letters + "XXX")[:3]


# ---------------------------------------------------------------- sync

def sync_season(season, use_cache=False, fetch=None):
    """Idempotent upsert of teams, drivers, races and results. Returns (stats dict, summary str)."""
    fetch = fetch or (lambda path, params=None: fetch_json(path, params, use_cache))

    calendar = parse_calendar(fetch(f"{season}.json")["MRData"]["RaceTable"]["Races"])
    api_drivers = fetch(f"{season}/drivers.json", {"limit": PAGE})["MRData"]["DriverTable"]["Drivers"]
    api_teams = fetch(f"{season}/constructors.json", {"limit": PAGE})["MRData"]["ConstructorTable"]["Constructors"]
    results = parse_results(fetch_races_paginated(f"{season}/results.json", "Results", fetch), "Results", "race")
    results += parse_results(fetch_races_paginated(f"{season}/sprint.json", "SprintResults", fetch),
                             "SprintResults", "sprint")
    d_rank = standings_ranks(fetch(f"{season}/driverStandings.json"), "DriverStandings", "Driver", "driverId")
    c_rank = standings_ranks(fetch(f"{season}/constructorStandings.json"),
                             "ConstructorStandings", "Constructor", "constructorId")

    current_team = latest_constructor(results)
    missing = [d["driverId"] for d in api_drivers if d["driverId"] not in current_team]
    fallback_team = {}
    if missing:  # drivers with no results still need a team_id: ask each constructor for its roster
        for t in api_teams:
            roster = fetch(f"{season}/constructors/{t['constructorId']}/drivers.json")
            for d in roster["MRData"]["DriverTable"]["Drivers"]:
                fallback_team.setdefault(d["driverId"], t["constructorId"])

    stats = dict.fromkeys(
        ["teams_inserted", "drivers_inserted", "races_inserted", "races_updated",
         "results_inserted", "results_updated", "drivers_skipped"], 0)
    conn = db.get_db()
    try:
        with conn.cursor() as cur:
            for t in api_teams:
                n = cur.execute(
                    """INSERT INTO teams (constructor_ref, name, nationality, price)
                       VALUES (%s, %s, %s, %s) AS new
                       ON DUPLICATE KEY UPDATE name = new.name, nationality = new.nationality""",
                    (t["constructorId"], t["name"], t.get("nationality"),
                     constructor_price(c_rank.get(t["constructorId"]))),
                )
                stats["teams_inserted"] += n == 1
            cur.execute("SELECT id, constructor_ref FROM teams")
            team_ids = {r["constructor_ref"]: r["id"] for r in cur.fetchall()}

            for d in api_drivers:
                ref = d["driverId"]
                cref = current_team.get(ref) or fallback_team.get(ref)
                if cref not in team_ids:
                    stats["drivers_skipped"] += 1
                    continue
                # price and active are set on first insert only: admin edits survive re-syncs
                n = cur.execute(
                    """INSERT INTO drivers (driver_ref, code, permanent_number, first_name, last_name,
                                            nationality, team_id, price, active)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) AS new
                       ON DUPLICATE KEY UPDATE code = new.code, permanent_number = new.permanent_number,
                         first_name = new.first_name, last_name = new.last_name,
                         nationality = new.nationality, team_id = new.team_id""",
                    (ref, d.get("code") or fallback_code(d["familyName"]),
                     _int_or_none(d.get("permanentNumber")), d["givenName"], d["familyName"],
                     d.get("nationality"), team_ids[cref], driver_price(d_rank.get(ref)),
                     1 if ref in current_team else 0),
                )
                stats["drivers_inserted"] += n == 1
            cur.execute("SELECT id, driver_ref FROM drivers")
            driver_ids = {r["driver_ref"]: r["id"] for r in cur.fetchall()}

            for r in calendar:
                n = cur.execute(
                    """INSERT INTO races (season, round, name, circuit, country, race_date, has_sprint)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) AS new
                       ON DUPLICATE KEY UPDATE name = new.name, circuit = new.circuit, country = new.country,
                         race_date = new.race_date, has_sprint = new.has_sprint""",
                    (season, r["round"], r["name"], r["circuit"], r["country"], r["race_date"], r["has_sprint"]),
                )
                stats["races_inserted"] += n == 1
                stats["races_updated"] += n == 2
            cur.execute("SELECT id, round FROM races WHERE season = %s", (season,))
            race_ids = {r["round"]: r["id"] for r in cur.fetchall()}

            for res in results:
                if res["driver_ref"] not in driver_ids or res["constructor_ref"] not in team_ids:
                    continue
                n = cur.execute(
                    """INSERT INTO race_results (race_id, driver_id, team_id, session_type,
                                                 position, grid, points, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) AS new
                       ON DUPLICATE KEY UPDATE team_id = new.team_id, position = new.position,
                         grid = new.grid, points = new.points, status = new.status""",
                    (race_ids[res["round"]], driver_ids[res["driver_ref"]], team_ids[res["constructor_ref"]],
                     res["session_type"], res["position"], res["grid"], res["points"], res["status"]),
                )
                stats["results_inserted"] += n == 1
                stats["results_updated"] += n == 2

            summary = (
                f"{stats['races_inserted']} races inserted, {stats['races_updated']} races updated, "
                f"{stats['results_inserted']} results inserted, {stats['results_updated']} results updated, "
                f"{stats['drivers_inserted']} new drivers, {stats['teams_inserted']} new teams"
            )
            cur.execute("INSERT INTO sync_log (season, summary) VALUES (%s, %s)", (season, summary[:255]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return stats, summary
