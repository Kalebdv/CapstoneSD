"""Small GitHub REST client used by the project-health scripts.

Uses only the Python standard library. Set GITHUB_TOKEN in the environment;
a fine-grained read-only token is sufficient and strongly recommended.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API_ROOT = "https://api.github.com"


@dataclass
class GitHubClient:
    token: str | None = None
    user_agent: str = "ComfyUI-project-health-analysis/1.0"

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = os.environ.get("GITHUB_TOKEN")

    def _request(self, path_or_url: str) -> tuple[Any, dict[str, str]]:
        url = path_or_url if path_or_url.startswith("http") else API_ROOT + path_or_url
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self.user_agent,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        while True:
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    body = response.read().decode("utf-8")
                    return json.loads(body), dict(response.headers.items())
            except urllib.error.HTTPError as exc:
                # Respect GitHub rate-limit reset when possible.
                if exc.code in (403, 429):
                    reset = exc.headers.get("X-RateLimit-Reset")
                    retry_after = exc.headers.get("Retry-After")
                    if retry_after:
                        wait = int(retry_after) + 1
                    elif reset:
                        wait = max(1, int(reset) - int(time.time()) + 1)
                    else:
                        wait = 60
                    print(f"Rate limited by GitHub; sleeping {wait}s...", flush=True)
                    time.sleep(wait)
                    continue
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"GitHub API {exc.code} for {url}: {detail}") from exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            path = path + ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        data, _ = self._request(path)
        return data

    def search_issues(self, query: str, page: int = 1, per_page: int = 100) -> dict[str, Any]:
        return self.get(
            "/search/issues",
            {"q": query, "per_page": per_page, "page": page, "sort": "created", "order": "asc"},
        )

    def paged(self, path: str, params: dict[str, Any] | None = None, per_page: int = 100):
        params = dict(params or {})
        page = 1
        while True:
            params.update({"per_page": per_page, "page": page})
            items = self.get(path, params)
            if not isinstance(items, list):
                raise TypeError(f"Expected list from {path}, got {type(items).__name__}")
            yield from items
            if len(items) < per_page:
                break
            page += 1
