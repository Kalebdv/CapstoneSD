"""Fixed configuration for the ComfyUI project-health analysis."""

from datetime import date, timedelta

REPO = "Comfy-Org/ComfyUI"
OBS_START = date(2025, 10, 18)
OBS_END = date(2026, 10, 17)
# Last master commit at/before the observation cutoff.
SNAPSHOT_SHA = "c9ea36b9d2140c89b2ef84f93f428df474e72ba5"

RECENT_DAYS = 90
RECENT_START = OBS_END - timedelta(days=RECENT_DAYS - 1)  # inclusive

# Contributor categorisation. We use the maximum count in any activity type,
# rather than summing PRs/issues/commits, because a merged PR can also appear as
# a default-branch commit and would otherwise be double-counted.
FREQUENT_ACTIVITY_THRESHOLD = 12
FREQUENT_ACTIVE_MONTHS = 3
KEY_ACTIVITY_THRESHOLD = 50
KEY_ACTIVE_MONTHS = 6

# Deterministic qualitative sampling.
RANDOM_SEED = 20261017
PRS_PER_CONTRIBUTOR_GROUP = 10
ISSUES_PER_STATUS = 10

# Manual decisions are deliberately explicit and reviewable. Automatic signals
# are still exported so the report can show the evidence behind each decision.
MANUAL_BOTS = {
    "comfy-pr-bot",
}
HUMAN_OVERRIDES = {
    "octo-patch",  # borderline name/automation case; manually verified human
}

# GitHub placeholder/system identities that cannot be treated as one real contributor.
# "ghost" aggregates artifacts whose original authors deleted their GitHub accounts.
SYSTEM_IDENTITIES = {
    "ghost",
}

# Cross-GitHub-account aliases confirmed to belong to one individual.
# Keep empty until a candidate has been manually verified. Format:
#   "old-or-alternate-login": "canonical-login"
ACCOUNT_ALIASES: dict[str, str] = {}