# Open questions

Decisions still to be made for BikeHound. Context and decided parts: [ARCHITECTURE.md](ARCHITECTURE.md).
When a question is settled, move the outcome into the decisions table there and delete it here.

## 1. Threshold and weight scale

Cosine similarities between *any* two bike photos are already fairly high, so the range of the
photo score is unknown until it is measured on real photos.

- **Must hold:** `brand + model` alone reaches the default threshold; `color` alone does not
  (unless the user raises its weight). With the current default weights (0.3 + 0.4) that implies a
  threshold ≤ 0.7, which may be too low for photos.
- **Options:** rescale the photo score (e.g. map the measured "different bike" baseline to 0),
  or scale the default weights to the measured threshold.
- **Decided by:** a small measurement with same-bike / different-bike photo pairs.

## 2. Silent breakage

A source whose page structure changed may return zero listings without raising an error. That
looks the same as "nothing new today" and is the most likely way to miss a bike.

- **Candidate:** treat zero results on the *near* search as a failure and notify, since a bike
  category within 50 km is never empty.
- **To check:** whether that holds for every platform (Vinted and Facebook may be sparse).

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
- **Decides:** where the client-side radius filter applies, and whether `lat`/`lon` in the
  config can be dropped in favour of postcode only.

## 5. Page caps and backfill depth

- **To find out:** per platform, how many results a search returns and how far back pagination
  goes.
- **Decides:** the page cap per search (politeness) and how far the first run can backfill to
  the theft date.

## 6. Far search volume

The far search uses model words, falling back to brand words when no model is configured. A
nationwide brand-only search for a common brand (e.g. Gazelle in the Netherlands) may return
hundreds of new listings a day.

- **Options:** keep the fallback and accept the CPU time, or require at least one model word for
  the far search.
- **Decided by:** measuring the daily volume for a common brand.

## 7. Background cropping

No bike detection or background removal in v1 (D20). Revisit if real-world false positives are
driven by similar backgrounds (same street, same wall) instead of similar bikes.

## 8. README update

Bring the README in line with the design: opt-in platforms, `active_until`, Python ≥ 3.14,
install steps, ntfy setup. Follow-up after the design phase.
