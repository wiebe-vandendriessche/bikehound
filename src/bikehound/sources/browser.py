"""A real Chromium with a fresh, empty, in-memory profile every run (D23).

Playwright's own Chromium, never the user's browser: nothing is written to disk and no
cookies, logins or history carry over between runs. BikeHound never logs in. Set
BIKEHOUND_HEADED=1 to show the window (e.g. under xvfb-run on a server) if a platform starts
blocking headless Chromium.
"""

import os
import random
import time
from contextlib import contextmanager

from playwright.sync_api import Error, sync_playwright

from . import Blocked

HEADLESS = not os.environ.get("BIKEHOUND_HEADED")


@contextmanager
def pages():
    """Yields get(url) -> the page's HTML as the server sent it, visited like a person would."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS)
            ctx = browser.new_context()  # incognito-like: discarded when the run ends
            try:
                tab = ctx.new_page()

                def get(url: str) -> str:
                    time.sleep(random.uniform(2, 5))
                    r = tab.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    if r is None or r.status != 200:
                        raise Blocked(f"HTTP {r.status if r else 'no response'}")
                    return r.text()

                yield get
            finally:
                browser.close()
    except Error as e:
        # also a missing Chromium: the message says to run `playwright install chromium`
        raise Blocked(f"browser: {e.message.splitlines()[0]}") from e
