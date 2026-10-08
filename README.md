# F1 Fantasy League

Flask + MySQL fantasy F1 game, built for CSC413 DevOps Assignment 1 (Zaryan Nabeel, FA23-BDS-039).
Pick 5 drivers + 1 constructor within a 100.0M budget (max 2 drivers per real team); score their real
2026 points (Grand Prix + sprints). Data: [Jolpica-F1](https://api.jolpi.ca/ergast/f1/).

Deployment to EC2 (IaaS) and Elastic Beanstalk + RDS (PaaS): see [DEPLOYMENT.md](DEPLOYMENT.md).

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env            # then edit DB_PASSWORD, SECRET_KEY

# Load the database (as MySQL root). Edit passwords in a copy of create_users.sql first.
cmd /c "mysql -u root -p < sql\schema.sql"
cmd /c "mysql -u root -p < sql\seed_2026.sql"
cmd /c "mysql -u root -p < sql\create_users.local.sql"

.venv\Scripts\flask --app application create-admin
.venv\Scripts\flask --app application seed-demo
.venv\Scripts\flask --app application run
```

## CLI commands

| Command | Purpose |
|---|---|
| `flask create-admin` | Create an admin account (the only way to get one) |
| `flask sync-data --season 2026 [--use-cache]` | Import calendar, drivers, teams and results from Jolpica (idempotent) |
| `flask export-seed --season 2026` | Write `sql/seed_2026.sql` from the current DB |
| `flask seed-demo` | Create 5 demo users with valid teams; passwords printed once |

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```
Pure rule tests always run. DB tests build a throwaway `f1fantasy_test` database and need
`TEST_DB_USER` / `TEST_DB_PASSWORD` (an account allowed to create databases) in `.env`;
they are skipped if MySQL is unreachable.

## Layout

- `app/auth` — accounts, validation, `login_required` / `admin_required`
- `app/f1data` — public F1 pages, admin CRUD, `jolpica.py` importer
- `app/fantasy` — fantasy rules and scoring (`validate_picks`, `team_total`, `race_breakdown` are pure functions)
- `sql/` — `schema.sql` (source of truth, incl. views `v_driver_points`, `v_constructor_points`, `v_leaderboard`), seed, DB accounts
- `deploy/` — EC2 setup script, systemd unit, nginx site, Beanstalk bundle builder
