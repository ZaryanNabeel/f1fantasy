from flask import Blueprint, current_app, render_template

from . import db
from .fantasy.services import leaderboard

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    season = current_app.config["F1_SEASON"]
    next_race = db.query(
        "SELECT * FROM races WHERE season = %s AND race_date >= CURDATE() ORDER BY race_date LIMIT 1",
        (season,), one=True)
    latest = db.query(
        """SELECT r.* FROM races r WHERE r.season = %s
           AND EXISTS (SELECT 1 FROM race_results rr WHERE rr.race_id = r.id AND rr.session_type = 'race')
           ORDER BY r.round DESC LIMIT 1""", (season,), one=True)
    podium = []
    if latest:
        podium = db.query(
            """SELECT rr.position, rr.points, d.id AS driver_id, d.first_name, d.last_name, t.name AS team_name
               FROM race_results rr JOIN drivers d ON d.id = rr.driver_id JOIN teams t ON t.id = rr.team_id
               WHERE rr.race_id = %s AND rr.session_type = 'race' AND rr.position BETWEEN 1 AND 3
               ORDER BY rr.position""", (latest["id"],))
    return render_template("index.html", top=leaderboard(season, limit=10), next_race=next_race,
                           latest=latest, podium=podium)
