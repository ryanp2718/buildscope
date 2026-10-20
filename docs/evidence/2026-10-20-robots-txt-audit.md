# Audit: robots.txt as RFC 9309 reads it

Date:      2026-10-20
Produced:  `python spikes/robots_audit.py` (one robots.txt request per host, 2026-10-20; every
           figure below). No model calls; cost $0.00.
Inputs:    every `manifest.csv` under `data/` (1,658 recorded requests over 408 hosts, 2026-09-20
           to 2026-10-20)
Outputs:   `data/robots_audit/` (private): each host's robots.txt as fetched, `hosts.json`,
           `rows.csv` (one row per recorded request, judged three ways)
Status:    Current. The fix is in `permits.capture`; the outcomes it moves are in the
           [portal population pre-registration](2026-10-04-portal-population-preregistration.md)'s
           interim funnel.

## Question

Did the crawler fetch only what each host's robots.txt allows it, read as RFC 9309 specifies, and
which recorded outcomes change if it did not?

## What was wrong

Until 2026-10-20, `permits.capture` read robots.txt with Python's standard-library parser and
fetched it with the crawler's page headers. Four defects:

- **A rule lost its query.** `Disallow: /?` (Google's, meaning root URLs with a query) was read as
  `Disallow: /`, refusing all of www.google.com, reCAPTCHA's script included.
- **Wildcards were literal.** `*` and `$` matched nothing, so Bay County's `Allow: /Home$` list
  followed by `Disallow: /` allowed every path.
- **A byte-order mark hid the first line.** SmartGov's robots.txt starts with one, and its first
  line is its only `User-agent: *`, so its rules were never read.
- **robots.txt was asked for as HTML.** LOGIS answered `Accept: text/html` with 406, and any
  failure was read as "no rules". RFC 9309 reads a 4xx as no rules, but a 5xx or no answer as
  "assume everything is disallowed".

`capture` now uses Protego, Scrapy's RFC 9309 parser. It asks for robots.txt as text and strips a
byte-order mark. A 5xx means nothing is fetched. If robots.txt gets no answer at all, nothing is
fetched either, and the row records a transport failure, so a host that is down is not counted as
one that refused. `tests/test_capture.py` covers each case.

## Method

Each host's robots.txt was fetched once, as `capture` now fetches it. Every recorded request was
judged three ways: as recorded at the time; by the old parser on today's file; under RFC 9309 on
today's file. Where the old parser also refuses a request today, the file has changed since, or the
old Accept header got a different answer at the time. Only requests that a server answered count as
fetched.

## Results

| | requests | hosts |
|---|---:|---:|
| fetched | 1,527 | |
| fetched, but a rule in today's robots.txt disallows it | 59 | 9 |
| of which the old parser allows it today too (its error) | 38 | 7 |
| refused for robots.txt | 24 | |
| refused, but RFC 9309 allows it today | 1 | 1 |

| host | requests | cause | effect |
|---|---:|---|---|
| aca-oregon.accela.com | 18 | today: `Disallow: /`; the old parser refuses it too | v2's held-out Oregon portal, fetched 2026-09-20 to 09-27. The file has changed since, or answered differently; not decidable now |
| epermits.logis.org | 16 | `Disallow: /`, read as no rules after a 406 | Apple Valley: robots.txt disallows |
| ci-banning-ca.smartgovcommunity.com | 11 | `Disallow: /ApplicationPublic/`, hidden by a byte-order mark | Banning: robots.txt disallows |
| ci-maricopa-az.smartgovcommunity.com | 4 | the same | Maricopa: robots.txt disallows |
| epermits.nashville.gov | 3 | today: `Disallow: /`; the old parser refuses it too | Nashville: robots.txt disallows |
| portal.baycountyfl.gov | 3 | only `/Home$`-style paths allowed | Bay County: robots.txt disallows |
| fasttrack.ocfl.net | 2 | only `/OnlineServices/Default.aspx` allowed | Orange County FL: robots.txt disallows |
| sanantonio.gov, knoxcounty.org | 2 | one page each, read while locating portals | none |

The one wrong refusal (Millbrae's eProcess360) changes nothing: the owner found that portal to be
login only on 2026-10-20. The eight self-hosted EnerGov portals stay robots.txt disallows, because
Telerik's CDN disallows every agent under either parser. reCAPTCHA's script is allowed, so the
searches behind it count as blocked by a bot check, not as robots.txt disallows.

The 23 pages saved from Apple Valley, Banning and Maricopa were deleted on 2026-10-20, at the
owner's decision. Their manifest rows are kept as the record of each request.

## What this does not establish

- **Today's files, not the files at the time.** A host that tightened its robots.txt since looks
  like a violation here, and one that loosened it does not.
- **Page-level only.** The manifest records each page, not the scripts and data calls a browser
  page makes. Requests the browser held back for robots.txt are counted on the page's row, but the
  ones it sent are not listed. Browser sessions before 2026-10-20 used the old parser for their
  sub-requests too.
