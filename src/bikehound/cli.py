import argparse
import secrets
import sys
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path

import httpx

from . import notify
from .config import ConfigError, load
from .match import frame_hit, listing_photo_score, load_model, reference_embeddings, score
from .sources import SOURCES, Blocked
from .sources.lrp import UA
from .store import Store, now


def init(args) -> int:
    dest = Path(args.config)
    if dest.exists():
        print(f"{dest} already exists, not overwriting")
        return 1
    text = files("bikehound").joinpath("config.example.yaml").read_text(encoding="utf-8")
    dest.write_text(text.replace("{topic}", f"bikehound-{secrets.token_hex(12)}"), encoding="utf-8")
    print(f"Wrote {dest}. Edit it, put photos in reference/, then run `bikehound check`.")
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
    notify._send(cfg.ntfy_url, "BikeHound test notification", "BikeHound check", tags="dog")
    print("Test notification sent.")
    ok = True
    for platform in cfg.platforms:
        if platform not in SOURCES:
            print(f"{platform}: source not implemented yet")
            continue
        try:
            found = SOURCES[platform](cfg, today(), max_pages=1)
        except Blocked as e:
            print(f"{platform}: FAILED, {e}")
            ok = False
            continue
        with photo_client() as client:
            scored = sorted(((listing_photo_score(model, refs, client, l), l) for l in found),
                            key=lambda x: x[0], reverse=True)  # fmt: skip
        ps = [p for p, _ in scored]
        print(f"{platform}: {len(found)} listings on the first page(s), photo score "
              f"median {ps[len(ps) // 2]:.2f}, p95 {ps[len(ps) // 20]:.2f}, max {ps[0]:.2f}")  # fmt: skip
        for p, l in scored[:3]:
            print(f"  {p:.2f}  {l.title[:60]}  {l.url}")
    return 0 if ok else 1


def today():
    return datetime.now().astimezone().date()


def run(args) -> int:
    cfg = load(Path(args.config))
    store = Store(cfg.data_dir / "bikehound.sqlite")
    started = now()
    if today() > cfg.active_until:
        if not store.stopped_sent():
            notify.stopped(cfg.ntfy_url, cfg.active_until)
            store.record_run(started, False, "stopped")
        return 0
    if store.too_soon():
        print("Last successful run was less than 12 hours ago, exiting.")
        return 0

    # day-precision dates, so overlap a day; seen filters the repeats
    last = store.last_ok_run()
    since = (
        cfg.stolen_on
        if last is None
        else max(cfg.stolen_on, last.astimezone().date() - timedelta(days=1))
    )
    first = store.first_run()
    model = load_model()
    refs = reference_embeddings(model, cfg)
    status, digest = {}, []
    for platform in cfg.platforms:
        search = SOURCES.get(platform)
        try:
            if search is None:
                raise Blocked("source not implemented yet")
            listings = search(cfg, since)
        except Blocked as e:
            status[platform] = f"failed: {e}"
            try:
                notify.failure(cfg.ntfy_url, platform, str(e))
            except httpx.HTTPError as ne:
                print(f"Could not send failure notification: {ne}")
            continue
        new = [l for l in listings if not store.is_seen(l.platform, l.id)]
        print(f"{platform}: scoring {len(new)} new listings")
        unsent = 0
        with photo_client() as client:
            for l in new:
                photo = 0.0 if frame_hit(l, cfg) else listing_photo_score(model, refs, client, l)
                s = score(l, cfg, photo)
                if not s.notify(cfg.threshold):
                    store.record(l.platform, l.id, s.total, False)
                elif first:
                    digest.append((l, s))  # sent together below, recorded once sent
                else:
                    try:
                        notify.match(cfg.ntfy_url, l, s)
                        store.record(l.platform, l.id, s.total, True)
                    except httpx.HTTPError:
                        # unrecorded, so the next run retries it
                        unsent += 1
        status[platform] = f"ok: {len(new)} new" + (
            f", {unsent} notifications deferred" if unsent else ""
        )
    if digest:
        sent = notify.digest(cfg.ntfy_url, digest)
        for l, s in sent:
            store.record(l.platform, l.id, s.total, True)
        status["digest"] = f"{len(sent)} of {len(digest)} matches sent"
    store.record_run(started, True, "; ".join(f"{k} {v}" for k, v in status.items()))
    print(status)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="bikehound")
    p.add_argument("-c", "--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("init", init), ("check", check), ("run", run)):
        sub.add_parser(name).set_defaults(fn=fn)
    # `login` joins when the Playwright sources exist
    args = p.parse_args()
    try:
        sys.exit(args.fn(args))
    except ConfigError as e:
        sys.exit(f"Config error: {e}")
