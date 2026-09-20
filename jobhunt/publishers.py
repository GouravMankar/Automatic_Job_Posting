"""Publishing adapters for the public job channel.

Instagram uses Meta's Instagram API with Instagram Login for eligible
professional accounts. The image must be publicly reachable and is converted
to JPEG before upload. WhatsApp support remains a separate business-messaging
workflow and is not a group/channel poster.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests


def _instagram_token() -> str:
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Set INSTAGRAM_ACCESS_TOKEN in .env")
    return token


def _instagram_base() -> str:
    version = os.getenv("INSTAGRAM_API_VERSION", "v26.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"
    return f"https://graph.instagram.com/{version}"


def publish_instagram_image(image_url: str, caption: str) -> dict[str, Any]:
    """Create and publish a single-image Instagram post."""
    token = _instagram_token()
    ig_user_id = os.getenv("INSTAGRAM_USER_ID")
    if not ig_user_id:
        raise RuntimeError("Set INSTAGRAM_USER_ID in .env")
    if not image_url.startswith("https://"):
        raise ValueError("image_url must be an HTTPS URL")

    base = f"{_instagram_base()}/{ig_user_id}"
    headers = {"Authorization": f"Bearer {token}"}

    create = requests.post(
        f"{base}/media",
        params={"image_url": image_url, "caption": caption},
        headers=headers,
        timeout=60,
    )
    create.raise_for_status()
    creation_id = create.json().get("id")
    if not creation_id:
        raise RuntimeError(f"Instagram media container response had no id: {create.text}")

    publish = requests.post(
        f"{base}/media_publish",
        params={"creation_id": creation_id},
        headers=headers,
        timeout=60,
    )
    publish.raise_for_status()
    data = publish.json()
    data["creation_id"] = creation_id
    return data


def upload_cloudinary_jpeg(image_path: str | Path) -> dict[str, Any]:
    """Upload a local banner to Cloudinary as JPEG and return its secure URL."""
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError as exc:
        raise RuntimeError(
            "Cloudinary is not installed. Run: pip install cloudinary"
        ) from exc

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not all((cloud_name, api_key, api_secret)):
        raise RuntimeError(
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and "
            "CLOUDINARY_API_SECRET in .env"
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )

    result = cloudinary.uploader.upload(
        str(image_path),
        folder=os.getenv("CLOUDINARY_FOLDER", "daily-it-jobs"),
        format="jpg",
        resource_type="image",
        overwrite=False,
    )
    secure_url = result.get("secure_url")
    if not secure_url:
        raise RuntimeError(f"Cloudinary response had no secure_url: {result}")
    return result


def send_whatsapp_text(to: str, body: str) -> dict[str, Any]:
    """Send a supported WhatsApp Business Cloud API text message."""
    token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        raise RuntimeError("Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID in .env")
    version = os.getenv("WHATSAPP_API_VERSION", "v26.0").strip()
    if not version.startswith("v"):
        version = f"v{version}"
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    r = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return r.json()
