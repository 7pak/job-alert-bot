"""Find companies hiring in your region and which ATS board they use. Run it monthly.

Source: the public dataset github.com/Feashliaa/job-board-data (rebuilt daily from ATS boards).
Steps: download chunks -> keep jobs located in your region -> group by ATS board -> check each
board live -> merge into companies.yml. Hand-added entries and `enabled: false` flags are kept.

Usage:
  python tools/discover_companies.py --region gcc                 # a region pack from presets/regions
  python tools/discover_companies.py --countries "Germany,Berlin"  # or your own place names
  python tools/discover_companies.py --region dach --no-verify     # skip the live check
  python tools/discover_companies.py --region uk --out presets/companies/uk.yml
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobbot.http import BROWSER_UA  # noqa: E402
from jobbot.patterns import terms_re  # noqa: E402
from jobbot.profile import read_yaml  # noqa: E402

CACHE = ROOT / "data" / "dataset"
RAW = "https://raw.githubusercontent.com/Feashliaa/job-board-data/main/data/chunks/jobs_chunk_{i}.json.gz"

TECH = re.compile(r"engineer|developer|scientist|analyst|designer|devops|software|data|(?<![a-z])(?:ai|ml|qa)(?![a-z])", re.I)
URL_TOKEN = {
    "greenhouse": re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([A-Za-z0-9_-]+)"),
    "lever": re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)"),
}
# Internal or duplicate boards (referrals, campus resume drops, LinkedIn feeds): not useful.
SKIP_NAME = re.compile(r"referral|resume ?drop|campus|job wrapping|linkedin|external feed|talent (?:pool|community)", re.I)
CHECK = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever": "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{t}",
}


def download(max_chunks: int = 80) -> list[Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(max_chunks):
        f = CACHE / f"chunk_{i}.json.gz"
        if not f.exists() or time.time() - f.stat().st_mtime > 86400:
            r = requests.get(RAW.format(i=i), timeout=60)
            if r.status_code == 404:
                break
            r.raise_for_status()
            f.write_bytes(r.content)
        files.append(f)
    print(f"dataset: {len(files)} chunks")
    return files


def region_re(region: str | None, countries: str | None) -> re.Pattern:
    terms = [c.strip() for c in (countries or "").split(",") if c.strip()]
    if region:
        pack = ROOT / "presets" / "regions" / f"{region}.yml"
        if not pack.exists():
            sys.exit(f"unknown region {region}. Available: {', '.join(p.stem for p in pack.parent.glob('*.yml'))}")
        terms += [t for x in read_yaml(pack)["locations"]["targets"] for t in x["terms"]]
    if not terms:
        sys.exit("give --region or --countries")
    return terms_re(terms, caps_sensitive=True)


def region_boards(files: list[Path], where: re.Pattern) -> dict[tuple[str, str], dict]:
    boards: dict[tuple[str, str], dict] = defaultdict(lambda: {"local": 0, "tech": 0})
    for f in files:
        for j in json.load(gzip.open(f)):
            if not where.search(j.get("location") or ""):
                continue
            ats = (j.get("ats") or "").lower()
            rx = URL_TOKEN.get(ats)
            m = rx.search(j.get("url") or "") if rx else None
            if not m:
                continue
            b = boards[(ats, m.group(1))]
            b["local"] += 1
            b["tech"] += bool(TECH.search(j.get("title") or ""))
    return boards


def board_name(session: requests.Session, ats: str, token: str) -> str:
    if ats == "greenhouse":
        try:
            r = session.get(f"https://boards-api.greenhouse.io/v1/boards/{token}", timeout=20)
            if r.ok and r.json().get("name"):
                return r.json()["name"].strip()
        except (requests.RequestException, ValueError):
            pass
    return re.sub(r"[-_]+", " ", token.split(".")[0]).title()


def verify(boards: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    s = requests.Session()
    s.headers["User-Agent"] = BROWSER_UA
    alive = {}
    for n, ((ats, token), info) in enumerate(sorted(boards.items()), 1):
        try:
            r = s.get(CHECK[ats].format(t=token), timeout=30)
        except requests.RequestException as exc:
            print(f"  ? {ats} {token}: {exc.__class__.__name__}")
            continue
        if r.status_code != 200:
            print(f"  x {ats} {token}: HTTP {r.status_code}")
            continue
        data = r.json()
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        alive[(ats, token)] = {**info, "jobs_now": len(jobs), "name": board_name(s, ats, token)}
        if n % 25 == 0:
            print(f"  checked {n}/{len(boards)}")
        time.sleep(0.4)
    return alive


def merge(found: dict[tuple[str, str], dict], path: Path) -> None:
    current = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    current = current or {}
    added = 0
    for (ats, token), info in sorted(found.items(), key=lambda kv: -kv[1]["tech"]):
        rows = current.setdefault(ats, [])
        if any(r.get("token") == token for r in rows) or SKIP_NAME.search(info.get("name") or ""):
            continue
        rows.append({"name": info.get("name") or token, "token": token, "via": "dataset"})
        added += 1
    header = (
        "# Company boards polled by the bot. One entry per board.\n"
        "# name: shown in alerts. token: the board id in the ATS URL. enabled: false to pause one.\n"
        "# via: dataset = found by tools/discover_companies.py, otherwise added by hand.\n"
        "# smartrecruiters supports countries: [de, at, ...] to only list jobs there.\n\n"
    )
    body = yaml.safe_dump(current, sort_keys=False, allow_unicode=True, width=120, default_flow_style=None)
    path.write_text(header + body, encoding="utf-8")
    total = sum(len(v) for v in current.values())
    print(f"{path.name}: added {added}, total {total} boards")


def main() -> None:
    ap = argparse.ArgumentParser(description="Find ATS boards with jobs in your region.")
    ap.add_argument("--region", help="region pack name from presets/regions (gcc, dach, uk, us, eu)")
    ap.add_argument("--countries", help="comma separated place names, e.g. 'Germany,Berlin,Munich'")
    ap.add_argument("--no-verify", action="store_true", help="skip the live check of each board")
    ap.add_argument("--out", default=str(ROOT / "companies.yml"))
    args = ap.parse_args()

    where = region_re(args.region, args.countries)
    boards = region_boards(download(), where)
    print(f"boards with jobs in your region in the dataset: {len(boards)}")
    found = boards if args.no_verify else verify(boards)
    print(f"live boards: {len(found)}")
    merge(found, Path(args.out))


if __name__ == "__main__":
    main()
