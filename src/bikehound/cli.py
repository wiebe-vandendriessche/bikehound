import argparse
import logging
import secrets
import sys
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path

import httpx

from . import notify, wizard
from .config import PLATFORMS, ConfigError, load
from .match import (
    PHOTO_EXT,
    frame_hit,
    listing_photo_score,
    load_model,
    reference_embeddings,
    score,
    word_warnings,
)
from .sources import SOURCES, Blocked
from .sources.lrp import UA
from .store import Store, now

log = logging.getLogger(__name__)


def init(args) -> int:
    dest = Path(args.config)
    if dest.exists():
        print(f"{dest} already exists, not overwriting")
        return 1
    asked = sys.stdin.isatty()  # cron or `docker run` without -it gets the plain template
    v = wizard.interactive() if asked else wizard.EXAMPLE
    text = files("bikehound").joinpath("config.example.yaml").read_text(encoding="utf-8")
    text = wizard.render(text, v).replace("{topic}", f"bikehound-{secrets.token_hex(12)}")
    dest.write_text(text, encoding="utf-8")
    ref = dest.parent / "reference"  # where the README says the photos go
    ref.mkdir(exist_ok=True)
    copied = wizard.copy_photos(v["photos"], ref)
    cfg = load(dest)  # an error here is a bug in init, not in the answers
    print(f"Wrote {dest}." + ("" if asked else " Edit it to describe your bike."))
    for w in word_warnings(cfg.keywords):
        print(f"Warning: {w}")
    if not cfg.keywords:
        print("No keywords: matching relies on the photos alone.")
    n = sum(p.suffix.lower() in PHOTO_EXT for p in ref.iterdir())
    print(
        f"{n} photos in {ref} ({copied} copied now)." if n else f"Put photos of your bike in {ref}."
    )
    print(f"Subscribe in the ntfy app to {cfg.ntfy_url}, then run `bikehound check`.")
    return 0


def photo_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True)


def check(args) -> int:
    cfg = load(Path(args.config))
    model = load_model()
    refs = reference_embeddings(model, cfg)
    print(
        f"Config ok, {len(refs)} reference photos embedded, platforms: {', '.join(cfg.platforms)}"
    )
    for w in word_warnings(cfg.keywords):
        log.warning(w)
    ok = True
    try:
        notify._send(cfg.ntfy_url, "BikeHound test notification", "BikeHound check", tags="dog")
        print("Test notification sent.")
    except httpx.HTTPError as e:
        print(f"Test notification FAILED: {e}")
        ok = False
    for platform in cfg.platforms:
        try:
            found = SOURCES[platform](cfg, today(), max_pages=1)
        except Exception as e:  # noqa: BLE001, why() logs the traceback
            print(f"{platform}: FAILED, {why(platform, e)}")
            ok = False
            continue
        with photo_client() as client:
            scored = sorted(((listing_photo_score(model, refs, client, l), l) for l in found),
                            key=lambda x: x[0], reverse=True)  # fmt: skip
        ps = [p for p, _ in scored]
        if not ps:
            print(f"{platform}: 0 listings on the first page(s)")
            continue
        print(f"{platform}: {len(found)} listings on the first page(s), photo score "
              f"median {ps[len(ps) // 2]:.2f}, p95 {ps[len(ps) // 20]:.2f}, max {ps[0]:.2f}")  # fmt: skip
        for p, l in scored[:3]:
            print(f"  {p:.2f}  {l.title[:60]}  {l.url}")
        hits = sorted(((s, l) for p, l in scored if (s := score(l, cfg, p)).notify(cfg.threshold)),
                      key=lambda h: h[0].total, reverse=True)  # fmt: skip
        by_text = sum(s.total - s.photo >= cfg.threshold for s, _ in hits)
        print(f"  would notify: {len(hits)} of {len(found)} ({by_text} by keywords alone)")
        for s, l in hits[:3]:
            print(f"  {s.total:.2f}  {s.reasons()}  {l.title[:40]}  {l.url}")
    return 0 if ok else 1


def today():
    return datetime.now().astimezone().date()


def why(platform: str, e: Exception) -> str:
    """The reason a platform failed. Anything but Blocked is unexpected: logged with traceback."""
    if isinstance(e, Blocked):
        return str(e)
    log.exception("%s: search failed", platform)
    return f"{type(e).__name__}: {e}. The site probably changed; see the log."


def run(args) -> int:
    cfg = load(Path(args.config))
    try:
        return _run(args, cfg)
    except ConfigError:
        raise
    except Exception as e:
        # anything unexpected still ends in a notification, or an unattended run dies silently
        log.exception("run crashed")
        try:
            notify.crashed(cfg.ntfy_url, f"{type(e).__name__}: {e}")
        except httpx.HTTPError as ne:
            log.warning("could not send the crash notification: %s", ne)
        return 1


def _run(args, cfg) -> int:
    store = Store(cfg.data_dir / "bikehound.sqlite")
    started = now()
    if today() > cfg.active_until:
        if not store.stopped_sent():
            notify.stopped(cfg.ntfy_url, cfg.active_until)
            store.record_run(started, False, "stopped")
        return 0
    if store.too_soon() and not args.force:
        log.info("last successful run was less than 12 hours ago, exiting (--force overrides)")
        return 0

    model = load_model()
    refs = reference_embeddings(model, cfg)
    status, digest, backfilled = {}, [], []
    for platform in args.platform or cfg.platforms:
        search = SOURCES[platform]
        try:
            # per platform, so a platform that was blocked or newly enabled catches up;
            # day-precision dates, so overlap a day; seen filters the repeats
            last = store.last_ok(platform)
            since = (
                cfg.stolen_on
                if last is None
                else max(cfg.stolen_on, last.astimezone().date() - timedelta(days=1))
            )
            log.info("%s: searching since %s", platform, since)
            listings = search(cfg, since)
        except Exception as e:  # noqa: BLE001, why() logs the traceback
            reason = why(platform, e)
            log.warning("%s: failed, %s", platform, reason)
            status[platform] = f"failed: {reason}"
            try:
                notify.failure(cfg.ntfy_url, platform, reason)
            except httpx.HTTPError as ne:
                log.warning("could not send the failure notification: %s", ne)
            continue
        new = [l for l in listings if not store.is_seen(l.platform, l.id)]
        log.info("%s: %d listings, scoring %d new", platform, len(listings), len(new))
        unsent = 0
        with photo_client() as client:
            for l in new:
                photo = 0.0 if frame_hit(l, cfg) else listing_photo_score(model, refs, client, l)
                s = score(l, cfg, photo)
                log.debug("%.2f  %s  %s  %s", s.total, s.reasons(), l.title[:60], l.url)
                if not s.notify(cfg.threshold):
                    store.record(l.platform, l.id, s.total, False)
                elif last is None:  # first run for this platform: one digest, not a flood
                    digest.append((l, s))  # sent together below, recorded once sent
                else:
                    try:
                        notify.match(cfg.ntfy_url, l, s)
                        store.record(l.platform, l.id, s.total, True)
                        log.info("%s: notified %.2f %s", platform, s.total, l.url)
                    except httpx.HTTPError as e:
                        # unrecorded, so the next run retries it
                        log.warning("%s: notification deferred, %s", platform, e)
                        unsent += 1
        if last is None:
            backfilled.append(platform)  # marked ok only once its digest is out, see below
        else:
            store.mark_ok(platform, started)
        status[platform] = f"ok: {len(new)} new" + (
            f", {unsent} notifications deferred" if unsent else ""
        )
    sent = notify.digest(cfg.ntfy_url, digest) if digest else []
    for l, s in sent:
        store.record(l.platform, l.id, s.total, True)
    if digest:
        status["digest"] = f"{len(sent)} of {len(digest)} matches sent"
    if len(sent) == len(digest):
        # a partly sent digest leaves these unmarked, so the next run backfills the rest again
        for platform in backfilled:
            store.mark_ok(platform, started)
    # a run limited with --platform does not count for the 12 h guard, so it never makes the
    # next full (cron) run skip; `since` is per platform, so nothing is searched twice
    summary = "; ".join(f"{k} {v}" for k, v in status.items())
    store.record_run(started, not args.platform, summary)
    log.info("done: %s", summary)
    # nonzero when a platform failed or notifications were deferred, for systemd/Docker
    bad = any(v.startswith("failed") or "deferred" in v for v in status.values())
    return 1 if bad or len(sent) < len(digest) else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="bikehound")
    p.add_argument("-c", "--config", default="config.yaml")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-q", "--quiet", action="store_true", help="log warnings and errors only")
    g.add_argument(
        "-v", "--verbose", action="count", default=0, help="-v: debug, -vv: also other libraries"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("init", init), ("check", check)):
        sub.add_parser(name).set_defaults(fn=fn)
    r = sub.add_parser("run")
    r.set_defaults(fn=run)
    r.add_argument("--force", action="store_true", help="ignore the 12 h guard")
    r.add_argument(
        "--platform",
        action="append",
        choices=sorted(PLATFORMS),
        help="search only this platform instead of the config's list (repeatable)",
    )
    args = p.parse_args()
    # -vv lets every library through (httpx logs each request); below that only bikehound's own
    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 2 else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    level = logging.WARNING if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    logging.getLogger("bikehound").setLevel(level)
    try:
        sys.exit(args.fn(args))
    except ConfigError as e:
        sys.exit(f"Config error: {e}")
