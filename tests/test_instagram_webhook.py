from __future__ import annotations

import json
from pathlib import Path

from jobhunt.instagram.events import iter_comment_events, matches_trigger
from jobhunt.instagram.registry import JobRegistry
from jobhunt.instagram.store import WebhookStore


def payload():
    return {
        "object": "instagram",
        "entry": [{
            "id": "17841424115240285",
            "time": 1789820570,
            "changes": [{
                "field": "comments",
                "value": {
                    "id": "comment-123",
                    "media": {"id": "media-456"},
                    "text": "interested",
                    "from": {"id": "viewer-9", "username": "viewer"},
                    "timestamp": "2026-09-20T10:00:00+00:00",
                },
            }],
        }],
    }


def test_comment_parser_extracts_media_and_comment_ids():
    events = list(iter_comment_events(payload()))
    assert len(events) == 1
    event = events[0]
    assert event.comment_id == "comment-123"
    assert event.media_id == "media-456"
    assert event.text == "interested"
    assert event.commenter_id == "viewer-9"


def test_any_comment_trigger_accepts_any_text():
    assert matches_trigger("hello", "any")
    assert matches_trigger("🔥", "any")


def test_keyword_trigger_is_case_insensitive():
    assert matches_trigger("send link please", "keyword", "LINK")
    assert not matches_trigger("hello", "keyword", "LINK")


def test_registry_finds_post_by_instagram_media_id(tmp_path: Path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([
        {"instagram_media_id": "media-456", "company": "Acme", "url": "https://example.com/job"}
    ]), encoding="utf-8")
    post = JobRegistry(path).find_by_media_id("media-456")
    assert post["url"] == "https://example.com/job"


def test_webhook_store_dedupes(tmp_path: Path):
    store = WebhookStore(tmp_path / "events.sqlite3")
    assert store.claim("comment:1", "1", "media", "{}", "now") is True
    assert store.claim("comment:1", "1", "media", "{}", "now") is False
    assert store.has_event("comment:1") is True
