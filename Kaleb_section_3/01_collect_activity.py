#!/usr/bin/env python3
"""Collect the fixed ComfyUI project-health observation window from GitHub.

Outputs CSV/JSON files only; no repository modifications are made.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

from github_api import GitHubClient
from health_config import OBS_END, OBS_START, RECENT_START, REPO, SNAPSHOT_SHA


def month_windows(start: date, end: date):
    cur = start
    while cur <= end:
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        window_end = min(end, next_month - timedelta(days=1))
        yield cur, window_end
        cur = window_end + timedelta(days=1)


def search_all(client: GitHubClient, kind: str, start: date, end: date):
    """Search all PRs or issues, split monthly to stay below Search's 1000 cap."""
    seen: dict[int, dict] = {}
    for a, b in month_windows(start, end):
        query = f"repo:{REPO} is:{kind} created:{a.isoformat()}..{b.isoformat()}"
        first = client.search_issues(query, page=1)
        total = min(int(first["total_count"]), 1000)
        pages = max(1, math.ceil(total / 100))
        batches = [first]
        for page in range(2, pages + 1):
            batches.append(client.search_issues(query, page=page))
        for batch in batches:
            for item in batch["items"]:
                seen[int(item["number"])] = item
        print(f"{kind}: {a}..{b}: {first['total_count']} items", flush=True)
    return [seen[k] for k in sorted(seen)]


def cutoff_state(item: dict) -> str:
    closed_at = item.get("closed_at")
    if closed_at and closed_at[:10] <= OBS_END.isoformat():
        return "closed"
    return "open"


def write_issue_like(path: Path, items: list[dict]):
    fields = [
        "number", "login", "user_type", "author_association", "created_at", "closed_at",
        "state_at_cutoff", "title", "comments", "url",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for x in items:
            u = x.get("user") or {}
            w.writerow({
                "number": x["number"],
                "login": u.get("login") or "",
                "user_type": u.get("type") or "",
                "author_association": x.get("author_association") or "",
                "created_at": x.get("created_at") or "",
                "closed_at": x.get("closed_at") or "",
                "state_at_cutoff": cutoff_state(x),
                "title": (x.get("title") or "").replace("\n", " "),
                "comments": x.get("comments", 0),
                "url": x.get("html_url") or "",
            })


def collect_commits(client: GitHubClient):
    params = {
        "sha": SNAPSHOT_SHA,
        "since": OBS_START.isoformat() + "T00:00:00Z",
        "until": OBS_END.isoformat() + "T23:59:59Z",
    }
    return list(client.paged(f"/repos/{REPO}/commits", params))


def write_commits(path: Path, commits: list[dict]):
    fields = [
        "sha", "login", "user_type", "author_name", "author_email", "author_date",
        "committer_date", "parent_count", "is_merge", "message", "url",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for c in commits:
            author = c.get("author") or {}
            commit = c.get("commit") or {}
            ca = commit.get("author") or {}
            cc = commit.get("committer") or {}
            parents = c.get("parents") or []
            w.writerow({
                "sha": c.get("sha") or "",
                "login": author.get("login") or "",
                "user_type": author.get("type") or "",
                "author_name": ca.get("name") or "",
                "author_email": ca.get("email") or "",
                "author_date": ca.get("date") or "",
                "committer_date": cc.get("date") or "",
                "parent_count": len(parents),
                "is_merge": int(len(parents) > 1),
                "message": (commit.get("message") or "").replace("\n", "\\n"),
                "url": c.get("html_url") or "",
            })


def collect_codeowners(client: GitHubClient) -> list[str]:
    data = client.get(f"/repos/{REPO}/contents/CODEOWNERS", {"ref": SNAPSHOT_SHA})
    import base64
    text = base64.b64decode(data["content"]).decode("utf-8")
    owners: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        for token in line.split()[1:]:
            if token.startswith("@") and "/" not in token:
                owners.add(token[1:])
    return sorted(owners)


def collect_first_activity(client: GitHubClient, prs: list[dict], issues: list[dict]) -> dict[str, dict]:
    """Find earliest PR/issue in accounts active in the recent 90-day period.

    The repository issues endpoint includes both issues and pull requests, which lets
    us establish earliest observable GitHub contribution with one core-API request per
    candidate rather than two Search requests.
    """
    candidates = set()
    recent = RECENT_START.isoformat()
    for x in prs + issues:
        if (x.get("created_at") or "")[:10] >= recent:
            login = (x.get("user") or {}).get("login")
            if login:
                candidates.add(login)

    out: dict[str, dict] = {}
    for i, login in enumerate(sorted(candidates), 1):
        items = client.get(
            f"/repos/{REPO}/issues",
            {"creator": login, "state": "all", "sort": "created", "direction": "asc", "per_page": 1},
        )
        if items:
            x = items[0]
            out[login] = {
                "first_number": x.get("number"),
                "first_created_at": x.get("created_at"),
                "first_url": x.get("html_url"),
                "first_type": "pr" if "pull_request" in x else "issue",
            }
        if i % 50 == 0:
            print(f"Earliest-activity lookup: {i}/{len(candidates)}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output", help="output directory")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    client = GitHubClient()
    if not client.token:
        print("WARNING: GITHUB_TOKEN is not set; GitHub's unauthenticated rate limits are low.")

    prs = search_all(client, "pr", OBS_START, OBS_END)
    issues = search_all(client, "issue", OBS_START, OBS_END)
    commits = collect_commits(client)
    codeowners = collect_codeowners(client)
    first_activity = collect_first_activity(client, prs, issues)

    write_issue_like(out / "prs.csv", prs)
    write_issue_like(out / "issues.csv", issues)
    write_commits(out / "commits.csv", commits)
    (out / "codeowners.json").write_text(json.dumps(codeowners, indent=2), encoding="utf-8")
    (out / "first_activity.json").write_text(json.dumps(first_activity, indent=2), encoding="utf-8")
    metadata = {
        "repository": REPO,
        "observation_start": OBS_START.isoformat(),
        "observation_end": OBS_END.isoformat(),
        "recent_start": RECENT_START.isoformat(),
        "snapshot_sha": SNAPSHOT_SHA,
        "pull_requests": len(prs),
        "issues": len(issues),
        "commits_all": len(commits),
        "commits_non_merge": sum(len(c.get("parents") or []) <= 1 for c in commits),
        "commits_unlinked_author": sum(not (c.get("author") or {}).get("login") for c in commits),
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
