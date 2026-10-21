#!/usr/bin/env python3
"""Filter bots/aliases and compute deterministic contributor categories."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from health_config import (
    ACCOUNT_ALIASES,
    FREQUENT_ACTIVE_MONTHS,
    FREQUENT_ACTIVITY_THRESHOLD,
    HUMAN_OVERRIDES,
    KEY_ACTIVE_MONTHS,
    KEY_ACTIVITY_THRESHOLD,
    MANUAL_BOTS,
    OBS_END,
    OBS_START,
    RECENT_START,
)

BOT_RE = re.compile(r"(?:\[bot\]$|(?:^|[-_])bot(?:$|[-_]))", re.I)
VERSION_RE = re.compile(r"\b(?:v?\d+(?:\.\d+){1,4}|\d+)\b", re.I)
HEX_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)


def rows(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def canonical(login: str) -> str:
    seen = set()
    while login in ACCOUNT_ALIASES and login not in seen:
        seen.add(login)
        login = ACCOUNT_ALIASES[login]
    return login


def norm_template(message: str) -> str:
    first = message.split("\\n", 1)[0].strip().lower()
    first = HEX_RE.sub("<sha>", first)
    first = VERSION_RE.sub("<n>", first)
    return re.sub(r"\s+", " ", first)


def month_of(ts: str) -> str:
    return ts[:7] if ts else ""


def within(ts: str, start: date, end: date = OBS_END) -> bool:
    d = ts[:10]
    return bool(d and start.isoformat() <= d <= end.isoformat())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="output", help="directory produced by 01_collect_activity.py")
    args = ap.parse_args()
    data = Path(args.data)

    prs = list(rows(data / "prs.csv"))
    issues = list(rows(data / "issues.csv"))
    commits_all = list(rows(data / "commits.csv"))
    commits = [x for x in commits_all if x["is_merge"] == "0"]
    codeowners = set(json.loads((data / "codeowners.json").read_text(encoding="utf-8")))
    first_activity = json.loads((data / "first_activity.json").read_text(encoding="utf-8"))

    # --- Bot evidence -------------------------------------------------------
    by_login_messages: dict[str, list[str]] = defaultdict(list)
    user_types: dict[str, set[str]] = defaultdict(set)
    activity_counts: dict[str, Counter] = defaultdict(Counter)

    for kind, collection, time_field in (
        ("pr", prs, "created_at"), ("issue", issues, "created_at"), ("commit", commits, "author_date")
    ):
        for x in collection:
            login = x.get("login", "")
            if not login:
                continue
            user_types[login].add(x.get("user_type", ""))
            activity_counts[login][kind] += 1
            if kind == "commit":
                by_login_messages[login].append(x.get("message", ""))

    bot_rows = []
    excluded_bots = set()
    for login in sorted(activity_counts):
        msgs = by_login_messages.get(login, [])
        templates = Counter(norm_template(m) for m in msgs if m)
        template_ratio = (templates.most_common(1)[0][1] / len(msgs)) if msgs and templates else 0.0
        type_signal = "Bot" in user_types.get(login, set())
        name_signal = bool(BOT_RE.search(login))
        behavior_signal = len(msgs) >= 3 and template_ratio >= 0.75

        if login in HUMAN_OVERRIDES:
            bot = False
            reason = "manual human override"
        elif login in MANUAL_BOTS:
            bot = True
            reason = "manual bot classification"
        elif type_signal:
            bot = True
            reason = "GitHub user type is Bot"
        elif name_signal and behavior_signal:
            bot = True
            reason = "bot-like identity + repetitive commit behavior"
        else:
            bot = False
            reason = "insufficient bot evidence"
        if bot:
            excluded_bots.add(login)

        bot_rows.append({
            "login": login,
            "user_types": ";".join(sorted(t for t in user_types[login] if t)),
            "prs": activity_counts[login]["pr"],
            "issues": activity_counts[login]["issue"],
            "commits": activity_counts[login]["commit"],
            "identity_type_signal": int(type_signal),
            "identity_name_signal": int(name_signal),
            "template_ratio": f"{template_ratio:.3f}",
            "behavior_signal": int(behavior_signal),
            "excluded_as_bot": int(bot),
            "reason": reason,
        })

    with (data / "bot_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        fields = list(bot_rows[0]) if bot_rows else ["login"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(bot_rows)

    # --- Identity evidence --------------------------------------------------
    alias_counter = Counter()
    emails: dict[str, set[str]] = defaultdict(set)
    names: dict[str, set[str]] = defaultdict(set)
    for x in commits:
        login = x.get("login", "")
        if not login:
            continue
        name = x.get("author_name", "").strip()
        email = x.get("author_email", "").strip().lower()
        alias_counter[(login, name, email)] += 1
        if email:
            emails[email].add(login)
        if name:
            names[name.casefold()].add(login)

    with (data / "author_aliases.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["login", "author_name", "author_email", "commit_count"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for (login, name, email), count in sorted(alias_counter.items()):
            w.writerow({"login": login, "author_name": name, "author_email": email, "commit_count": count})

    candidates = []
    for email, logins in emails.items():
        if len(logins) > 1:
            candidates.append({"evidence": "exact_email", "value": email, "logins": ";".join(sorted(logins))})
    for name, logins in names.items():
        if len(logins) > 1:
            candidates.append({"evidence": "exact_name", "value": name, "logins": ";".join(sorted(logins))})
    with (data / "identity_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["evidence", "value", "logins"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(sorted(candidates, key=lambda x:(x["evidence"],x["value"])))

    # --- Contributor metrics ------------------------------------------------
    stats = defaultdict(lambda: {
        "pr": 0, "issue": 0, "commit": 0,
        "recent_pr": 0, "recent_issue": 0, "recent_commit": 0,
        "pre_pr": 0, "pre_issue": 0, "pre_commit": 0,
        "months": set(), "pre_months": set(),
    })

    def add(kind: str, collection: list[dict], ts_field: str):
        for x in collection:
            login = x.get("login", "")
            if not login or login in excluded_bots:
                continue
            login = canonical(login)
            ts = x.get(ts_field, "")
            s = stats[login]
            s[kind] += 1
            if month_of(ts):
                s["months"].add(month_of(ts))
            if within(ts, RECENT_START):
                s[f"recent_{kind}"] += 1
            elif within(ts, OBS_START, RECENT_START - timedelta(days=1)):
                s[f"pre_{kind}"] += 1
                if month_of(ts):
                    s["pre_months"].add(month_of(ts))

    add("pr", prs, "created_at")
    add("issue", issues, "created_at")
    add("commit", commits, "author_date")

    contributor_rows = []
    category_counts = Counter()
    for login in sorted(stats):
        s = stats[login]
        p, i, c = s["pr"], s["issue"], s["commit"]
        volume_max = max(p, i, c)
        active_months = len(s["months"])
        breadth = sum(v > 0 for v in (p, i, c))
        frequent = volume_max >= FREQUENT_ACTIVITY_THRESHOLD and active_months >= FREQUENT_ACTIVE_MONTHS
        key = (volume_max >= KEY_ACTIVITY_THRESHOLD and active_months >= KEY_ACTIVE_MONTHS) or login in codeowners

        recent_total = s["recent_pr"] + s["recent_issue"] + s["recent_commit"]
        pre_max = max(s["pre_pr"], s["pre_issue"], s["pre_commit"])
        historical_frequent = pre_max >= FREQUENT_ACTIVITY_THRESHOLD and len(s["pre_months"]) >= FREQUENT_ACTIVE_MONTHS
        dormant = historical_frequent and recent_total == 0

        first = first_activity.get(login, {}).get("first_created_at", "")
        newcomer = bool(first and first[:10] >= RECENT_START.isoformat())

        # Mutually exclusive sampling group.
        if newcomer:
            group = "newcomer"
        elif dormant:
            group = "dormant"
        elif key:
            group = "key"
        elif frequent:
            group = "frequent_non_key"
        else:
            group = "other"
        category_counts[group] += 1

        contributor_rows.append({
            "login": login,
            "prs_12m": p,
            "issues_12m": i,
            "commits_12m": c,
            "active_months_12m": active_months,
            "activity_breadth": breadth,
            "volume_max": volume_max,
            "recent_prs": s["recent_pr"],
            "recent_issues": s["recent_issue"],
            "recent_commits": s["recent_commit"],
            "recent_total": recent_total,
            "codeowner": int(login in codeowners),
            "frequent": int(frequent),
            "key": int(key),
            "newcomer": int(newcomer),
            "dormant": int(dormant),
            "sampling_group": group,
            "first_repo_pr_or_issue": first,
        })

    contributor_rows.sort(key=lambda x: (-int(x["volume_max"]), x["login"].lower()))
    with (data / "contributors.csv").open("w", newline="", encoding="utf-8") as f:
        fields = list(contributor_rows[0]) if contributor_rows else ["login"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(contributor_rows)

    summary = {
        "human_contributors_in_window": len(contributor_rows),
        "excluded_bot_accounts": sorted(excluded_bots),
        "sampling_group_counts": dict(sorted(category_counts.items())),
        "thresholds": {
            "frequent_activity_in_one_type": FREQUENT_ACTIVITY_THRESHOLD,
            "frequent_active_months": FREQUENT_ACTIVE_MONTHS,
            "key_activity_in_one_type": KEY_ACTIVITY_THRESHOLD,
            "key_active_months": KEY_ACTIVE_MONTHS,
            "recent_start": RECENT_START.isoformat(),
        },
        "codeowners": sorted(codeowners),
        "top_20_by_volume_max": contributor_rows[:20],
        "identity_candidate_rows": len(candidates),
    }
    (data / "contributor_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
