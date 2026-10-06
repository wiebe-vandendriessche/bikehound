# BikeHound architecture

Status: design agreed 2026-10-05 and implemented: config, store, notify (incl. first-run digest),
text and photo scoring, CLI (`init`, `check`, `run`), the 2dehands/Marktplaats source, the
browser helper, the Vinted source, the Facebook source (logged out, best effort, D24) and a
Dockerfile.

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
- Four marketplaces: 2dehands.be, Marktplaats.nl, Vinted, Facebook Marketplace (Leboncoin was
  planned and dropped, D25).
- Matching on photos (local image model) plus a text bonus for configured keywords.
- Push notifications through ntfy.
- One bike per config file.

### Deliberately out of scope

| Not included | Why |
|---|---|
| Hosted service, web UI, user accounts | Would make the maintainer run scrapers on behalf of others and hold their personal data. |
| Built-in scheduler or long-running daemon | Runs once a day; cron/systemd/Docker already schedule. |
| Plugin system for marketplaces | Four sources in one repo; new ones arrive as a pull request. |
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
| D2 | One-shot CLI (`bikehound run`), scheduled by the host; a Dockerfile as an alternative install (built locally, not published). | No daemon to keep alive; a home IP has the best chance against bot protection. |
| D3 | Four marketplaces in v1 (Leboncoin dropped, D25). 2dehands and Marktplaats on by default; Vinted and Facebook opt-in. | The user chooses their own platform and account risk. |
| D4 | 2dehands/Marktplaats through their shared JSON API over plain HTTP. Vinted and Facebook through Playwright with a real Chromium and a persistent profile per platform. Where the page fetches JSON, the source reads that response instead of scraping selectors. | One browser mechanism for the hard platforms; intercepted JSON breaks less often than CSS selectors. |
| D5 | On a block, CAPTCHA or expired session: skip that platform for this run, notify the user, no retry. | Fail soft and visibly; never escalate. |
| D6 | One Python module per platform exposing `search()`, registered in a plain dict. | Adding a platform is one file plus one line. No base class, no entry points. |
| D7 | Photo score from a local image model (SigLIP2-base via `transformers`, CPU-only torch) on the whole photo, cosine similarity, highest pair across the first 3 listing photos x all reference photos. Rescaled so the measured median of unrelated listings (0.55) maps to 0 and their 99th percentile (0.71) to 0.5. Default `threshold` 0.5. | Free, private, works offline; one good photo is enough. Chosen over DINOv2 by a measured bake-off (below). Rescaling keeps the keyword weights meaningful: `brand + model` (0.7) reaches the threshold, `color` alone does not, the photo alone only for about the closest 1% of listings. |
| D8 | Text bonus: user-defined keyword groups (brand, model, colour, …) with optional per-group weight, matched as case- and accent-insensitive substrings in title and description, except that a number never matches inside a longer number (`28` is not in `280`, `28.00` or `28.5`). `total = photo_score + Σ matched group weights`. | Strong text evidence (brand + model, or a bright distinctive colour) must lift a listing over the threshold even when the photo doesn't match. |
| D9 | Frame number found in the text: always notify. | Unambiguous evidence. |
| D10 | Two searches per platform: *near & broad* (bike subcategories only, within a radius, newest first) and *far & targeted* (model keywords, whole category, nationwide). Near runs only on platforms that accept the user's postcode (2dehands for BE, Marktplaats for NL). | Vague listings are caught near home by photo; honest listings far away are caught by text. A foreign postcode is silently ignored, which would turn near into a nationwide flood. |
| D11 | Paging stops once a page ends before `since`: the theft date on the first run, else the last successful run minus one day. Only unseen listing IDs are scored. Backfill is bounded by the page cap. | No duplicate work, no duplicate notifications. Platforms sort by *bump* date, so already-seen listings fill every page and "stop at a page with nothing new" never triggers. |
| D12 | Listings without a usable location are kept, not dropped. | Missing a bike is worse than a false positive. |
| D13 | Notifications through ntfy (one HTTP POST, photo attached, link as click action). A random topic is generated at `init`. | Free, open source, self-hostable, no account, no extra dependency. |
| D14 | Config is a commented YAML file plus a folder of reference photos. Commands: `init`, `check`, `run` (no `login`: no source needs an account, D23, D24). | Technical users prefer a documented file over a wizard; `check` gives immediate feedback. |
| D15 | Polite behaviour fixed in code: one sequential pass, page cap per search, random pauses, normal user agent; `run` refuses to start within 12 h of the last successful run. | Protects the user's accounts and IP against a misconfigured cron. |
| D16 | One SQLite file with only `seen` and `runs`; rows older than 180 days are pruned. | Minimal data, no seller information, stdlib `sqlite3`. |
| D17 | `active_until` (default: theft date + 1 year) ends the search with one final notification. | Protects against forgotten cron jobs; the human decides when the bike is found. |
| D18 | Tests run on recorded fixtures and pure scoring logic; live checks only via `bikehound check`, never in CI. | Live tests in CI fail on datacenter IPs, not on real breakage. |
| D19 | Python ≥ 3.14; dependencies: `httpx`, `playwright`, `torch`, `transformers`, `pillow`, `pyyaml`. CLI with `argparse`, config validated with a dataclass. Tooling: `pytest`, `ruff`, `pyproject.toml`. | Most mature ecosystem for browser automation and vision models; no extra layers. |
| D20 | No background removal or bike cropping. | Measured: a bike-detector crop added about 0.01 AUC on top of SigLIP2 while more than doubling CPU time per photo. |
| D21 | The first run sends one digest (all matches sorted by score, split into messages under 4000 bytes) instead of one push per match. | A backfill of a popular model produced 121 matches; ntfy.sh rate-limits after about 60 messages. |
| D22 | `since` and "first run" are tracked per platform (`platform_ok` table). A platform is marked ok only when it was searched without `Blocked`, and on its first run only once its digest is fully sent. | A platform blocked for days, or enabled later, catches up from its own last success instead of searching one day back. |
| D23 | Browser sources run on BikeHound's own logged-out profile; BikeHound never logs in to a user's personal account and never creates accounts. | Protects the user's own accounts; account creation is against platform terms (section 1). |
| D24 | Facebook logged out, best effort: one bikes page per price band (6) plus one text search per far word, in a fixed big-city area per country (`brussels`, `amsterdam`). No account, no login, no backfill, no radius. | A login needs an account and identity checks; logged out, one page is a stale 24-listing sample, but the price-band union covers several days. Partial coverage beats none (section 1). |
| D25 | No Leboncoin source. | Spike on 2026-10-06: a fresh logged-out profile, headless and headed, gets a Datadome CAPTCHA (HTTP 403) on the search and category pages; after a few loads the homepage is blocked too. Getting through needs CAPTCHA solving or stealth (section 1). |
| D26 | Location is `postcode`, `country` and `radius_km`; no coordinates in the config and no client-side radius filter. | Only 2dehands and Marktplaats take a radius, and they apply it server-side; Vinted and Facebook carry no coordinates. `lat`/`lon` were only needed for Leboncoin's search across the border (D25). Old configs with `lat`/`lon` still load. |

## 3. Components

```
                     ┌──────────────────────────┐
  cron / systemd ───▶│ cli.py                   │  init · check · run
  docker run         └────────────┬─────────────┘
                                  │
          ┌───────────────────────┼─────────────────────────────┐
          ▼                       ▼                             ▼
 ┌─────────────────┐   ┌──────────────────────┐      ┌──────────────────┐
 │ config.py       │   │ sources/             │      │ store.py         │
 │ YAML → dataclass│   │  lrp.py  (2dehands,  │      │ SQLite: seen,    │
 │ + validation    │   │           marktplaats│      │ runs, pruning,   │
 └─────────────────┘   │  vinted.py           │      │ 12 h guard       │
                       │  facebook.py         │      └──────────────────┘
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
   run was less than 12 hours ago: exit. `since` and "first run" are then taken per platform
   (D22).
2. **Prepare.** Load the config, load the model, and load or compute the reference embeddings.
3. **Search, platform by platform, sequentially.** For each enabled platform:
   - *near*: bike category, within `radius_km`, newest first;
   - *far*: each word of the `model` group (or the `brand` group if there is no model), no
     distance limit;
   - pages continue until a page ends before `since` (D11), a page comes back short, or the
     page cap is reached;
   - on `Blocked`, record the failure, send a failure notification and continue with the next
     platform.
4. **Filter.** Drop listings already in `seen`. The radius is applied by the platforms that
   support one; listings without a location are kept.
5. **Score.** For each listing:
   - frame number in the text → match, done;
   - download photos into memory (HTTP, or through the Playwright context for browser sources),
     embed them, take the highest cosine similarity against any reference photo;
   - add the weight of each keyword group with at least one word found in title + description.
6. **Notify** every listing with `total ≥ threshold`: photo, platform, price, score, matched
   keywords, link. On the first run all matches go out as a digest instead (D21). A notification that fails (e.g. ntfy.sh rate limit during a large first-run
   backfill) leaves the listing unrecorded, so the next run retries it.
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
  radius_km: 50

platforms: [2dehands, marktplaats]   # opt-in: vinted, facebook (see README warnings)

keywords:                        # any group name; words in every language the platforms use
  brand: { words: [cortina] }                                  # default weight 0.3
  model: { words: [e-u4, eu4, "e u4"] }                        # default weight 0.4
  color: { words: [felgroen, groen, green, vert], weight: 0.3 } # default 0.1, raised: rare colour

threshold: 0.5

ntfy:
  url: https://ntfy.sh/bikehound-3f9c…   # generated by `init`; the topic name is the secret
```

Default weights: `brand` 0.3, `model` 0.4, `color` 0.1, any other group 0.1.

### 2dehands / Marktplaats (`sources/lrp.py`)

Both sites run the same JSON API (`/lrp/api/search`) with the same category IDs. Facts measured
on 2026-10-05:

- The listing `date` is the bump date (`Vandaag`, `Gisteren`, `Eergisteren`, `2 okt 26`), not
  the post date. Sorting `SORT_INDEX DECREASING` orders by it. Bump date >= post date, so the
  stop rule never skips a listing posted after the theft.
- Subcategory filter: repeated `l2CategoryIds=` (the singular `l2CategoryId` is ignored).
- Hard pagination cap: `offset + limit <= 5000`. Bike listings within 50 km bumped per day:
  about 1000 around Gent, about 3000 around Utrecht. Near backfill therefore reaches roughly
  10 days on 2dehands and 1.5 days on Marktplaats.
- Search results cut the description at about 200 characters. Keywords or a frame number after
  that point are missed; accepted for v1 (a detail fetch per listing would cost hundreds of
  requests a day).
- Zero listings on the first near page is treated as `Blocked`: a bike category within a radius
  is never empty, so it signals breakage, not a quiet day.

### Vinted (`sources/vinted.py`)

Facts measured on vinted.be on 2026-10-06, logged out, headless Chromium, home IP:

- Protection: Cloudflare (`cf_clearance`) and Datadome. A fresh, logged-out profile gets
  through headless, and receives an anonymous `access_token_web`. No account needed.
- The JSON API (`/api/v2/catalog/items`) answers 403 with a block page to an in-page `fetch()`.
  The catalog page itself is server-rendered and makes no JSON call for its items. So the source
  navigates catalog pages like a visitor and parses the HTML (deviation from D4's JSON
  preference: there is no JSON to read).
- Cards carry stable `data-testid="product-item-id-<id>--..."` attributes: link (`--overlay-link`,
  whose `title` also holds brand, condition and price), photo (`--image--img`, 310x430 webp),
  price (`--price-text`). No date, no location, no description, no seller data. The trailing
  prices are stripped from the title, so number keywords never hit on a price.
- Location: the item page shows one (`data-testid="seller-location"`) only for business sellers
  (those with a legal registration); none of 12 sampled private listings had one. So Vinted
  listings carry no location, and fetching item pages to find one is not worth the requests.
  vinted.be also shows listings from other countries (seen: the Netherlands).
- Photos: the CDN (`images1.vinted.net`) serves plain `httpx`, so the shared photo download works.
- 96 items per page, hard cap of 10 pages (page 11 is empty).
- Categories: 4345 bikes and 4346 e-bikes, each including its subcategories (checked: the same
  ids as querying all leaves). Volume for 960 items: 4345 reaches 8 weeks back (about 17 a day),
  4346 12 months, 4347 kids' bikes only 20 hours (about 1000 a day). Near therefore uses 4345 +
  4346; kids' bikes are left out.
- No radius search (shipping marketplace): near is the whole country's bike categories, newest
  first. The domain follows `location.country` (`www.vinted.be`, `www.vinted.nl`).
- Far search: model (or brand) words within 4333 cycling, so brand words that are also shoe
  names (Gazelle) do not flood it.
- No dates on cards, but item ids are one global counter: about 10.8M a day (19 h), 11.5M
  (8 weeks), 8.3M (12-month average). `since` becomes an id cutoff, newest id on the first near
  page minus `days x 8M`; the low rate errs toward reading further back.
- "Newest first" is ordered by bump, like 2dehands: on one page 28 of 95 neighbours were out of
  id order, with a 4-week-old listing among 3-day-old ones. A bumped listing keeps its old id,
  so each listing below the cutoff is dropped, but paging stops only at a page with nothing above
  it (as D11). Zero cards on the first near page raises `Blocked`.

### Facebook Marketplace (`sources/facebook.py`), logged out

Spikes on 2026-10-06, fresh profile, logged out, headless, home IP. A logged-in source was
dropped: every maintained open-source tool that pages through Marketplace logs in, and a new
account had to pass a webcam identity check. Decision D24: logged out, best effort.

- The bikes category (`/marketplace/<city>/bicycles?sortBy=creation_time_descend`) loads without
  login (HTTP 200). A cookie dialog appears; the data is in the server HTML regardless.
- The HTML embeds 24 listings as Relay JSON (`GroupCommerceProductItem`): id, title, price,
  `creation_time`, city (`reverse_geocode`), photo URL. No description, no coordinates.
- Scrolling loads nothing more logged out (no GraphQL requests), so one URL gives 24 listings.
- **The logged-out feed is a cached sample, not the newest listings.** The same search split
  into three price bands returned 25 listings newer than the main feed's oldest that the main
  feed did not show, and listings up to 4 hours newer than its newest. Reloading returned the
  identical 24.
- Location only by city slug in the path. `radius` is ignored (10 km and the default 65 km
  returned the same listings); `latitude`/`longitude` query parameters are ignored too.
- What works: text search (`/marketplace/<city>/search?query=...`) returns 24 results; the
  photo CDN serves plain `httpx`; 9 loads in a row hit no login wall.
- **Price bands fill the gap.** One page per band (`minPrice`/`maxPrice`: 0-50, 50-100,
  100-200, 200-400, 400-800, 800+) gives 24 listings each; around Brussels every band reached 2
  to 7 days back, and the union held 131 distinct listings against 24 on the plain page. A daily
  run (yesterday onward) found 50 listings in 7 page loads (35 s).
- **The area is Facebook's, not the user's.** Only big-city slugs exist (`brussels`,
  `amsterdam`); others (`leuven`, `ghent`, `antwerp`, `bruges`) silently return San Francisco
  listings, and the numeric city ids that listings carry return the Brussels results. So the
  source uses one verified slug per country and has no location setting. Listings came from
  across Flanders and Brussels (Kortrijk to Antwerpen to Namur), wider than `radius_km`.
- Far text searches need no bands: a search for a brand reached 10 days back on one page.
- 14 loads in a row hit no login wall. Reports say Facebook has been sending anonymous visitors
  to a login page since mid-2026; then every band comes back empty, which raises `Blocked`.

### Leboncoin (dropped, D25)

Spike on 2026-10-06, home IP, fresh profiles, logged out. The goal was a search across the
border: the French part of the user's radius (for example Kortrijk + 50 km reaches Lille).

- Headless: `/recherche?category=55&sort=time&order=desc` answered HTTP 403, Datadome
  (`x-datadome: protected`, a `captcha-delivery` page).
- Headed, new profile: the homepage loaded (HTTP 200), the search page right after it 403 with
  the CAPTCHA. `/c/velos` the same.
- After about 8 page loads in total, even the homepage answered 403 on a new profile: the IP
  was flagged.
- Not tried, as out of scope: CAPTCHA solving, stealth plugins, proxies, an account.

### Photo score bake-off (2026-10-05)

Reference: the catalogue photo of a Rock Machine Manhattan 40-27 (green hardtail MTB, white
background). Test set: 75 listings showing a green hardtail MTB (labelled by eye from searches
such as "groene mountainbike") against 997 near listings around Gent. 2dehands/Marktplaats
search results carry one photo per listing.

| Pipeline | AUC | Recall in top 1% | Recall in top 5% | CPU per photo |
|---|---|---|---|---|
| Whole photo, DINOv2-small CLS (first version) | 0.69 | 9% | 20% | 154 ms |
| Bike crop (torchvision Faster R-CNN MobileNet), DINOv2 CLS | 0.69 | 9% | 21% | + 453 ms |
| Whole photo, **SigLIP2-base** (chosen) | 0.94 | 20% | 71% | 336 ms |
| Bike crop, SigLIP2-base | 0.95 | 25% | 69% | 336 + 453 ms |
| Hue histogram of the crop | 0.75 | 0% | 7% | 9 ms |
| Crop, SigLIP2 + 0.1 x hue histogram | 0.96 | 25% | 71% | |

- The embedding model was the problem, not the background. DINOv2 ranked clean side views of
  any bike highest (mostly road bikes); SigLIP2's top 18 negatives were all hardtail MTBs, three
  of them lime green ones that were not labelled, so its recall is an underestimate.
- Recall is for "a bike like mine" (same type and colour). No photo of the actual bike exists, so
  recall on the real bike is unmeasured; a photo of the actual bike should score higher.
- Caveat: positives came from text searches (mostly Marktplaats), negatives from 2dehands.
- Cost: a first run of ~5000 listings went from 11 to 21 minutes (measured); one-time model
  download of 1.5 GB (Apache-2.0).
- Not tried: YOLO or SAM masks (cropping barely helped), DINOv3 (gated licence), fine-tuning.

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Platform changes its API or page structure | That source returns nothing or fails | Fetch/parse split, fixtures make repair quick; failures are reported to the user, not swallowed. A source that silently returns zero results is the dangerous case (see open questions). |
| Bot protection (Vinted: Datadome) | Source blocked, sometimes for days | Real browser, persistent profile, home IP, low volume. When blocked: skip and notify. Accept lower coverage. |
| Headless browsers are easier to detect | More blocks on servers without a display | Document running headed (e.g. under `xvfb-run`) as an option; no stealth tricks. |
| Facebook closes anonymous access | Facebook source stops | No account is used (D24). All bands empty raises `Blocked`: the user gets a failure notification, the other sources continue. |
| Terms of service | Automated access is forbidden on several platforms | Personal use only, stated in the README; no circumvention; responsibility lies with the user. |
| Costs | — | No paid APIs. Compute is local CPU; volume is a few hundred listings a day. |
| Docker image size (`torch` + Chromium + model) | Multi-GB image, slow first pull | Accept for v1; ONNX Runtime instead of `torch` is the upgrade path. |
| `torch` wheels lag behind new Python versions | Install fails on the newest Python | Pin the supported version in `pyproject.toml` and the Docker image. |
| Image model sees "similar bike", not "my bike" | Many false positives for common models | Low threshold is intentional; notifications show the score and reasons. An LLM re-ranker is the upgrade path if volume becomes a burden. |
| ntfy.sh topics are public by name | Anyone who guesses the topic sees the notifications | Long random topic; self-hosting ntfy is documented. |
| Seller personal data | GDPR exposure | Only IDs and scores are stored; no texts, names or photos. |

## 7. Open questions

Tracked in [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md).
