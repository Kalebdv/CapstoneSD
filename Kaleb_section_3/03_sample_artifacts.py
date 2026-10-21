#!/usr/bin/env python3
"""Draw the deterministic stratified samples described in Section 3.3."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from health_config import (
    ACCOUNT_ALIASES,
    ISSUES_PER_STATUS,
    PRS_PER_CONTRIBUTOR_GROUP,
    RANDOM_SEED,
    RECENT_START,
    SYSTEM_IDENTITIES,
)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def canonical(login: str) -> str:
    seen = set()
    while login in ACCOUNT_ALIASES and login not in seen:
        seen.add(login)
        login = ACCOUNT_ALIASES[login]
    return login


def write_csv(path: Path, data: list[dict]):
    if not data:
        path.write_text("", encoding="utf-8"); return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0])); w.writeheader(); w.writerows(data)


def temporal_sample(items: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Choose one random item from each chronological quantile bin."""
    items = sorted(items, key=lambda x: (x["created_at"], int(x["number"])))
    if len(items) <= n:
        return items
    chosen = []
    for b in range(n):
        lo = (b * len(items)) // n
        hi = ((b + 1) * len(items)) // n
        chosen.append(rng.choice(items[lo:hi]))
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="output")
    args = ap.parse_args()
    data = Path(args.data)
    rng = random.Random(RANDOM_SEED)

    contributors = {x["login"]: x for x in read_csv(data / "contributors.csv")}
    bots = {
        x["login"] for x in read_csv(data / "bot_candidates.csv")
        if x.get("excluded_as_bot") == "1"
    }
    prs = read_csv(data / "prs.csv")
    issues = read_csv(data / "issues.csv")

    # PRs: four mutually exclusive contributor strata.
    sample_prs = []
    group_sizes = {}
    for group in ("key", "frequent_non_key", "newcomer", "dormant"):
        candidates = []
        for p in prs:
            login = p.get("login", "")
            if not login or login in bots or login in SYSTEM_IDENTITIES:
                continue
            login = canonical(login)
            c = contributors.get(login)
            if not c or c["sampling_group"] != group:
                continue
            # Dormant contributors are represented by a PR from their active period;
            # newcomer samples are restricted to the period in which they are newcomers.
            d = p["created_at"][:10]
            if group == "dormant" and d >= RECENT_START.isoformat():
                continue
            if group == "newcomer" and d < RECENT_START.isoformat():
                continue
            row = dict(p)
            row["canonical_login"] = login
            row["sample_group"] = group
            candidates.append(row)
        group_sizes[group] = len(candidates)
        k = min(PRS_PER_CONTRIBUTOR_GROUP, len(candidates))
        selected = rng.sample(sorted(candidates, key=lambda x: int(x["number"])), k)
        sample_prs.extend(sorted(selected, key=lambda x: int(x["number"])))

    # Issues: 10 open and 10 closed at the fixed cutoff, spread over time by
    # chronological quantile bins rather than concentrated in one burst.
    sample_issues = []
    issue_sizes = {}
    for status in ("open", "closed"):
        candidates = [
            dict(x) for x in issues
            if x["state_at_cutoff"] == status
            and x.get("login") not in bots
            and x.get("login") not in SYSTEM_IDENTITIES
        ]
        issue_sizes[status] = len(candidates)
        selected = temporal_sample(candidates, ISSUES_PER_STATUS, rng)
        for x in selected:
            x["sample_group"] = f"issue_{status}"
        sample_issues.extend(selected)

    write_csv(data / "sample_prs.csv", sample_prs)
    write_csv(data / "sample_issues.csv", sample_issues)
    summary = {
        "random_seed": RANDOM_SEED,
        "pr_candidate_counts": group_sizes,
        "pr_sample_counts": {g: sum(x["sample_group"] == g for x in sample_prs) for g in group_sizes},
        "issue_candidate_counts": issue_sizes,
        "issue_sample_counts": {s: sum(x["sample_group"] == f"issue_{s}" for x in sample_issues) for s in issue_sizes},
        "pr_sample_numbers": {g: [int(x["number"]) for x in sample_prs if x["sample_group"] == g] for g in group_sizes},
        "issue_sample_numbers": {s: [int(x["number"]) for x in sample_issues if x["sample_group"] == f"issue_{s}"] for s in issue_sizes},
    }
    (data / "sample_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()