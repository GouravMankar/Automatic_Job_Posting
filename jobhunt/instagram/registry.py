"""Lookup published jobs by Instagram Media ID."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JobRegistry:
    def __init__(self, manifest_path: str | Path = "out/channel/posts.json"):
        self.path = Path(manifest_path)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def find_by_media_id(self, media_id: str) -> dict[str, Any] | None:
        media_id = str(media_id or "")
        for post in self._load():
            if str(post.get("instagram_media_id") or "") == media_id:
                return post
        return None
