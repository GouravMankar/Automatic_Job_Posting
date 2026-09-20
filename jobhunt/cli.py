"""jobhunt CLI: profile -> fetch -> prefilter -> screen -> draft -> digest -> mail.

The agent never submits an application. It finds, filters, ranks and drafts.
A human reads the digest, edits the note, and presses submit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from . import digest as digest_mod
from . import llm, mailer
from .fetch import fetch_all
from .mock import fetch_all_mock
from .prefilter import prefilter
from .providers import LLMError, resolve
from .store import Store
from .channel import is_it_job, prepare_posts
from .publishers import publish_instagram_image, upload_cloudinary_jpeg

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: str = ".env") -> None:
    """Minimal .env reader so there is no python-dotenv dependency."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cfg(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"config not found: {p}  (run from the project root)")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _load_profile(cfg: dict, allow_sample: bool) -> dict | None:
    path = Path(cfg.get("profile_file", "profile.json"))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    sample = ROOT / "profile.example.json"
    if allow_sample and sample.exists():
        print(f"  ! {path} missing — using {sample.name} for this dry run.")
        print("    Build the real one: python -m jobhunt profile --resume resume.pdf")
        return json.loads(sample.read_text(encoding="utf-8"))

    print(f"missing {path} — run `python -m jobhunt profile --resume <file>` first")
    return None


# ------------------------------------------------------------------ profile --
def cmd_profile(args) -> int:
    src = Path(args.resume)
    if not src.exists():
        print(f"resume not found: {src}")
        return 1
    is_pdf = src.suffix.lower() == ".pdf"

    try:
        provider, model = resolve("draft")
        print(f"reading {src.name} via {provider.name}/{model} ...")
        profile = llm.build_profile(
            resume_bytes=src.read_bytes() if is_pdf else None,
            resume_text=None if is_pdf else src.read_text(encoding="utf-8", errors="replace"),
            is_pdf=is_pdf, provider=provider, model=model,
        )
    except (LLMError, ValueError) as e:
        print(f"profile extraction failed: {e}")
        return 1

    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"wrote {args.out}\n")
    print(json.dumps(profile, indent=2, ensure_ascii=False)[:900])
    return 0


# ---------------------------------------------------------------------- run --
def cmd_run(args) -> int:
    cfg = _cfg(args.config)
    profile = _load_profile(cfg, allow_sample=args.mock)
    if profile is None:
        return 1
    store = Store(cfg.get("seen_file", "seen.json"))
    filters = cfg.get("filters", {}) or {}

    # ---- 1. fetch
    print("\n[1/5] fetching boards")
    if args.mock:
        jobs = fetch_all_mock()
    else:
        companies = _cfg(cfg.get("companies_file", "companies.yaml")).get("companies") or []
        if not companies:
            print("companies.yaml has no entries")
            return 1
        jobs = fetch_all(companies)
    scanned = len(jobs)
    if not scanned:
        print("no postings fetched — check the slugs in companies.yaml")
        return 1

    # ---- 2. prefilter + dedupe (deterministic, free, no LLM)
    print("\n[2/5] filtering")
    jobs = prefilter(jobs, filters)
    passed_filters = len(jobs)
    jobs = store.unseen(jobs)
    print(f"  new since last run: {len(jobs)}")
    candidates = len(jobs)
    if args.limit:
        jobs = jobs[:args.limit]
        print(f"  --limit {args.limit} applied")

    if not jobs:
        subject, doc = digest_mod.build([], scanned, 0, store.stats())
        path = digest_mod.write(doc, cfg.get("digest_file", "out/digest.html"))
        print(f"\nnothing new today. preview: {path}")
        return 0

    # ---- 3. screen
    scorer = "keyword" if args.scorer == "keyword" else "llm"
    if scorer == "keyword":
        print(f"\n[3/5] screening {len(jobs)} jobs (keyword stub — DEV ONLY)")
        llm.keyword_screen(jobs, profile)
    else:
        try:
            provider, model = resolve("screen")
        except LLMError as e:
            print(f"\n{e}\nNo key? Run with --scorer keyword for an offline dry run.")
            return 1
        print(f"\n[3/5] screening {len(jobs)} jobs via {provider.name}/{model}")
        llm.screen(jobs, profile,
                   batch_size=int(cfg.get("screen_batch_size", 8)),
                   jd_chars=int(cfg.get("screen_jd_chars", 1400)),
                   provider=provider, model=model)

    # If every batch failed, the digest would be empty and — worse — we would
    # record these jobs as seen and never show them again. Bail instead.
    if scorer == "llm" and not any(j.score is not None for j in jobs):
        print("\n! screening scored nothing: every batch failed.\n"
              "  Not recording these jobs, so the next run retries them.\n"
              "  Check the warnings above (bad key, rate limit, wrong model id).")
        return 1

    threshold = float(cfg.get("score_threshold", 7.0))
    top_n = int(cfg.get("max_per_digest", 5))
    shortlist = sorted([j for j in jobs if (j.score or 0) >= threshold],
                       key=lambda j: j.score or 0, reverse=True)[:top_n]
    print(f"  {len(shortlist)} scored >= {threshold}")

    # ---- 4. draft
    print(f"\n[4/5] drafting kits for {len(shortlist)}")
    if not shortlist:
        print("  nothing cleared the threshold")
    elif scorer == "keyword" or args.no_draft:
        print("  skipped (keyword scorer / --no-draft)")
    else:
        try:
            provider, model = resolve("draft")
            print(f"  via {provider.name}/{model}")
            llm.draft(shortlist, profile,
                      jd_chars=int(cfg.get("draft_jd_chars", 6000)),
                      provider=provider, model=model)
        except LLMError as e:
            print(f"  ! drafting unavailable: {e}")

    # ---- 5. digest
    print("\n[5/5] digest")
    subject, doc = digest_mod.build(shortlist, scanned, candidates, store.stats())
    path = digest_mod.write(doc, cfg.get("digest_file", "out/digest.html"))
    print(f"  wrote {path}")

    sent = False
    if args.send:
        try:
            mailer.send(subject, doc)
            sent = True
        except Exception as e:  # bad app password, blocked port, offline
            print(f"  ! email failed ({type(e).__name__}: {e}) — digest still on disk")
    else:
        print("  --send not passed, email skipped")

    store.record(jobs, emailed=sent)
    csv_path = store.export_csv(cfg.get("tracker_csv", "out/tracker.csv"))

    print(f"\nfunnel: {scanned} scanned -> {passed_filters} passed filters "
          f"-> {candidates} new -> {len(shortlist)} in digest")
    print(f"subject: {subject}")
    print(f"tracker: {store.stats()}  ({csv_path})")
    return 0


# -------------------------------------------------------------- channel --
def cmd_channel_prepare(args) -> int:
    cfg = _cfg(args.config)
    companies = _cfg(cfg.get("companies_file", "companies.yaml")).get("companies") or []
    if not companies:
        print("companies.yaml has no entries")
        return 1
    jobs = fetch_all_mock() if args.mock else fetch_all(companies)
    channel_cfg = cfg.get("channel", {}) or {}
    terms = channel_cfg.get("it_keywords") or None
    jobs = [j for j in jobs if is_it_job(j, terms)]
    # Keep public-channel dedupe separate from the personal resume job tracker.
    store = Store(cfg.get("channel_seen_file", "channel_seen.json"))
    jobs = store.unseen(jobs)
    if args.limit:
        jobs = jobs[:args.limit]
    posts = prepare_posts(jobs, channel_cfg.get("output_dir", "out/channel"), channel_cfg.get("hashtags"))
    print(f"prepared {len(posts)} channel posts")
    print(f"review manifest: {Path(channel_cfg.get('output_dir', 'out/channel')) / 'posts.json'}")
    print("Instagram banners: PNG 1080x1350 + SVG fallback")
    return 0


# --------------------------------------------------------- channel-publish --
def cmd_channel_publish(args) -> int:
    cfg = _cfg(args.config)
    channel_cfg = cfg.get("channel", {}) or {}
    manifest_path = Path(channel_cfg.get("output_dir", "out/channel")) / "posts.json"
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}")
        print("run: python -m jobhunt channel-prepare --limit 1")
        return 1

    posts = json.loads(manifest_path.read_text(encoding="utf-8"))
    pending = [p for p in posts if p.get("status") in {"READY_FOR_REVIEW", "READY_TO_PUBLISH", "FAILED"}]
    if args.limit:
        pending = pending[:args.limit]
    if not pending:
        print("no publishable posts found in posts.json")
        return 0

    if not args.yes:
        print(f"Prepared {len(pending)} post(s). No post will be published without --yes.")
        print("Preview first, then run: python -m jobhunt channel-publish --limit 1 --yes")
        return 0

    changed = False
    published = 0
    for idx, post in enumerate(pending, 1):
        banner = Path(post.get("banner", ""))
        if not banner.exists():
            print(f"[{idx}/{len(pending)}] missing banner: {banner}")
            post["status"] = "FAILED"
            post["publish_error"] = "banner file not found"
            changed = True
            continue

        print(f"[{idx}/{len(pending)}] {post.get('company')} — {post.get('title')}")
        try:
            upload = upload_cloudinary_jpeg(banner)
            image_url = upload["secure_url"]
            print("  Cloudinary: uploaded")
            result = publish_instagram_image(image_url, post.get("caption", ""))
            post["image_url"] = image_url
            post["cloudinary_public_id"] = upload.get("public_id")
            post["creation_id"] = result.get("creation_id")
            post["instagram_media_id"] = result.get("id")
            post["status"] = "PUBLISHED"
            post["published_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")
            post.pop("publish_error", None)
            published += 1
            changed = True
            print(f"  Instagram: published (media_id={result.get('id')})")
        except Exception as e:
            post["status"] = "FAILED"
            post["publish_error"] = f"{type(e).__name__}: {e}"
            changed = True
            print(f"  ! publish failed: {type(e).__name__}: {e}")

    if changed:
        manifest_path.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\npublished: {published}/{len(pending)}")
    return 0 if published == len(pending) else 1


# -------------------------------------------------------- instagram-webhook --
def cmd_instagram_webhook(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed — run: pip install -r requirements.txt")
        return 1
    print(f"Instagram webhook listening on http://{args.host}:{args.port}")
    print("Endpoints: GET/POST /webhooks/instagram and GET /health")
    uvicorn.run("jobhunt.instagram_webhook:app", host=args.host, port=args.port, reload=args.reload)
    return 0


# ------------------------------------------------------------------- misc --
def cmd_applied(args) -> int:
    store = Store(_cfg(args.config).get("seen_file", "seen.json"))
    ok = store.mark_applied(args.job_id)
    print("marked applied" if ok else f"unknown job_id: {args.job_id}")
    return 0 if ok else 1


def cmd_stats(args) -> int:
    cfg = _cfg(args.config)
    store = Store(cfg.get("seen_file", "seen.json"))
    print(json.dumps(store.stats(), indent=2))
    print(f"csv: {store.export_csv(cfg.get('tracker_csv', 'out/tracker.csv'))}")
    return 0


def main(argv=None) -> int:
    _load_env()
    p = argparse.ArgumentParser(
        prog="jobhunt",
        description="Personal job-search agent. Finds and drafts; never submits.")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("profile", help="turn a resume into profile.json")
    sp.add_argument("--resume", required=True, help="path to a .pdf, .txt or .md resume")
    sp.add_argument("--out", default="profile.json")
    sp.set_defaults(func=cmd_profile)

    sr = sub.add_parser("run", help="run the daily pipeline")
    sr.add_argument("--mock", action="store_true", help="bundled fixtures, no network")
    sr.add_argument("--scorer", choices=["llm", "keyword", "claude"], default="llm",
                    help="keyword = offline stub, needs no API key ('claude' is an "
                         "alias for 'llm', kept for older docs)")
    sr.add_argument("--no-draft", action="store_true", help="skip the expensive stage")
    sr.add_argument("--send", action="store_true", help="actually email the digest")
    sr.add_argument("--limit", type=int, help="cap jobs sent to the LLM (cost guard)")
    sr.set_defaults(func=cmd_run)

    sc = sub.add_parser("channel-prepare", help="prepare all IT jobs for channel review")
    sc.add_argument("--mock", action="store_true", help="use bundled fixtures")
    sc.add_argument("--limit", type=int, help="limit prepared posts")
    sc.set_defaults(func=cmd_channel_prepare)

    spub = sub.add_parser("channel-publish", help="publish prepared channel posts to Instagram")
    spub.add_argument("--limit", type=int, help="limit posts to publish")
    spub.add_argument("--yes", action="store_true", help="actually upload and publish")
    spub.set_defaults(func=cmd_channel_publish)

    sw = sub.add_parser("instagram-webhook", help="run the Instagram comment webhook server")
    sw.add_argument("--host", default=os.getenv("INSTAGRAM_WEBHOOK_HOST", "0.0.0.0"))
    sw.add_argument("--port", type=int, default=int(os.getenv("INSTAGRAM_WEBHOOK_PORT", "8000")))
    sw.add_argument("--reload", action="store_true", help="reload when Python files change")
    sw.set_defaults(func=cmd_instagram_webhook)

    sa = sub.add_parser("applied", help="mark a job_id as applied")
    sa.add_argument("job_id")
    sa.set_defaults(func=cmd_applied)

    ss = sub.add_parser("stats", help="tracker summary + CSV export")
    ss.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
