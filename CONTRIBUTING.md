# Contributing to BikeHound

Thanks for helping people get their bikes back. The most useful contributions are fixes when a
marketplace changes its pages, and new marketplaces.

Before a larger change, open an issue so we can agree on the approach. The design and the
reasons behind it are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); open decisions are in
[docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md).

## Setup

You need [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/wiebe-vandendriessche/bikehound.git
cd bikehound
uv sync                              # Python 3.14 and the dependencies
uv run playwright install chromium   # only for the browser sources (Vinted, Facebook)
```

## Tests and lint

```bash
uv run pytest
uv run ruff check
uv run ruff format
```

Tests run offline on recorded fixtures and pure logic. They never download the image model and
never open a browser. CI runs the same three commands on every pull request. Live behaviour is
checked by hand with `uv run bikehound check`, never in CI: marketplaces block datacenter IPs.

## Adding or fixing a marketplace

A marketplace is one module in `src/bikehound/sources/`:

- a pure `parse(raw) -> list[Listing]` that turns a recorded response into listings;
- `search(cfg, since, max_pages=None, fetch=None)`, where `fetch` does the network part and is
  injected in tests;
- `Blocked` raised on a block, CAPTCHA, login wall, or a first page that is suspiciously empty
  (a silent zero is the most likely way to miss a bike).

Then register it in `SOURCES` (`sources/__init__.py`) and `PLATFORMS` (`config.py`), add a
fixture and tests next to the existing ones, and add a facts section to ARCHITECTURE.md with
what you measured (endpoints, page caps, volume, location handling).

### Fixtures

Record a real response, then anonymise it before committing: fake listing ids, remove seller
names, profile data and anything else about a person, and replace image hosts with
`images.example.test`. Keep only the few listings the tests need.

## Project rules

These are part of the design, not style preferences. Pull requests that break them are not
merged:

- No bypassing bot protection: no stealth plugins, CAPTCHA solvers or rotating proxies. When a
  platform blocks, BikeHound skips it and tells the user.
- BikeHound never creates accounts and never logs in with someone's personal account.
- No paid APIs or third-party services that would see the user's searches or photos.
- No personal data in code, tests, fixtures or docs: not yours, not a seller's.
- Polite volume: one sequential pass a day, page caps, pauses between requests.

## Pull requests

Keep them focused on one change, describe what you tested (including any manual
`bikehound check` run), and fill in the checklist in the pull request template.

By contributing, you agree that your contribution is licensed under the
[GNU AGPL-3.0](LICENSE), like the rest of the project. Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md).
