# BikeHound architecture

Status: design, agreed 2026-10-05. Nothing here is implemented yet.

## 1. Purpose and scope

BikeHound searches second-hand marketplaces once a day for one stolen bike and sends the owner a
push notification for every listing that might be it. The owner looks at the photo and decides.

Guiding rule: **a false positive costs the owner five seconds; a missed bike costs the bike.**
Every trade-off below leans toward reporting too much rather than too little.

**Audience:** technical users. People who can clone a repo or install a Python tool, edit a YAML
file and set up a cron job or a Docker container. Each user runs their own copy and carries their
own platform risk.

### In scope

- A command-line tool, run once a day by the host's scheduler (cron, systemd timer, Docker).
- Five marketplaces: 2dehands.be, Marktplaats.nl, Vinted, Leboncoin, Facebook Marketplace.
- Matching on photos (local image model) plus a text bonus for configured keywords.
- Push notifications through ntfy.
- One bike per config file.

### Deliberately out of scope

| Not included | Why |
|---|---|
| Hosted service, web UI, user accounts | Would make the maintainer run scrapers on behalf of others and hold their personal data. |
| Built-in scheduler or long-running daemon | Runs once a day; cron/systemd/Docker already schedule. |
| Plugin system for marketplaces | Five sources in one repo; new ones arrive as a pull request. |
| Bot-protection bypass (stealth plugins, paid proxies, CAPTCHA solvers) | Costs money, is an arms race, and actively circumvents platform security. |
| Creating or recommending throwaway accounts | Also against platform terms. |
| LLM or paid API in the matching | Costs per listing and sends photos to a third party; may also reject a true match. |
| Notification channels other than ntfy | Apprise is the upgrade path if users ask. |
| Automatic stop on a match | The tool cannot tell a false positive from the real bike. |
| Storing listing texts, seller data or listing photos | Not needed; data minimisation (GDPR). |
| Running on GitHub Actions or other CI as a scraper | Datacenter IPs get blocked; bike photos would leave the user's machine. |

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Audience: technical users who self-host. | Generic without needing a hosted service. |
| D2 | One-shot CLI (`bikehound run`), scheduled by the host; an official Docker image as an alternative install. | No daemon to keep alive; a home IP has the best chance against bot protection. |
| D3 | All five marketplaces in v1. 2dehands and Marktplaats on by default; Vinted, Leboncoin and Facebook opt-in. | The user chooses their own platform and account risk. |
| D4 | 2dehands/Marktplaats through their shared JSON API over plain HTTP. Vinted, Leboncoin and Facebook through Playwright with a real Chromium and a persistent profile per platform. Where the page fetches JSON, the source reads that response instead of scraping selectors. | One browser mechanism for the hard platforms; intercepted JSON breaks less often than CSS selectors. |
| D5 | On a block, CAPTCHA or expired session: skip that platform for this run, notify the user, no retry. | Fail soft and visibly; never escalate. |
| D6 | One Python module per platform exposing `search()`, registered in a plain dict. | Adding a platform is one file plus one line. No base class, no entry points. |
| D7 | Photo score from a local embedding model (DINOv2-small via `transformers`), cosine similarity, highest pair across all listing × reference photos. | Free, private, works offline; one good photo is enough. |
| D8 | Text bonus: user-defined keyword groups (brand, model, colour, …) with optional per-group weight, matched as case- and accent-insensitive substrings in title and description. `total = photo_score + Σ matched group weights`. | Strong text evidence (brand + model, or a bright distinctive colour) must lift a listing over the threshold even when the photo doesn't match. |
| D9 | Frame number found in the text: always notify. | Unambiguous evidence. |
| D10 | Two searches per platform: *near & broad* (whole bike category, within a radius, newest first) and *far & targeted* (model keywords, nationwide). | Vague listings are caught near home by photo; honest listings far away are caught by text. |
| D11 | First run backfills to the theft date; later runs only process unseen listing IDs. | No duplicate work, no duplicate notifications. |
| D12 | Listings without a usable location are kept, not dropped. | Missing a bike is worse than a false positive. |
| D13 | Notifications through ntfy (one HTTP POST, photo attached, link as click action). A random topic is generated at `init`. | Free, open source, self-hostable, no account, no extra dependency. |
| D14 | Config is a commented YAML file plus a folder of reference photos. Commands: `init`, `check`, `login`, `run`. | Technical users prefer a documented file over a wizard; `check` gives immediate feedback. |
| D15 | Polite behaviour fixed in code: one sequential pass, page cap per search, random pauses, normal user agent; `run` refuses to start within 12 h of the last successful run. | Protects the user's accounts and IP against a misconfigured cron. |
| D16 | One SQLite file with only `seen` and `runs`; rows older than 180 days are pruned. | Minimal data, no seller information, stdlib `sqlite3`. |
| D17 | `active_until` (default: theft date + 1 year) ends the search with one final notification. | Protects against forgotten cron jobs; the human decides when the bike is found. |
| D18 | Tests run on recorded fixtures and pure scoring logic; live checks only via `bikehound check`, never in CI. | Live tests in CI fail on datacenter IPs, not on real breakage. |
| D19 | Python ≥ 3.14; dependencies: `httpx`, `playwright`, `torch`, `transformers`, `pillow`, `pyyaml`. CLI with `argparse`, config validated with a dataclass. Tooling: `pytest`, `ruff`, `pyproject.toml`. | Most mature ecosystem for browser automation and vision models; no extra layers. |
| D20 | No background removal or bike cropping in v1. | Add only if backgrounds visibly distort scores in practice. |

## 3. Components

```
                     ┌──────────────────────────┐
  cron / systemd ───▶│ cli.py                   │  init · check · login · run
  docker run         └────────────┬─────────────┘
                                  │
          ┌───────────────────────┼─────────────────────────────┐
          ▼                       ▼                             ▼
 ┌─────────────────┐   ┌──────────────────────┐      ┌──────────────────┐
 │ config.py       │   │ sources/             │      │ store.py         │
 │ YAML → dataclass│   │  lrp.py  (2dehands,  │      │ SQLite: seen,    │
 │ + validation    │   │           marktplaats│      │ runs, pruning,   │
 └─────────────────┘   │  vinted.py           │      │ 12 h guard       │
                       │  leboncoin.py        │      └──────────────────┘
                       │  facebook.py         │
                       │  __init__.py: dict   │
                       └──────────┬───────────┘
                                  │ list[Listing]
                                  ▼
                       ┌──────────────────────┐      ┌──────────────────┐
                       │ match.py             │      │ notify.py        │
                       │ photo embeddings     │─────▶│ ntfy POST        │
                       │ + keyword bonus      │      │ (match / failure │
                       │ + frame number       │      │  / stopped)      │
                       └──────────────────────┘      └──────────────────┘
```

| Component | Responsibility |
|---|---|
| `cli.py` | Parses commands with `argparse` and runs the flow in section 4. `-c` selects the config file. |
| `config.py` | Loads `config.yaml` into a dataclass, applies defaults and fails with a clear message on missing or invalid fields. |
| `sources/<platform>.py` | `search(query) -> list[Listing]`. Split into fetching (HTTP or Playwright) and a pure `parse(raw) -> list[Listing]`. Raises a single `Blocked` exception on CAPTCHA, block or expired session. |
| `sources/__init__.py` | `SOURCES = {"2dehands": ..., "marktplaats": ..., ...}` and the `Listing` dataclass (id, platform, url, title, description, price, location, photo URLs, posted_at). |
| `match.py` | Loads the model, computes and caches reference embeddings (keyed by file hash), scores each listing: photo score, keyword bonus, frame-number hit. Returns the score and the reasons for it. |
| `notify.py` | Sends three message kinds to ntfy: possible match, platform failure, search stopped. |
| `store.py` | SQLite access: `seen` (platform, listing_id, first_seen, score, notified), `runs` (started_at, per-platform status). Pruning and the 12-hour guard. |

### Commands

| Command | What it does |
|---|---|
| `bikehound init` | Copies `config.example.yaml` to `config.yaml` with a random ntfy topic. |
| `bikehound check` | Validates the config, embeds the reference photos, sends a test notification and runs one small search per enabled platform. |
| `bikehound login facebook` | Opens a visible browser on the Facebook profile so the user can log in once. |
| `bikehound run` | The daily job. |

### Files on disk (all git-ignored)

```
config.yaml            the user's configuration
reference/             the user's photos of the bike
data/
  bikehound.sqlite     seen + runs
  embeddings/          cached reference embeddings
  profiles/<platform>/ Playwright browser profiles (contain session cookies)
```

With several bikes, each config file gets its own `data/` folder next to it.

## 4. Data flow: from listing to notification

1. **Guards.** If today is after `active_until`: send "stopped" once, exit. If the last successful
   run was less than 12 hours ago: exit.
2. **Prepare.** Load the config, load the model, and load or compute the reference embeddings.
3. **Search, platform by platform, sequentially.** For each enabled platform:
   - *near*: bike category, within `radius_km`, newest first;
   - *far*: each word of the `model` group (or the `brand` group if there is no model), no
     distance limit;
   - pages continue until a page has no unseen listings, the theft date is passed, or the
     page cap is reached;
   - on `Blocked`, record the failure, send a failure notification and continue with the next
     platform.
4. **Filter.** Drop listings already in `seen`. Where a listing has coordinates and the platform
   ignored the radius, drop listings beyond `radius_km` (near search only). Keep listings
   without a location.
5. **Score.** For each listing:
   - frame number in the text → match, done;
   - download photos into memory (HTTP, or through the Playwright context for browser sources),
     embed them, take the highest cosine similarity against any reference photo;
   - add the weight of each keyword group with at least one word found in title + description.
6. **Notify** every listing with `total ≥ threshold`: photo, platform, price, score, matched
   keywords, link.
7. **Record.** Write every processed listing to `seen` (with score and notified flag) and the
   run status to `runs`. Prune `seen` rows older than 180 days.

Listing photos and texts exist only in memory during steps 4–6.

## 5. Configuration model

```yaml
# config.yaml — one bike per file
bike:
  stolen_on: 2026-09-20
  active_until: 2027-09-20       # optional, default stolen_on + 1 year
  frame_number: "WXYZ12345"      # optional; a hit always notifies
  reference_dir: reference/      # side views with the whole frame + distinctive details

location:
  postcode: "9000"
  country: BE
  lat: 51.05
  lon: 3.72
  radius_km: 50

platforms: [2dehands, marktplaats]   # opt-in: vinted, leboncoin, facebook (see README warnings)

keywords:                        # any group name; words in every language the platforms use
  brand: { words: [cortina] }                                  # default weight 0.3
  model: { words: [e-u4, eu4, "e u4"] }                        # default weight 0.4
  color: { words: [felgroen, groen, green, vert], weight: 0.3 } # default 0.1, raised: rare colour

threshold: 0.75                  # placeholder, see open questions

ntfy:
  url: https://ntfy.sh/bikehound-3f9c…   # generated by `init`; the topic name is the secret
```

Default weights: `brand` 0.3, `model` 0.4, `color` 0.1, any other group 0.1.

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Platform changes its API or page structure | That source returns nothing or fails | Fetch/parse split, fixtures make repair quick; failures are reported to the user, not swallowed. A source that silently returns zero results is the dangerous case (see open questions). |
| Bot protection (Vinted, Leboncoin: Datadome) | Source blocked, sometimes for days | Real browser, persistent profile, home IP, low volume. When blocked: skip and notify. Accept lower coverage. |
| Headless browsers are easier to detect | More blocks on servers without a display | Document running headed (e.g. under `xvfb-run`) as an option; no stealth tricks. |
| Facebook account blocked | User loses their personal account | Opt-in, clear warning, one run a day, low page cap. The user decides which account to use. |
| Terms of service | Automated access is forbidden on several platforms | Personal use only, stated in the README; no circumvention; responsibility lies with the user. |
| Costs | — | No paid APIs. Compute is local CPU; volume is a few hundred listings a day. |
| Docker image size (`torch` + Chromium + model) | Multi-GB image, slow first pull | Accept for v1; ONNX Runtime instead of `torch` is the upgrade path. |
| `torch` wheels lag behind new Python versions | Install fails on the newest Python | Pin the supported version in `pyproject.toml` and the Docker image. |
| Image model sees "similar bike", not "my bike" | Many false positives for common models | Low threshold is intentional; notifications show the score and reasons. An LLM re-ranker is the upgrade path if volume becomes a burden. |
| ntfy.sh topics are public by name | Anyone who guesses the topic sees the notifications | Long random topic; self-hosting ntfy is documented. |
| Seller personal data | GDPR exposure | Only IDs and scores are stored; no texts, names or photos. |

## 7. Open questions

Tracked in [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md).
