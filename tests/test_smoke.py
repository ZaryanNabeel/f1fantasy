from decimal import Decimal

from app import create_app
from app.auth.services import is_safe_next, validate_registration
from app.f1data.jolpica import (constructor_price, driver_price, fetch_races_paginated, latest_constructor,
                                parse_results)
from app.f1data.services import parse_price
from app.fantasy.services import race_breakdown, validate_picks

from .conftest import register

# ---------------------------------------------------------------- pure functions (no DB)

DRIVERS = {i: {"price": Decimal(p), "team_id": (i + 1) // 2, "active": 1}
           for i, p in enumerate(["30", "28", "25", "22", "20", "18", "15", "12", "10", "8"], 1)}
DRIVERS[11] = {"price": Decimal("5"), "team_id": 1, "active": 0}
TEAMS = {1: {"name": "Red Bull", "price": Decimal("20"), "active": 1},
         5: {"name": "Haas", "price": Decimal("8"), "active": 1},
         9: {"name": "Gone", "price": Decimal("5"), "active": 0}}


def test_valid_fantasy_team():
    assert validate_picks("Speed Demons", [3, 6, 8, 9, 10], 5, DRIVERS, TEAMS) == []


def test_fantasy_rules_rejected():
    assert any("exactly 5" in e for e in validate_picks("Team", [7, 8, 9, 10], 5, DRIVERS, TEAMS))
    assert any("Budget" in e for e in validate_picks("Team", [1, 3, 5, 7, 9], 1, DRIVERS, TEAMS))
    assert any("Max 2" in e for e in validate_picks("Team", [1, 2, 11, 9, 10], 5, {**DRIVERS, 11: {
        "price": Decimal("4"), "team_id": 1, "active": 1}}, TEAMS))
    assert any("active constructor" in e for e in validate_picks("Team", [3, 6, 8, 9, 10], 9, DRIVERS, TEAMS))
    assert any("active drivers" in e for e in validate_picks("Team", [11, 6, 8, 9, 10], 5, DRIVERS, TEAMS))
    assert any("3-40" in e for e in validate_picks("ab", [3, 6, 8, 9, 10], 5, DRIVERS, TEAMS))
    assert any("once" in e for e in validate_picks("Team", [3, 3, 8, 9, 10], 5, DRIVERS, TEAMS))


def test_registration_rules():
    assert validate_registration("good_name", "a@b.co", "secret123", "secret123") == {}
    errs = validate_registration("x!", "not-an-email", "short", "short")
    assert set(errs) == {"username", "email", "password"}
    assert "password" in validate_registration("good_name", "a@b.co", "lettersonly", "lettersonly")
    assert "confirm" in validate_registration("good_name", "a@b.co", "secret123", "secret124")


def test_safe_next():
    assert is_safe_next("/my-team")
    for bad in ("https://evil.com", "//evil.com", "/\\evil.com", "", "javascript:alert(1)"):
        assert not is_safe_next(bad)


def test_prices():
    assert driver_price(1) == 30.0 and driver_price(2) == 28.5 and driver_price(30) == 4.5
    assert driver_price(None) == 4.5
    assert constructor_price(1) == 25.0 and constructor_price(11) == 5.0 and constructor_price(None) == 5.0
    assert parse_price("12.5") == Decimal("12.5")
    assert parse_price("12.3") is None and parse_price("3.5") is None and parse_price("35.5") is None


def test_parse_results_and_current_team():
    races = [{"round": "1", "Results": [
        {"positionText": "1", "grid": "2", "points": "25", "status": "Finished",
         "Driver": {"driverId": "a"}, "Constructor": {"constructorId": "x"}},
        {"positionText": "R", "grid": "5", "points": "0", "status": "Retired",
         "Driver": {"driverId": "b"}, "Constructor": {"constructorId": "y"}}]},
             {"round": "2", "Results": [
        {"positionText": "3", "grid": "1", "points": "15", "status": "Finished",
         "Driver": {"driverId": "a"}, "Constructor": {"constructorId": "z"}}]}]
    rows = parse_results(races, "Results", "race")
    assert rows[1]["position"] is None and rows[0]["position"] == 1
    assert latest_constructor(rows) == {"a": "z", "b": "y"}


def test_pagination_merges_races_split_across_pages():
    # 150 results over 2 pages; round 2 is split between them
    pages = {0: [{"round": "1", "Results": [1] * 80}, {"round": "2", "Results": [2] * 20}],
             100: [{"round": "2", "Results": [2] * 30}, {"round": "3", "Results": [3] * 20}]}
    calls = []

    def fake_fetch(path, params):
        calls.append(params["offset"])
        return {"MRData": {"total": "150", "RaceTable": {"Races": pages[params["offset"]]}}}

    races = fetch_races_paginated("2026/results.json", "Results", fake_fetch)
    assert calls == [0, 100]
    assert [len(r["Results"]) for r in races] == [80, 50, 20]


def test_race_breakdown_credits_constructor_by_result_team():
    rows = [{"race_id": 1, "round": 1, "race_name": "A", "driver_id": 1, "team_id": 1, "points": 25},
            {"race_id": 1, "round": 1, "race_name": "A", "driver_id": 2, "team_id": 2, "points": 18},
            {"race_id": 2, "round": 2, "race_name": "B", "driver_id": 2, "team_id": 1, "points": 10}]
    out = race_breakdown(rows, [1], 1)
    assert [(e["drivers"], e["constructor"], e["total"]) for e in out] == [(25, 25, 50), (0, 10, 10)]


def test_health_returns_503_when_db_down():
    app = create_app({"TESTING": True, "DB_HOST": "127.0.0.1", "DB_PORT": 1})
    resp = app.test_client().get("/health")
    assert resp.status_code == 503 and resp.get_json()["db"] == "down"


# ---------------------------------------------------------------- with test database

def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200 and resp.get_json() == {"status": "ok", "db": "ok"}


def test_public_pages(client):
    for url in ("/", "/drivers", "/drivers/1", "/teams", "/teams/1", "/races", "/races/1", "/leaderboard"):
        assert client.get(url).status_code == 200, url
    assert client.get("/drivers/999").status_code == 404


def test_register_login_logout(client):
    assert register(client).status_code == 302
    client.post("/logout")  # registering logs in; /register redirects logged-in users
    assert register(client, username="ALICE_1", email="other@example.com").status_code == 400  # case-insensitive
    bad = client.post("/login", data={"username": "alice_1", "password": "wrong-pass1"})
    assert bad.status_code == 401 and b"Invalid username or password." in bad.data
    resp = client.post("/login", data={"username": "alice_1", "password": "password1", "next": "/profile"})
    assert resp.headers["Location"] == "/profile"


def test_login_required_and_admin_guard(client):
    resp = client.get("/my-team")
    assert resp.status_code == 302 and "/login?next=/my-team" in resp.headers["Location"]
    register(client)
    assert client.get("/admin").status_code == 403


def test_create_fantasy_team_and_leaderboard(client):
    register(client)
    # drivers 1 (RB, 30), 3 (McL, 25), 9 (Wil, 10), 11 (Haas, 6), 12 (Haas, 5) + Haas (8) = 84.0
    resp = client.post("/my-team/edit", data={"name": "Fast Lane", "drivers": ["1", "3", "9", "11", "12"],
                                              "constructor_id": "6"})
    assert resp.status_code == 302
    board = client.get("/leaderboard").data.decode()
    # drivers 33 (25 GP + 8 sprint) + 18 + 0 + 15 + 0, constructor Haas 15 -> 81
    assert "Fast Lane" in board and ">81<" in board
    # edit: invalid budget keeps selections and shows the rule
    resp = client.post("/my-team/edit", data={"name": "Fast Lane", "drivers": ["1", "2", "3", "4", "5"],
                                              "constructor_id": "1"})
    assert resp.status_code == 400 and b"Budget exceeded" in resp.data and b'value="5" data-price' in resp.data


def test_team_name_unique_per_season(client):
    register(client, "bob_1")
    client.post("/my-team/edit", data={"name": "Same Name", "drivers": ["1", "3", "9", "11", "12"],
                                       "constructor_id": "6"})
    client.post("/logout")
    register(client, "carol_1")
    resp = client.post("/my-team/edit", data={"name": "same name", "drivers": ["1", "3", "9", "11", "12"],
                                              "constructor_id": "6"})
    assert resp.status_code == 400 and b"already taken" in resp.data
