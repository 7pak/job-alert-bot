# Deployment

The bot is one small Python process. It needs no inbound ports (Telegram is reached by long polling), about 100 MB of RAM and almost no CPU. Run it on any always-on Linux machine.

Two ways:

- **systemd** on an Ubuntu or Debian server (the main path, with a hardened unit and a one-command deploy script).
- **Docker** with `docker compose`, on any server and also on Windows or macOS for local testing.

Run only one copy per Telegram bot. Two copies polling the same bot make Telegram answer `409 Conflict`.

## Option A: any Ubuntu or Debian server (systemd)

You need SSH access with sudo, and Python 3.11 or newer on the server (Ubuntu 24.04 and Debian 12 or newer have it).

**1. One-time server setup.** Copy the setup script and run it:

```bash
scp deploy/setup_server.sh user@your-server:/tmp/
ssh user@your-server 'sudo bash /tmp/setup_server.sh'
```

It installs `python3-venv` and automatic security updates, creates a `jobbot` system user with no login shell, creates `/opt/job-alert-bot`, and caps the journal at 200 MB.

**2. Tell the deploy script where your server is.** Copy `deploy/.deploy.env.example` to `deploy/.deploy.env` (gitignored):

```
JOBBOT_HOST=ubuntu@203.0.113.10
JOBBOT_KEY=~/.ssh/id_ed25519
```

Environment variables with the same names win over the file. Optional: `JOBBOT_APP_DIR`, `JOBBOT_SERVICE`, `JOBBOT_USER`.

**3. Deploy.** From your computer (Linux, macOS, or Git Bash on Windows):

```bash
bash deploy/deploy.sh --with-secrets    # first time: also copies .env
bash deploy/deploy.sh                   # every later update
```

The script runs `jobbot check-config` locally first, then packs the code with your `config.yml`, `profile.yml` and `companies.yml`, copies it over SSH, installs the dependencies in a virtualenv, installs the systemd unit and restarts the service. Flags:

| Flag | What it adds |
|---|---|
| `--with-secrets` | Copies `.env` (first deploy, or after rotating a token). |
| `--with-db` | Copies `data/jobs.db` (only when moving an existing bot to a new server; stop the old copy first). |
| `--with-cv` | Copies `cv.md` or `cv.docx` (only with CV tailoring on). |

Extra packages: when CV tailoring is on in your `config.yml`, `deploy.sh` also installs what it needs on the server (the `anthropic` SDK, and `python-docx` for .docx). Override with `JOBBOT_EXTRAS` in `deploy/.deploy.env`.

**4. Check it.**

```bash
ssh user@your-server 'systemctl status job-alert-bot'
ssh user@your-server 'journalctl -u job-alert-bot -f'
```

Then send `/stats` to your bot.

The unit (`deploy/job-alert-bot.service`) restarts the bot on crashes, runs it as the unprivileged `jobbot` user, mounts the system read-only and lets it write only to `data/`. The database schema only ever gets new columns, so updates never need a reset.

## Option B: Docker

Create the data folder and your files **before** the first start. Docker turns a missing file into an empty folder, and on Linux a missing `data/` would be created owned by root, so SQLite could not open it.

```bash
mkdir -p data
cp config.example.yml config.yml        # or run `jobbot init` with Python installed
cp profile.example.yml profile.yml
cp companies.example.yml companies.yml
cp .env.example .env                    # then fill in the Telegram values
docker compose up -d --build
docker compose logs -f
```

If you forgot one, the bot stops with "config.yml is a folder, not a file": delete that folder, create the file and start again.

The image is `python:3.12-slim` based and builds for amd64 and arm64 (Oracle Ampere, Raspberry Pi). Your files are mounted read-only and `data/` keeps the database. On Linux, the container runs with uid 1000 so `data/` stays yours; set `JOBBOT_UID` and `JOBBOT_GID` if your user id differs.

Run one-off commands in the container:

```bash
docker compose run --rm jobbot python -m jobbot check-config
docker compose run --rm jobbot python -m jobbot once --dry-run -v
```

For CV tailoring: put `cv.md` or `cv.docx` in a `cv/` folder, set `tailoring.cv_file: cv/cv.md` (or `cv/cv.docx`) in `config.yml`, uncomment the `./cv` volume in `docker-compose.yml`, and build with `docker compose build --build-arg EXTRAS="anthropic python-docx"`.

## Where to run it

Prices and free tiers change. Check the provider's current terms before you sign up.

| Provider | Notes |
|---|---|
| **Oracle Cloud Always Free** | Ampere A1 (arm64) instances are free within the Always Free limits and are more than enough. Oracle may reclaim Always Free instances that stay idle for 7 days (very low CPU, network and memory use), and this bot is light. Upgrading the account to Pay As You Go keeps Always Free resources free and avoids the idle reclamation. Open no ingress ports beyond SSH. |
| **Google Cloud e2-micro** | One e2-micro VM in some US regions is part of the free tier, with a small disk and limited free egress. The bot's traffic is small. |
| **AWS** | The current free plan for new accounts is credit based and time limited. Plan for a small monthly cost after it ends, or pick another provider. |
| **Hetzner or any VPS** | The smallest ARM or x86 plan (a few euros a month) is plenty. |
| **Raspberry Pi or a home Linux box** | Works well with Docker or systemd. Keep it on and online. Use `setup_server.sh` on Raspberry Pi OS (Debian based). |

Firewall: the bot only makes outbound HTTPS requests. Keep inbound closed except SSH (ideally key-only).

## Health checks (optional)

Set `healthcheck_url` in `config.yml` to a ping URL from healthchecks.io (free plan) or a similar service. The bot pings it after good source runs, at most every 5 minutes. Set the check's period to about 30 minutes and you get an email when the bot stops.

## Updating

Pull or edit the code, then run `bash deploy/deploy.sh` (systemd) or `docker compose up -d --build` (Docker). Your files and the database stay as they are.
