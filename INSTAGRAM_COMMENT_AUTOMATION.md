# Instagram Comment -> Job Link Automation

This project includes its own FastAPI webhook for the workflow:

```text
Instagram job post
        ↓
user comments anything
        ↓
Meta sends a comment webhook
        ↓
FastAPI parses the event
        ↓
Instagram media ID → out/channel/posts.json
        ↓
find the job's official apply URL
        ↓
private reply to that comment
        ↓
optional public reply
```

The current default is **any comment**. Set `INSTAGRAM_COMMENT_TRIGGER_MODE=keyword` to use `INSTAGRAM_COMMENT_KEYWORD` instead.

## 1. Configure `.env`

Copy `.env.example` to `.env` and set:

```env
INSTAGRAM_ACCESS_TOKEN=...
INSTAGRAM_USER_ID=...
INSTAGRAM_COMMENT_AUTOMATION_ENABLED=true
INSTAGRAM_COMMENT_TRIGGER_MODE=any
INSTAGRAM_WEBHOOK_VERIFY_TOKEN=your-random-secret
```

For production, also set your Meta app secret and enable signature verification:

```env
META_APP_SECRET=...
INSTAGRAM_WEBHOOK_VERIFY_SIGNATURE=true
```

Never commit `.env`.

## 2. Install dependencies

```powershell
pip install -r requirements.txt
```

## 3. Start the local webhook

```powershell
python -m jobhunt instagram-webhook
```

Default endpoints:

- `GET /health`
- `GET /webhooks/instagram` — Meta verification
- `POST /webhooks/instagram` — webhook event receiver

## 4. Make localhost public with ngrok

In a second PowerShell window:

```powershell
ngrok http 8000
```

ngrok creates a public HTTPS URL that forwards to a local server and is designed for local webhook testing. See the official ngrok localhost/webhook guide: https://ngrok.com/use-cases/share-localhost

Use the resulting URL as the Meta callback URL:

```text
https://YOUR-NGROK-URL/webhooks/instagram
```

Use the same value configured in:

```env
INSTAGRAM_WEBHOOK_VERIFY_TOKEN=...
```

## 5. Subscribe the app to Instagram comment events

In the Meta developer dashboard, configure the Instagram webhook subscription for comment events using the callback URL above. The exact dashboard labels can vary by Meta API version.

## 6. Publish one test job first

```powershell
python -m jobhunt channel-prepare --mock --limit 1
python -m jobhunt channel-publish --limit 1 --yes
```

The publisher stores the Instagram media ID in `out/channel/posts.json`. The webhook uses that ID to find the correct application URL.

## 7. Test a comment

Comment on the published test post from another Instagram account. With `INSTAGRAM_COMMENT_TRIGGER_MODE=any`, even a comment such as `interested` triggers the lookup.

Check:

```text
out/instagram_webhook.log
instagram_webhook.sqlite3
```

The webhook ignores comments made by your own Instagram account and ignores duplicate event IDs.

## 8. Safety switches

To receive/log events without sending messages:

```env
INSTAGRAM_COMMENT_AUTOMATION_ENABLED=false
```

To turn off public replies but keep private replies:

```env
INSTAGRAM_PUBLIC_REPLY_ENABLED=false
```

To turn on public replies too:

```env
INSTAGRAM_PUBLIC_REPLY_ENABLED=true
```

## Important platform behavior

Meta's private-reply flow is constrained by Instagram's messaging rules. The application deliberately sends at most one private reply for a comment and records the event status to avoid duplicate replies. Confirm the current limits and eligibility for your account/API version in Meta's official documentation before production use.
