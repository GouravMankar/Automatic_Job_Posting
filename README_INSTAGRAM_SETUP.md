# Instagram Automation Setup

## One-command local webhook

After installing requirements and configuring `.env`:

```powershell
python -m jobhunt instagram-webhook
```

In a second terminal:

```powershell
ngrok http 8000
```

ngrok gives the local webhook a public HTTPS URL for Meta to call. Official guide: https://ngrok.com/use-cases/share-localhost

Set the Meta callback URL to:

```text
https://YOUR-NGROK-URL/webhooks/instagram
```

Meta verification calls:

```text
GET /webhooks/instagram
```

Instagram comment events are received at:

```text
POST /webhooks/instagram
```

## Project behavior

- `channel-prepare` generates the job banner and caption.
- `channel-publish --yes` uploads the banner to Cloudinary, publishes it to Instagram, and records the Instagram media ID.
- The webhook uses the saved media ID to recover the exact job/application URL.
- `INSTAGRAM_COMMENT_TRIGGER_MODE=any` means any comment on a published job post triggers processing.
- `INSTAGRAM_COMMENT_AUTOMATION_ENABLED=false` turns off replies without disabling webhook receipt/logging.
- SQLite dedupe prevents the same comment event from being processed twice.
- Logs are written to `out/instagram_webhook.log`.
