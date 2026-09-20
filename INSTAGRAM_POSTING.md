# Instagram posting

1. Put your real Instagram Login token, Instagram user ID, and Cloudinary credentials in `.env`.
2. Generate one banner: `python -m jobhunt channel-prepare --mock --limit 1`.
3. Preview without publishing: `python -m jobhunt channel-publish --limit 1`.
4. Publish one post: `python -m jobhunt channel-publish --limit 1 --yes`.

The command uploads the banner to Cloudinary as JPEG, passes the public HTTPS URL to Instagram's media container endpoint, then calls `media_publish`. The manifest records the image URL, container ID, and Instagram media ID.

Do not commit `.env`. Do not paste access tokens or API secrets into chat, screenshots, GitHub, or the repository.
