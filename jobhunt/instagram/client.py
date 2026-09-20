"""Small client for the Instagram API flows used by the job channel."""
from __future__ import annotations

import os
from typing import Any

import requests


class InstagramAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _version() -> str:
    value = (os.getenv("INSTAGRAM_API_VERSION") or "v26.0").strip()
    return value if value.startswith("v") else f"v{value}"


def api_base() -> str:
    # Instagram Login / Graph endpoints use the graph.instagram.com host.
    return f"https://graph.instagram.com/{_version()}"


def _token() -> str:
    value = (os.getenv("INSTAGRAM_ACCESS_TOKEN") or "").strip()
    if not value:
        raise InstagramAPIError("INSTAGRAM_ACCESS_TOKEN is not set")
    return value


def _raise_api_error(response: requests.Response, operation: str) -> None:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:1000]
    detail = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        msg = detail.get("message") or response.text[:300]
        code = detail.get("code")
        message = f"{operation} failed: HTTP {response.status_code}; code={code}; message={msg}"
    else:
        message = f"{operation} failed: HTTP {response.status_code}; response={response.text[:500]}"
    raise InstagramAPIError(message, status_code=response.status_code, payload=payload)


def send_private_reply(comment_id: str, text: str) -> dict[str, Any]:
    """Send one private reply anchored to an Instagram comment."""
    ig_user_id = (os.getenv("INSTAGRAM_USER_ID") or "").strip()
    if not ig_user_id:
        raise InstagramAPIError("INSTAGRAM_USER_ID is not set")
    if not comment_id:
        raise InstagramAPIError("comment_id is required")
    url = f"{api_base()}/{ig_user_id}/messages"
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": text},
    }
    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=30,
    )
    if not response.ok:
        _raise_api_error(response, "Instagram private reply")
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def reply_to_comment(comment_id: str, text: str) -> dict[str, Any]:
    """Reply publicly to an Instagram comment."""
    if not comment_id:
        raise InstagramAPIError("comment_id is required")
    url = f"{api_base()}/{comment_id}/replies"
    response = requests.post(
        url,
        json={"message": text},
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=30,
    )
    if not response.ok:
        _raise_api_error(response, "Instagram public comment reply")
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}
