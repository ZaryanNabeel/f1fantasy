"""Thin PyMySQL helper: one connection per request, parameterized queries only."""
import pymysql
from flask import current_app, g


def connect(cfg=None):
    cfg = cfg or current_app.config
    return pymysql.connect(
        host=cfg["DB_HOST"],
        port=cfg["DB_PORT"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        database=cfg["DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        autocommit=False,
    )


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        try:
            db.close()
        except pymysql.Error:
            pass


def query(sql, args=None, one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone() if one else cur.fetchall()


def execute(sql, args=None, commit=True):
    """Run a write; returns lastrowid. Pass commit=False inside a multi-statement transaction."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, args)
        rowid = cur.lastrowid
    if commit:
        db.commit()
    return rowid


def commit():
    get_db().commit()


def rollback():
    get_db().rollback()


def init_app(app):
    app.teardown_appcontext(close_db)
