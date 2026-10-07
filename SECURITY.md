# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use
[GitHub's private vulnerability reporting](https://github.com/wiebe-vandendriessche/bikehound/security/advisories/new)
for this repository.

## What counts

BikeHound runs on the user's own machine, so the main risks are about leaking what it keeps
there or sends out. For example:

- the ntfy topic leaking (anyone who knows it can read the notifications);
- data ending up outside `data/`, in logs, or in a commit;
- photos, descriptions or seller data being stored, or anything being sent anywhere, against the
  design (the gallery keeps only title, price, town, photo URL and score, locally);
- listing text breaking out of escaping in `data/matches.html` (script injection);
- a malicious page or response making BikeHound write files or run code.

A marketplace blocking BikeHound is not a security issue; open a normal issue for that.

## Supported versions

Only the latest version on `main` gets fixes.
