"""A real Chromium on a persistent profile per platform, in data/profiles/<platform>/.

The profile is BikeHound's own and stays logged out: it never shares cookies with the user's
browser and BikeHound never logs in. Set BIKEHOUND_HEADED=1 to show the window (e.g. under
xvfb-run on a server) if a platform starts blocking headless Chromium.
"""

import os
import random
import time
from contextlib import contextmanager

from playwright.sync_api import Error, sync_playwright

from . import Blocked

HEADLESS = not os.environ.get("BIKEHOUND_HEADED")


@contextmanager
def pages(cfg, platform: str):
    """Yields get(url) -> the page's HTML as the server sent it, visited like a person would."""
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                cfg.data_dir / "profiles" / platform, headless=HEADLESS
            )
            try:
                tab = ctx.pages[0] if ctx.pages else ctx.new_page()

                def get(url: str) -> str:
                    time.sleep(random.uniform(2, 5))
                    r = tab.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    if r is None or r.status != 200:
                        raise Blocked(f"HTTP {r.status if r else 'no response'}")
                    return r.text()

                yield get
            finally:
                ctx.close()
    except Error as e:
        # also a missing Chromium: the message says to run `playwright install chromium`
        raise Blocked(f"browser: {e.message.splitlines()[0]}") from e
