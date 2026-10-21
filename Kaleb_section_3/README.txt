ComfyUI Project Health scripts
==============================

Fixed analysis period: 2025-10-18 through 2026-10-17 (inclusive)
Pinned master snapshot: c9ea36b9d2140c89b2ef84f93f428df474e72ba5
Sampling seed: 20261017

No third-party Python packages are required.

Recommended usage:

  # Use a read-only GitHub token to avoid API rate limits.
  # Linux/macOS:
  export GITHUB_TOKEN=YOUR_TOKEN
  # PowerShell:
  $env:GITHUB_TOKEN="YOUR_TOKEN"

  python 01_collect_activity.py --out output
  python 02_analyze_contributors.py --data output
  python 03_sample_artifacts.py --data output

Important outputs:
  output/metadata.json
  output/contributors.csv
  output/contributor_summary.json
  output/bot_candidates.csv
  output/author_aliases.csv
  output/identity_candidates.csv
  output/sample_prs.csv
  output/sample_issues.csv
  output/sample_summary.json

The scripts never write to GitHub. They only perform read-only REST API calls.
Cross-account identity merging is intentionally conservative: candidates are
reported in identity_candidates.csv, but two GitHub accounts are merged only
when an explicitly reviewed mapping is added to ACCOUNT_ALIASES in
health_config.py.
