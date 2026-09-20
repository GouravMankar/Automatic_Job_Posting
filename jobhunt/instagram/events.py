"""Normalize Instagram webhook comment payloads into a small internal shape."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class CommentEvent:
    instagram_user_id: str
    comment_id: str
    media_id: str
    text: str
    commenter_id: str | None = None
    commenter_username: str | None = None
    timestamp: str | None = None


def _value_to_event(ig_user_id: str, value: dict[str, Any]) -> CommentEvent | None:
    comment_id = str(value.get("id") or value.get("comment_id") or "")
    media = value.get("media")
    if isinstance(media, dict):
        media_id = str(media.get("id") or "")
    else:
        media_id = str(value.get("media_id") or media or "")
    text = str(value.get("text") or value.get("message") or "")
    if not comment_id or not media_id:
        return None
    from_obj = value.get("from") or value.get("user") or {}
    if not isinstance(from_obj, dict):
        from_obj = {}
    return CommentEvent(
        instagram_user_id=ig_user_id,
        comment_id=comment_id,
        media_id=media_id,
        text=text,
        commenter_id=str(from_obj.get("id")) if from_obj.get("id") is not None else None,
        commenter_username=str(from_obj.get("username")) if from_obj.get("username") is not None else None,
        timestamp=str(value.get("timestamp")) if value.get("timestamp") is not None else None,
    )


def iter_comment_events(payload: dict[str, Any]) -> Iterator[CommentEvent]:
    for entry in payload.get("entry", []) or []:
        if not isinstance(entry, dict):
            continue
        ig_user_id = str(entry.get("id") or "")
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict) or change.get("field") != "comments":
                continue
            value = change.get("value") or {}
            if isinstance(value, dict):
                event = _value_to_event(ig_user_id, value)
                if event:
                    yield event


def matches_trigger(text: str, mode: str = "any", keyword: str = "LINK") -> bool:
    if mode.lower() == "any":
        return True
    normalized = " ".join((text or "").lower().split())
    target = " ".join((keyword or "LINK").lower().split())
    return bool(target and (normalized == target or target in normalized))
