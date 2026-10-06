# Open questions

Decisions still to be made for BikeHound. Context and decided parts: [ARCHITECTURE.md](ARCHITECTURE.md).
When a question is settled, move the outcome into the decisions table there and delete it here.

## 2. Silent breakage

A source whose page structure changed may return zero listings without raising an error. That
looks the same as "nothing new today" and is the most likely way to miss a bike.

- **Decided for 2dehands/Marktplaats:** zero results on the first near page raises `Blocked`.
- **Decided for Vinted:** same rule. The newest bikes in a whole country are never empty.
- **To check:** whether that holds for Leboncoin and Facebook.

## 3. Facebook login with Docker

`bikehound login facebook` needs a visible browser; a container has no display.

- **A.** Log in with a local install (`uv tool install`), then mount the profile folder into
  the container.
- **B.** Run the login command in the container with a forwarded display (X11 or noVNC).
- **Leaning:** A, documentation only, no extra code.

## 4. Location per platform

Each platform takes a location differently (postcode, coordinates, profile setting) and not all
return coordinates per listing.

- **To find out:** per platform, how to pass the location and radius, and whether listings carry
  coordinates.
- **Known for 2dehands/Marktplaats:** `postcode` + `distanceMeters`, applied server-side; a
  postcode from the other country is silently ignored. Listings carry coordinates.
- **Known for Vinted:** no location search and no location on catalog cards; near is
  country-wide (see ARCHITECTURE.md).
- **Decides:** where the client-side radius filter applies, and whether `lat`/`lon` in the
  config can be dropped in favour of postcode only.

## 5. Page caps and backfill depth

- **To find out:** per platform, how many results a search returns and how far back pagination
  goes.
- **Decides:** the page cap per search (politeness) and how far the first run can backfill to
  the theft date.
- **Known for 2dehands/Marktplaats:** hard cap of 5000 results per search; near cap 50 pages of
  100, far cap 10 pages.
- **Known for Vinted:** hard cap of 10 pages of 96; near reads all 10 (about 8 weeks of bikes on
  vinted.be), far cap 2 pages.

## 6. Far search volume

The far search uses model words, falling back to brand words when no model is configured. A
nationwide brand-only search for a common brand (e.g. Gazelle in the Netherlands) may return
hundreds of new listings a day.

- **Options:** keep the fallback and accept the CPU time, or require at least one model word for
  the far search.
- **Decided by:** measuring the daily volume for a common brand.

## 8. README update

Bring the README in line with the design: opt-in platforms, `active_until`, Python ≥ 3.14,
install steps, ntfy setup. Follow-up after the design phase.
