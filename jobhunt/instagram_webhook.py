"""FastAPI webhook for Instagram comments -> job-specific private replies."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .instagram.client import InstagramAPIError, reply_to_comment, send_private_reply
from .instagram.events import iter_comment_events, matches_trigger
from .instagram.registry import JobRegistry
from .instagram.store import WebhookStore



def _load_env() -> None:
    path = Path(os.getenv("JOBHUNT_ENV_FILE", ".env"))
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _setup_logger() -> logging.Logger:
    path = Path(os.getenv("INSTAGRAM_WEBHOOK_LOG_FILE", "out/instagram_webhook.log"))
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jobhunt.instagram_webhook")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(stream)
    return logger


def _verify_signature(body: bytes, request: Request) -> None:
    if not _truthy("INSTAGRAM_WEBHOOK_VERIFY_SIGNATURE", default=False):
        return
    secret = (os.getenv("META_APP_SECRET") or "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="META_APP_SECRET is required when signature verification is enabled")
    supplied = request.headers.get("x-hub-signature-256") or ""
    prefix = "sha256="
    if not supplied.startswith(prefix):
        raise HTTPException(status_code=403, detail="missing webhook signature")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied[len(prefix):], expected):
        raise HTTPException(status_code=403, detail="invalid webhook signature")


def _event_key(comment_id: str, timestamp: str | None, raw: bytes) -> str:
    if comment_id:
        return f"comment:{comment_id}"
    return "raw:" + hashlib.sha256(raw).hexdigest()


def create_app() -> FastAPI:
    _load_env()
    logger = _setup_logger()
    registry = JobRegistry(os.getenv("INSTAGRAM_POSTS_MANIFEST", "out/channel/posts.json"))
    store = WebhookStore(os.getenv("INSTAGRAM_WEBHOOK_DB", "instagram_webhook.sqlite3"))
    app = FastAPI(title="JobHunt Instagram Webhook", version="1.0.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "enabled": _truthy("INSTAGRAM_COMMENT_AUTOMATION_ENABLED", default=True)}

    @app.get("/webhooks/instagram", response_class=PlainTextResponse)
    async def verify_webhook(request: Request) -> str:
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        expected = os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "")
        if mode == "subscribe" and challenge and token and hmac.compare_digest(token, expected):
            logger.info("Webhook verification succeeded")
            return challenge
        logger.warning("Webhook verification failed")
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhooks/instagram")
    async def receive_webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        _verify_signature(body, request)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("Invalid JSON webhook: %s", exc)
            raise HTTPException(status_code=400, detail="invalid JSON") from exc

        enabled = _truthy("INSTAGRAM_COMMENT_AUTOMATION_ENABLED", default=True)
        trigger_mode = os.getenv("INSTAGRAM_COMMENT_TRIGGER_MODE", "any")
        keyword = os.getenv("INSTAGRAM_COMMENT_KEYWORD", "LINK")
        private_enabled = _truthy("INSTAGRAM_PRIVATE_REPLY_ENABLED", default=True)
        public_enabled = _truthy("INSTAGRAM_PUBLIC_REPLY_ENABLED", default=False)
        own_id = os.getenv("INSTAGRAM_USER_ID", "")
        private_template = os.getenv(
            "INSTAGRAM_PRIVATE_REPLY_TEMPLATE",
            "Hi! 👋\n\nHere is the official application link for this job:\n\n{url}\n\nPlease verify the details on the official company career page before applying.",
        )
        public_template = os.getenv(
            "INSTAGRAM_PUBLIC_REPLY_TEMPLATE",
            "📩 Check your messages — I've sent the official application link!",
        )

        processed = 0
        duplicates = 0
        ignored = 0
        for event in iter_comment_events(payload):
            key = _event_key(event.comment_id, event.timestamp, body)
            if not store.claim(
                key,
                event.comment_id,
                event.media_id,
                json.dumps(payload, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ):
                duplicates += 1
                continue
            logger.info(
                "Comment received comment_id=%s media_id=%s username=%s text=%r",
                event.comment_id, event.media_id, event.commenter_username, event.text[:200],
            )
            try:
                if not enabled:
                    store.update(key, "DISABLED", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    ignored += 1
                    continue
                if own_id and event.commenter_id and str(event.commenter_id) == str(own_id):
                    store.update(key, "IGNORED_OWN_ACCOUNT", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    ignored += 1
                    continue
                if not matches_trigger(event.text, trigger_mode, keyword):
                    store.update(key, "IGNORED_TRIGGER", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    ignored += 1
                    continue

                post = registry.find_by_media_id(event.media_id)
                if not post:
                    logger.warning("No published job found for media_id=%s", event.media_id)
                    store.update(key, "NO_JOB_MAPPING", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    ignored += 1
                    continue
                apply_url = str(post.get("url") or post.get("apply_url") or "").strip()
                if not apply_url:
                    store.update(key, "NO_APPLY_URL", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    ignored += 1
                    continue

                private_error = None
                if private_enabled:
                    message = private_template.format(
                        url=apply_url,
                        company=post.get("company", ""),
                        title=post.get("title", ""),
                    )
                    try:
                        send_private_reply(event.comment_id, message)
                        logger.info("Private reply sent comment_id=%s media_id=%s", event.comment_id, event.media_id)
                    except InstagramAPIError as exc:
                        private_error = str(exc)
                        logger.exception("Private reply failed comment_id=%s", event.comment_id)

                if public_enabled and private_error is None:
                    try:
                        reply_to_comment(event.comment_id, public_template.format(
                            url=apply_url,
                            company=post.get("company", ""),
                            title=post.get("title", ""),
                        ))
                        logger.info("Public comment reply sent comment_id=%s", event.comment_id)
                    except InstagramAPIError:
                        logger.exception("Public reply failed comment_id=%s", event.comment_id)

                if private_enabled and private_error:
                    store.update(key, "FAILED_PRIVATE_REPLY", error=private_error, processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                else:
                    store.update(key, "REPLIED", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                processed += 1
            except Exception as exc:  # keep webhook response 200 so provider doesn't endlessly replay a poison event
                logger.exception("Unhandled event error comment_id=%s", event.comment_id)
                store.update(key, "ERROR", error=f"{type(exc).__name__}: {exc}", processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

        return {"ok": True, "processed": processed, "duplicates": duplicates, "ignored": ignored}

    return app


app = create_app()
