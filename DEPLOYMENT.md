# Deployment Manual — F1 Fantasy League

**Zaryan Nabeel · FA23-BDS-039 · CSC413 DevOps for Cloud Computing — Assignment 1**

This manual deploys the same codebase twice:

- **Part I (IaaS):** EC2 (Ubuntu) running MySQL, nginx, gunicorn and Flask, managed by systemd.
- **Part II (PaaS):** a code bundle in S3, deployed with Elastic Beanstalk, with the database on Amazon RDS for MySQL.

The only differences between the two deployments come from environment variables (see `.env.example`).

Before you start, check that:
- the code is pushed to GitHub, including `sql/seed_2026.sql`;
- the MySQL 8 client (`mysql`) is installed on your laptop; and
- you are signed in to the AWS Console in one region (for example `us-east-1`). Use the same region for everything.

Use letters and digits only (12+ characters) for every password below, so that no shell or SQL escaping is needed. Write the passwords down: the report and the grader need them.

| Account | Used by | Privileges |
|---|---|---|
| `f1app` | the application | SELECT, INSERT, UPDATE, DELETE on `f1fantasy.*` |
| `grader` | the evaluation script | SELECT on `f1fantasy.*` only |

---

## Part I — EC2 (IaaS)

### I-1. Launch the instance

1. Open **EC2 → Instances → Launch instances**.
2. **Name:** `f1fantasy-ec2`.
3. **AMI:** *Ubuntu Server 24.04 LTS (HVM), SSD Volume Type*, 64-bit (x86).
4. **Instance type:** `t3.micro`.
5. **Key pair:** click **Create new key pair**. Name it `f1fantasy-key`, choose RSA and `.pem`, and save the file somewhere safe.
6. **Network settings → Edit → Create security group** named `f1fantasy-ec2-sg`, with these inbound rules:

   | Type | Port | Source | Why |
   |---|---|---|---|
   | SSH | 22 | 0.0.0.0/0 | administration |
   | HTTP | 80 | 0.0.0.0/0 | the website |
   | MySQL/Aurora | 3306 | 0.0.0.0/0 | **the grader connects to MySQL remotely** |

7. **Storage:** 8–10 GiB gp3 (the default is fine).
8. Click **Launch instance**.

📸 Screenshot: the launch summary showing the Ubuntu AMI, t3.micro and the key pair.
📸 Screenshot: the security group inbound rules (22, 80, 3306).

### I-2. Allocate an Elastic IP

A plain public IP changes every time the instance stops and starts. An Elastic IP keeps the grading URL stable.

1. Open **EC2 → Elastic IPs → Allocate Elastic IP address → Allocate**.
2. Select the new address, then choose **Actions → Associate Elastic IP address**.
3. Choose the instance `f1fantasy-ec2` and click **Associate**.
4. Note the address. This manual calls it `<EIP>`.

📸 Screenshot: the Elastic IP list showing the address associated with `f1fantasy-ec2`.

### I-3. Connect to the instance

**Option A — SSH from your laptop** (in PowerShell):
```powershell
ssh -i C:\path\to\f1fantasy-key.pem ubuntu@<EIP>
```
If Windows complains that the key is too open, run this, then try again:
```powershell
icacls C:\path\to\f1fantasy-key.pem /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

**Option B — EC2 Instance Connect** (use this if your network blocks port 22): select the instance and choose **Connect → EC2 Instance Connect → Connect**.

📸 Screenshot: the terminal showing the `ubuntu@ip-...` prompt.

### I-4. Run the setup script

```bash
curl -fsSL https://raw.githubusercontent.com/ZaryanNabeel/f1fantasy/main/deploy/ec2_setup.sh -o ec2_setup.sh
bash ec2_setup.sh   # clones https://github.com/ZaryanNabeel/f1fantasy.git (set REPO_URL=... to use a fork)
```
The script prompts for the `f1app` and `grader` passwords. It then:

1. installs `python3-venv`, `nginx`, `mysql-server` and `git` with apt;
2. sets `bind-address = 0.0.0.0` in `/etc/mysql/mysql.conf.d/mysqld.cnf` and restarts MySQL;
3. clones the repository into `/home/ubuntu/f1fantasy`;
4. loads `schema.sql`, then `seed_2026.sql`, then `create_users.sql` (with your passwords substituted in);
5. creates the virtualenv `.venv` and installs `requirements.txt`;
6. writes `/etc/f1fantasy.env` with mode 600 and a randomly generated `SECRET_KEY`; and
7. installs and starts the `f1fantasy` systemd service and the nginx site.

The script is idempotent: you can safely re-run it, for example after a `git push` to deploy new code.

📸 Screenshot: the end of the script output, showing `{"db":"ok","status":"ok"}`.

### I-5. Check permissions and services

```bash
ls -ld /home/ubuntu/f1fantasy          # owner: ubuntu
ls -l  /etc/f1fantasy.env              # -rw------- ubuntu ubuntu
sudo mysql -e "SELECT user, host, plugin FROM mysql.user WHERE user IN ('root','f1app','grader');"
#   root   localhost  auth_socket            <- root keeps socket auth (no password, local only)
#   f1app  %          caching_sha2_password
#   grader %          caching_sha2_password
sudo ss -ltnp | grep -E ':80|:3306|:8000'
#   0.0.0.0:3306 (mysqld), 0.0.0.0:80 (nginx), 127.0.0.1:8000 (gunicorn)
systemctl status f1fantasy --no-pager
```
📸 Screenshot: the `ls -l` output and the `mysql.user` query result.
📸 Screenshot: `ss -ltnp` showing MySQL on `0.0.0.0:3306`, and `systemctl status f1fantasy` showing *active (running)*.

### I-6. Create the admin and demo users

```bash
cd ~/f1fantasy
set -a; . /etc/f1fantasy.env; set +a
.venv/bin/flask --app application create-admin      # prompts for username, email and password
.venv/bin/flask --app application seed-demo          # prints 5 demo logins ONCE: copy them now
```
📸 Screenshot: the `seed-demo` output. Blur the passwords if you include it in the report.

### I-7. Verify

1. From your laptop, check the health endpoint:
   ```powershell
   curl.exe http://<EIP>/health
   ```
   The expected output is `{"db":"ok","status":"ok"}`.
2. Open `http://<EIP>/` in a browser. Register a new user, create a fantasy team, and confirm that it appears on the **Leaderboard**.
3. From your laptop, log in as the grader:
   ```powershell
   mysql -h <EIP> -u grader -p f1fantasy
   ```
   Then run:
   ```sql
   SHOW GRANTS;                                   -- only USAGE + SELECT ON `f1fantasy`.*
   SELECT username, created_at FROM users ORDER BY id DESC LIMIT 3;   -- your new user is there
   SELECT * FROM v_leaderboard WHERE season = 2026 ORDER BY total_points DESC;
   INSERT INTO sync_log (season, summary) VALUES (2026, 'x');
   -- ERROR 1142 (42000): INSERT command denied to user 'grader'@...
   ```
📸 Screenshot: `curl` returning `{"db":"ok","status":"ok"}`.
📸 Screenshot: the home page in a browser, with the EIP visible in the address bar.
📸 Screenshot: your fantasy team on the leaderboard.
📸 Screenshot: the grader session showing `SHOW GRANTS`, your new user's row, and the **INSERT denied** error.

---

## Part II — S3 + Elastic Beanstalk + RDS (PaaS)

### II-1. Create the RDS MySQL instance (separately from Beanstalk)

The database is created on its own rather than inside the Beanstalk environment, so it survives if the environment is rebuilt or terminated.

1. Open **RDS → Databases → Create database**, and choose **Standard create**.
2. **Engine:** MySQL. **Version:** the latest MySQL 8.0 or 8.4.
3. **Templates:** *Free tier*.
4. **DB instance identifier:** `f1fantasy-db`. **Master username:** `admin`. **Master password:** choose one and note it.
5. **Instance class:** `db.t3.micro` or `db.t4g.micro`. **Storage:** 20 GiB gp2/gp3. Disable storage autoscaling.
6. **Connectivity:**
   - **Public access: Yes** (the grader connects from outside AWS).
   - **VPC security group:** create a new one named `f1fantasy-rds-sg`.
7. **Additional configuration:** leave *Initial database name* empty, because `schema.sql` creates `f1fantasy` itself.
8. Click **Create database**, and wait until the status is **Available** (about 5–10 minutes).
9. Open the database and copy its **Endpoint**, for example `f1fantasy-db.xxxx.us-east-1.rds.amazonaws.com`. This manual calls it `<RDS>`.
10. Open the `f1fantasy-rds-sg` security group and edit its inbound rules so that it allows **MySQL/Aurora 3306 from 0.0.0.0/0**. This allows both the grader and Beanstalk to connect.

📸 Screenshot: the RDS configuration summary (engine, instance class, *Publicly accessible: Yes*).
📸 Screenshot: the database page showing status **Available** and the endpoint.
📸 Screenshot: the `f1fantasy-rds-sg` inbound rule for port 3306.

### II-2. Load the schema, seed and accounts into RDS (from your laptop)

1. Copy `sql/create_users.sql` to `sql/create_users.local.sql`. Git ignores this file, so your passwords stay out of the repository.
2. In the copy, replace `CHANGE_ME_APP` and `CHANGE_ME_GRADER` with your passwords.
3. In PowerShell, from the project folder, run:
   ```powershell
   cmd /c "mysql -h <RDS> -u admin -p < sql\schema.sql"
   cmd /c "mysql -h <RDS> -u admin -p < sql\seed_2026.sql"
   cmd /c "mysql -h <RDS> -u admin -p < sql\create_users.local.sql"
   mysql -h <RDS> -u admin -p -e "SELECT COUNT(*) AS drivers FROM f1fantasy.drivers; SHOW GRANTS FOR 'grader'@'%';"
   ```
📸 Screenshot: the three load commands completing without errors, and the driver count and grants query.

### II-3. Build the bundle and upload it to S3

1. In Git Bash, from the project folder, build the bundle:
   ```bash
   bash deploy/build_eb_bundle.sh
   # OK: f1fantasy-eb.zip has N entries; application.py, Procfile, requirements.txt at root
   ```
   The bundle is built from the **last commit**, so commit your changes first.
2. Open **S3 → Create bucket**. Name it something like `f1fantasy-eb-fa23bds039` (bucket names are globally unique), use the same region as before, and keep *Block all public access* turned **on**.
3. Open the bucket, choose **Upload**, and add `f1fantasy-eb.zip`.
4. Open the uploaded object and copy its **Object URL** (`https://<bucket>.s3.<region>.amazonaws.com/f1fantasy-eb.zip`).

📸 Screenshot: the build script's `OK:` line.
📸 Screenshot: the bucket showing `f1fantasy-eb.zip` and its Object URL.

### II-4. Create the Elastic Beanstalk application and environment

1. Open **Elastic Beanstalk → Create application**.
2. **Environment tier:** *Web server environment*.
3. **Application name:** `f1fantasy`. **Environment name:** `f1fantasy-env`.
4. **Platform:** *Python*, with the branch *Python 3.12 running on 64bit Amazon Linux 2023*.
5. **Application code:** *Upload your code*, then choose **Public S3 URL** (or *S3 URL*) and paste the Object URL. **Version label:** `v1`.
6. **Presets:** *Single instance (free tier eligible)*.
7. **Service access:** use the existing roles `aws-elasticbeanstalk-service-role` and `aws-elasticbeanstalk-ec2-role`, or let the console create them. An EC2 key pair is optional.
8. **Database:** do **not** add a database here, because RDS is already separate.
9. Leave the rest at the defaults and click **Submit**. The environment is ready in about 5 minutes.

📸 Screenshot: the platform and application code page showing the S3 URL.
📸 Screenshot: the environment dashboard when it is created.

### II-5. Set the environment properties

1. Open **Configuration → Updates, monitoring, and logging → Edit**, then scroll to **Environment properties**.
2. Add these properties:

   | Name | Value |
   |---|---|
   | `FLASK_ENV` | `production` |
   | `SECRET_KEY` | 64 random hex characters (generate with `python -c "import secrets; print(secrets.token_hex(32))"`) |
   | `DB_HOST` | `<RDS>` endpoint |
   | `DB_PORT` | `3306` |
   | `DB_NAME` | `f1fantasy` |
   | `DB_USER` | `f1app` |
   | `DB_PASSWORD` | your f1app password |
   | `F1_SEASON` | `2026` |

3. Click **Apply**. The environment restarts.

📸 Screenshot: the environment properties. Blur `SECRET_KEY` and `DB_PASSWORD`.

### II-6. Allow Beanstalk to reach RDS

`f1fantasy-rds-sg` already allows 3306 from `0.0.0.0/0` (step II-1). For a tighter rule that you can show in the report, also add an inbound rule to `f1fantasy-rds-sg`: **MySQL/Aurora 3306, Source = the Beanstalk instance's security group**. To find that group, open **EC2 → Instances → the `f1fantasy-env` instance → Security**; its name contains `AWSEBSecurityGroup`.

📸 Screenshot: the RDS security group inbound rules, including the Beanstalk security group as a source.

### II-7. Verify

1. Open the environment URL, for example `http://f1fantasy-env.eba-xxxx.us-east-1.elasticbeanstalk.com/health`. The expected output is `{"db":"ok","status":"ok"}`, and the environment health shows **Ok** (green).
2. Register a user and create a fantasy team.
3. Optional: create the demo users from your laptop, pointing the CLI at RDS. In PowerShell, run:
   ```powershell
   $env:FLASK_ENV="production"; $env:SECRET_KEY="x"; $env:DB_HOST="<RDS>"; $env:DB_USER="f1app"; $env:DB_PASSWORD="<f1app pw>"
   .venv\Scripts\flask --app application seed-demo
   .venv\Scripts\flask --app application create-admin
   ```
4. Check the data as the grader:
   ```powershell
   mysql -h <RDS> -u grader -p f1fantasy -e "SELECT id, username, created_at FROM users ORDER BY id DESC LIMIT 3; SELECT * FROM v_leaderboard ORDER BY total_points DESC;"
   ```
📸 Screenshot: the environment dashboard showing health **Ok** and the URL.
📸 Screenshot: `/health` in the browser at the Beanstalk URL.
📸 Screenshot: your new user and team on the site.
📸 Screenshot: the grader query on RDS showing that same user.

---

## Updating a deployment

- **EC2:** `git push`, then on the instance run `cd ~/f1fantasy && git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart f1fantasy`. Alternatively, re-run `ec2_setup.sh`.
- **Beanstalk:** commit your changes, run `bash deploy/build_eb_bundle.sh`, upload the zip to S3, then choose **Upload and deploy** in the environment and give it a new version label.
- **Refresh F1 data:** log in as admin and click **Admin → Sync from API**, or run `flask --app application sync-data --season 2026` with the env file loaded.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| **502 Bad Gateway on Beanstalk** | gunicorn did not start. Usually the module or callable name doesn't match, or a dependency failed to install. | The Procfile must say `application:application`, and `application.py` must define `application = create_app()`. Check **Logs → Request logs → Last 100 lines** (`web.stdout.log`, `eb-engine.log`). |
| Beanstalk: *"Your source bundle has a single top-level folder"*, or `Procfile` not found | You zipped the parent folder instead of its contents. | Use `deploy/build_eb_bundle.sh` (`git archive` zips the contents). Check that `application.py` is at the root of the zip. |
| `RuntimeError: 'cryptography' package is required for sha256_password or caching_sha2_password auth methods` | MySQL 8's default authentication needs the `cryptography` package. | Make sure `cryptography` is in `requirements.txt` (it is), then reinstall or redeploy. |
| `Can't connect to MySQL server on '<EIP>' (10060/110)` from the laptop, while the site works | MySQL is listening only on `127.0.0.1`. | `sudo grep bind-address /etc/mysql/mysql.conf.d/mysqld.cnf` should show `0.0.0.0`. Fix it, then run `sudo systemctl restart mysql` and check with `sudo ss -ltnp \| grep 3306`. |
| Connection timeout on 3306 (EC2 or RDS) | Port 3306 is not open in the security group. | Add an inbound rule for MySQL/Aurora 3306 from `0.0.0.0/0` to the instance's or RDS's security group. |
| RDS connection times out from the laptop, but Beanstalk works | RDS is not publicly accessible. | Open **RDS → Modify → Connectivity → Public access: Yes → Apply immediately**. Also make sure its subnets have an internet gateway route (the default VPC does). |
| `Access denied for user 'f1app'@'...'` | The password is wrong, or `create_users.sql` was not loaded. | Check `DB_PASSWORD`. Run `SELECT user, host FROM mysql.user;` as admin or root. |
| `/health` returns 503 | The app is running but cannot reach the database. | Check the `DB_*` variables. On Beanstalk, check the security group rule in step II-6. |
| EC2: 502 from nginx | gunicorn is not running. | Run `sudo journalctl -u f1fantasy -n 50 --no-pager`. Common causes are a missing env file, or a bad `SECRET_KEY` line. |
| `ERROR 1062 Duplicate entry` when loading the seed | The seed was already loaded. | This is harmless. The seed only goes into an empty database (`ec2_setup.sh` checks for this). |
