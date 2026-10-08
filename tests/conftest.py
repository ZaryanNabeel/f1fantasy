"""Fixtures. DB tests run against a throwaway `f1fantasy_test` database built from sql/schema.sql.

Needs an account that may CREATE/DROP databases: TEST_DB_USER / TEST_DB_PASSWORD (default root / empty).
If MySQL is unreachable, DB tests are skipped and the pure-function tests still run.
"""
import os
from pathlib import Path

import pymysql
import pytest

from app import create_app  # importing app loads .env first

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = "f1fantasy_test"
DB_CFG = {
    "DB_HOST": os.environ.get("DB_HOST", "127.0.0.1"),
    "DB_PORT": int(os.environ.get("DB_PORT", "3306")),
    "DB_USER": os.environ.get("TEST_DB_USER", "root"),
    "DB_PASSWORD": os.environ.get("TEST_DB_PASSWORD", ""),
    "DB_NAME": TEST_DB,
}

# 6 active teams (+1 inactive); 12 active drivers, 2 per team (+1 inactive)
TEAMS = [(1, "red_bull", "Red Bull", 20.0, 1), (2, "mclaren", "McLaren", 18.0, 1), (3, "ferrari", "Ferrari", 16.0, 1),
         (4, "mercedes", "Mercedes", 14.0, 1), (5, "williams", "Williams", 10.0, 1), (6, "haas", "Haas", 8.0, 1),
         (7, "old_team", "Old Team", 5.0, 0)]
DRIVER_PRICES = [30.0, 28.0, 25.0, 22.0, 20.0, 18.0, 15.0, 12.0, 10.0, 8.0, 6.0, 5.0]


def _load_schema(cur):
    sql = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8").replace("f1fantasy", TEST_DB)
    sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    for stmt in sql.split(";"):
        if stmt.strip():
            cur.execute(stmt)


@pytest.fixture(scope="session")
def database():
    try:
        conn = pymysql.connect(host=DB_CFG["DB_HOST"], port=DB_CFG["DB_PORT"], user=DB_CFG["DB_USER"],
                               password=DB_CFG["DB_PASSWORD"], connect_timeout=3, autocommit=True)
    except pymysql.Error as exc:
        pytest.skip(f"MySQL not available for tests: {exc}")
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        _load_schema(cur)
        cur.executemany("INSERT INTO teams (id, constructor_ref, name, price, active) VALUES (%s,%s,%s,%s,%s)", TEAMS)
        drivers = [(i, f"driver_{i}", f"D{chr(64 + i)}X", i, "Test", f"Driver{i}", (i + 1) // 2, p, 1)
                   for i, p in enumerate(DRIVER_PRICES, 1)]
        drivers.append((13, "retired", "RET", None, "Old", "Timer", 1, 5.0, 0))
        cur.executemany("INSERT INTO drivers (id, driver_ref, code, permanent_number, first_name, last_name, "
                        "team_id, price, active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", drivers)
        cur.execute("INSERT INTO races (id, season, round, name, circuit, race_date, has_sprint) "
                    "VALUES (1, 2026, 1, 'Test GP', 'Test Ring', '2026-03-08', 1)")
        cur.executemany(
            "INSERT INTO race_results (race_id, driver_id, team_id, session_type, position, points) "
            "VALUES (1,%s,%s,%s,%s,%s)",
            [(1, 1, "race", 1, 25), (3, 2, "race", 2, 18), (11, 6, "race", 3, 15), (1, 1, "sprint", 1, 8)])
    conn.close()
    return DB_CFG


@pytest.fixture
def app(database):
    app = create_app({**database, "TESTING": True, "WTF_CSRF_ENABLED": False,
                      "SECRET_KEY": "test", "F1_SEASON": 2026})
    yield app
    with app.app_context():
        from app import db

        db.execute("DELETE FROM users")  # cascades to fantasy teams and picks


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="alice_1", password="password1", email=None):
    return client.post("/register", data={"username": username, "email": email or f"{username}@example.com",
                                          "password": password, "confirm": password})
