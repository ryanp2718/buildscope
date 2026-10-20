# Pre-registration: the portal population run

Date:      2026-10-04
Produced:  Written by hand. The draw is `python spikes/population_draw.py`; the interim funnel is
           `python spikes/population_probe.py --funnel` after `spikes/population_links.py`. No model
           calls; cost $0.00.
Inputs:    `data/frame/bps_frame.csv` (Census BPS, last 12 months); CISA's .gov domain registry
           (fetched 2026-10-04 through `permits.capture`);
           [agent run pre-registration](2026-10-01-agent-run-preregistration.md) (replaced; its
           confirmed choices carry over); [v2 run results](2026-10-01-v2-run-results.md)
Outputs:   `data/population/` (private): `draw.csv`, `portals.csv`, `sites.csv`, `links.json`,
           `probe.json`, `manual/`, `corpus/`. Later the run's records and a results report that
           cites this one.
Status:    **Draft.** The sample design (the cap, the Accela exception, the weighting, the two-page
           minimum and the take-all stratum) was approved by the owner on 2026-10-04. Changed by the
           owner on 2026-10-05 to save the owner's time: which portals are saved by hand,
           model-assisted checks of parser references, and a cap on the review after scoring.
           On 2026-10-20 the owner approved taking the owner out of the reference check, the
           browser's pacing, and applying robots.txt to every host a page loads from. The rest is
           for review. Nothing paid runs until the sections under "To be written before any paid
           call" are written and approved.

## Why this run

The v2 run and the agent-run draft use five portals between them: four Accela and St. Johns'
WATS. The repo's own Accela parser already reads every Accela tenancy, so those portals are where generating
an extractor matters least. Decided 2026-10-03: the unit of analysis is the portal, drawn from the
portals that actually issue US housing permits, and the question is what a trusted extractor costs
on them.

## Questions

1. **Headline: cost per trusted extractor**, per product and weighted to the population. A trusted
   extractor passes the check and matches the reference. Compared: a strong model one-shot against
   cheap models with the check and a repair loop.
2. **Delivery rate and wrong-but-accepted rate** for each approach: how often it hands over an
   extractor at all, and how often the check accepts a wrong one.
3. **Repair loop against resampling** at the same spend, paired by portal.

Secondary: the agent against the scripted loop; the Clark hint comparison; whether a reference
checked by a Claude model favours the Claude arm, measured where the reference is the portal's own
export (owner's point, 2026-10-20; see "Without the owner's review"). Descriptive: the
funnel, the share of offices and of housing units whose permits a polite crawler can reach.

## The population and the draw

**Frame.** The 1,000 permit offices with the most units in the BPS's last 12 months: 71.9% of US
permitted units, cut at 266 units. Ties at the cut are broken by state and BPS id.

**Order.** All 1,000 shuffled once with seed 20261003 (`data/population/draw.csv`). Offices are
located, classified and sampled in that order, so no portal is picked for being convenient. An
office whose portal is already a target (Clark, St. Johns, Santa Barbara, Polk, Oregon) is recorded
and skipped.

**Locating.** The office's own website is the source: whatever it links to as its permit search is
the portal, by the office's own account. The site comes from the .gov registry, matched on the
government's name, type and state, or by hand where the registry has none (`sites.csv`, column
`source`). `population_links.py` reads the home page, the site map and up to 3 of the office's own
permit pages, and lists every link that names a known vendor or reads like a permit search; the
links are reviewed by hand into `portals.csv`. Where the crawl reaches an office's permit pages
but not the portal, it is run again from the deepest of them (`--page`, a second hop). Web search
is the fallback only when the office's site cannot be read, or its pages build the portal link in
a script, and the row says so. Offices 1-80 were first located by web search and then by
the site crawl for the misses; the crawl found 17 portals the search had not.

**Outcomes**, one per office: answered the crawler (the portal's start page responded without a
block; whether it has a usable list is settled at onboarding), blocked (401, 403, 429 or a bot
check), robots_disallow,
unreachable (no connection from this network), login only, lookup only (no list of a date range's
permits: records are found by number, address or text, and the dates are only in each record), PDF
reports only, no online search, vendor named but no address found, not located. An outcome found
later that holds whoever fetches the portal replaces the probe's: lookup only, PDF reports only,
login only or no online search found by the owner in a browser, and login only, lookup only or no
online search found at onboarding by the crawler or its browser. A robots.txt refusal or a CAPTCHA
found at onboarding replaces it too, but binds only a crawler.

**Open data** (owner's point, 2026-10-04). An office whose government publishes its permits as a
dataset needs no extractor; a pipeline downloads it. New York City's DOB NOW finds one property at
a time, but the city publishes its approved permits as open data. Without this outcome such an
office counts as uncovered, and coverage looks worse than a real pipeline would get.

- **What counts.** The dataset is published by the office's own government. It is free and needs
  no login. It is machine-readable, with one row per building permit and an issue date. It holds
  permits issued in August 2026, the search rule's window. Monthly totals and PDF reports do not
  count.
- **How it is found** (`spikes/population_open_data.py`). The same steps run for every office in
  the sample:
  1. The data portals the office's own saved pages link to, each searched through its own catalog
     (Socrata, CKAN or ArcGIS Hub).
  2. data.gov's catalog, which harvests city and county portals. Its search does not read the
     publisher, so every dataset it returns for building or construction permits is matched to
     offices by the publisher's name.
  3. Web search, only for an office whose own site cannot be read, as for locating.

  Hits are reviewed by hand. Each dataset is then queried, through the same polite crawler, for
  its count of permits issued in August 2026. An office missed by all three steps is not counted,
  so the open-data share is a lower bound.
- **How it is counted.** Open data takes precedence: an office that qualifies is counted as open
  data, and its portal outcome is still recorded beside it. A pipeline would download the dataset
  instead of paying a model to read the portal, so an extractor gets no credit for that office's
  coverage.
- **What it does not change.** An open-data office's portal stays in the sample under the same
  rules as any other portal, and is scored the same way. Open data changes only the funnel and the
  pipeline view's weights (see Weighting), and gives a second check of the reference (see
  Checking the reference).
- **Found (2026-10-04):** 18 offices, all with August 2026 permits in their dataset:
  - NYC's five boroughs (DOB NOW: Build, filtered by borough)
  - Los Angeles, San Francisco, Austin, Seattle, Philadelphia, Denver, Nashville, Raleigh
  - Mecklenburg, Miami-Dade, Baltimore, Everett and Tempe

  Turned down, with the reason kept in `open_data.csv`:
  - **Stale:** Dallas (last updated 2020) and Phoenix (2023).
  - **Monthly totals only:** Houston.
  - **No issue date:** Fort Worth.
  - **API disallowed by robots.txt:** Cary.
  - **Retired platform:** Omaha (Accela's CivicData, end of life 30 June 2026).
  - **Published by a state or regional body:** Sussex County DE and Tumwater.
  - **Unverified:** San Jose. Its file's redirect to S3 answers 403 to the crawler.

**Interim funnel (2026-10-20)**, estimated for the 1,000 largest offices from offices 1-150 and the
take-all stratum, design-weighted, before onboarding settles which portals are usable. Since
2026-10-04, onboarding has moved portals that answered the crawler to the outcome any visitor
meets:
- **Login only:** three Accela portals (Fresno, Santa Rosa, Avondale), the three Cityworks
  portals, the seven offices on MGO Connect and three eTRAKiT portals.
- **Lookup only:** the three BS&A portals, Frisco's eTRAKiT, CivicGov, Cherokee County's CityView,
  Munis, Londonderry's eSuite, and the own systems of Durham, Miami-Dade and Stark County.
- **No online search:** St. Charles, whose eSuite search holds no building permits.

Searches behind a CAPTCHA moved to blocked (Citizenserve, SagesGov). Fourteen portals moved to
robots.txt disallows: the eight EnerGov portals on offices' own servers, which need a script CDN,
and six found by the [robots.txt audit](2026-10-20-robots-txt-audit.md) (SmartGov at Banning and
Maricopa, LOGIS, Bay County's CityView, Orange County FL and Nashville). The owner's browser
checks of 2026-10-20 moved Surf City, Valdosta, Forney and Millbrae from blocked or robots.txt
disallows. The report gives the final funnel.

| outcome | offices (estimated) | share of units |
|---|---:|---:|
| answered the crawler | 172 | 26.8% |
| not located | 204 | 13.8% |
| open data | 47 | 12.3% |
| login only | 111 | 11.0% |
| robots.txt disallows | 117 | 9.7% |
| blocked (403 or a bot check) | 96 | 6.8% |
| lookup only | 71 | 5.8% |
| unreachable from this network | 33 | 5.0% |
| vendor named, no address | 55 | 3.9% |
| no online search | 74 | 2.9% |
| PDF reports only | 20 | 2.0% |

Open data moves 12.3% of units. Without it, portals that answered the crawler hold 31.1% and blocked
ones 12.5%. With it, 39.1% of units sit with an office whose portal answered the crawler or that
publishes its permits as a dataset. Answering is an upper bound on what a pipeline can read: a
portal that answered may still have no usable list, which onboarding settles. Harris County's and
Miami-Dade's searches are lookups. No office carries more than 2.0% of these units. The largest are Denton, Buckeye, Los Angeles, Harris
County and Fayetteville.

Blocking follows the vendor. Tyler EnerGov on Tyler's hosting returned 403 on 6 of 6. The 8
EnerGov offices that run it on their own servers answered, but none can be rendered under
robots.txt: each loads EnerGov's interface library from Telerik's CDN, whose robots.txt disallows
every agent (checked 2026-10-20). All 6 OpenGov portals and MyGov's
`public.mygov.us` disallow crawlers in robots.txt; MyGov's MGO Connect does not, but its permit
search asks for a sign-in in all seven of its jurisdictions in the sample. iWorQ returned
403 on 3 of 3. Citizenserve's search and public reports, and SagesGov's search, submit only with
a reCAPTCHA token (3 of 3, 1 of 1). SmartGov's robots.txt disallows its search on both portals
reached, and LOGIS's disallows its whole host. BS&A's record search needs a number, name, address
or parcel (3 of 3).

Behind the access, the owner's browser checks found more (2026-10-04):
- **MyGov's `public.mygov.us`** is the permit application only at Mansfield and Midlothian. Both
  publish their permits as PDF reports.
- **iWorQ at Santa Fe TX** searches by permit number, parcel address or text, with no date filter.
  Its list shows type and status only, so it is lookup only.
- **The last four, one per product (2026-10-20), none with a usable list:**
  - Surf City NC (OpenGov) is lookup only. Its search (linked from no menu) finds records by
    location or by text in a record's name or number, with no date filter, and shows only each
    record's name or number.
  - Valdosta GA (iWorQ) is login only: the permit search asks for an access number, and the
    portal's instructions say the search behind it is by record, as at Santa Fe.
  - Forney TX (`public.mygov.us`) has no online search: the portal offers only application pages,
    and the city's permit reports stop at March 2020 (confirmed by the crawler).
  - Millbrae CA (eProcess360) is login only: the portal opens on its sign-in.

**Concentration** (owner's point, 2026-10-04). Four offices hold 27.6% of offices 1-150's
units: Harris County (10.1%, its own system), Fort Worth (7.2%), Manatee County (7.1%) and
Oklahoma City (3.3%), the last three on Accela. The draw took 3 of the frame's 4 largest offices,
about a 1-in-85 chance; in the frame those 3 are 3.7% of units. Weighted by units, the 150
offices count as about 36 offices of equal size (Kish effective sample size). The take-all
stratum below answers this. Harris County's public search turned out to be a lookup by project
number, so it fails the usability rule and no extractor result rests on it. Fort Worth's Accela
search is usable and in the sample.

## The sample

**Usable** means a public search returns a list of records under the search rule below. It is
settled for each portal when it is onboarded.

**Two groups, filled in draw order:**

- **Accela: the first 10 to 12 usable Accela portals, with no cap.** Accela tenancies differ in
  template (column sets and order; Clark and Santa Barbara behaved differently in v2), and that
  variation within one product is what this group measures.
- **Every other product: at most 3 tested portals per product**, the first usable ones in draw
  order. A city's own system is a product of its own. Development portals do not count toward the
  cap. A portal past the cap is recorded as "capped" and not onboarded. Portals on one product
  mostly share a template, so the cap spends the run on more layouts instead of more copies of one.

An office counts under the system it now links as its permit portal. Hemet moved from eTRAKiT to
EnerGov on 2026-08-10 and still links eTRAKiT for applications made before then; it counts as
EnerGov, and its old eTRAKiT takes no eTRAKiT place.

**A portal needs at least 2 result pages under the search rule to be usable** (approved by the
owner on 2026-10-04). Pages 2 onward are what catch an extractor that hard-codes page 1.

**Access and the sample** (owner, 2026-10-05). This replaces "access does not choose the sample",
which would have had the owner save about 30 portals by hand. The crawler's identity is never
changed.

- A portal that refuses the crawler, or whose robots.txt disallows it, is replaced by the next
  portal on its product that the crawler can fetch.
- A product with no portal the crawler can fetch (OpenGov, iWorQ, MyGov's `public.mygov.us`,
  eProcess360, and since 2026-10-20 Tyler EnerGov, Citizenserve, SagesGov, SmartGov and LOGIS)
  gets one portal saved by hand, with one try: the owner opens it in a browser, runs
  the same search and saves the pages (`data/population/manual/README.txt`). If it has no usable
  list, the product is reported as not estimated. None of the four had one (2026-10-20), so
  OpenGov, iWorQ, `public.mygov.us` and eProcess360 are all reported as not estimated, from one
  portal each. The other five tries are deferred. Each product is reported as not estimated
  unless the owner saves its first portal in draw order later: Carlsbad (EnerGov), O'Fallon
  (Citizenserve), LaGrange (SagesGov), Banning (SmartGov) and Apple Valley (LOGIS).
- An office's own system that refuses the crawler is not sampled (15, among them New York City,
  Los Angeles, San Francisco, San Jose, Jacksonville, Raleigh, Nashville and Orange County FL). Its units are reported as
  behind a portal that refuses an identified crawler. New York City, Los Angeles, San Francisco
  and Raleigh publish their permits as open data.
- A portal that answered the crawler but builds its search in the browser is fetched with
  Playwright, sending the crawler's identity and reading robots.txt for every request the page
  makes. Fresno's and Santa Rosa's Accela portals were checked this way on 2026-10-06: both send
  every visitor to Accela's sign-in, so they are login only.
  - **SmartGov** (Banning, Maricopa; 2026-10-20). Its Advanced Search filters on the issued date
    and pages in the browser. Its robots.txt disallows the search (`/ApplicationPublic/`), which
    the robots.txt audit found after both portals' pages were saved. Both are robots.txt
    disallows, and their pages, like Apple Valley's, were deleted.
  - **A search behind a CAPTCHA** (2026-10-20) is blocked by a bot check. The crawler does not try
    to pass one, seen or unseen: reCAPTCHA v3 at Citizenserve, reCAPTCHA at SagesGov, an image
    CAPTCHA at Bay County's CityView. Like a robots.txt refusal, it binds only a crawler.
  - **A page built for a recognised browser.** ASP.NET serves an unrecognised User-Agent a page
    without its partial-postback script. On LOGIS, Evolve, FastTrackGov and Munis, the search
    button's own script then stops. There the crawler sends the postback the button would send,
    with each field filled as the page's script fills it, as it fetches the Accela export. BS&A's
    and Houston's page scripts read the browser from the User-Agent and stop. The crawler's
    identity is not changed for either.
  - **robots.txt read under RFC 9309** (from 2026-10-20). Until then the crawler read robots.txt
    with Python's standard-library parser, which drops a rule's query and ignores wildcards. It
    also asked for the file as HTML, and read a refusal as "no rules". The
    [robots.txt audit](2026-10-20-robots-txt-audit.md) re-judged every recorded request and moved
    six portals to robots.txt disallows.
  - **robots.txt on other hosts** (owner, 2026-10-20). The rule covers every host a page loads
    from, a library's CDN included, with no exception for static scripts. That is how Google's
    renderer treats a resource robots.txt blocks. A portal that cannot render without a
    disallowed resource is recorded as robots.txt disallows, which binds only a crawler, so it can
    still be saved by hand.
  - **Pacing** (approved by the owner on 2026-10-20). The pause
    comes before each page load and each click, not before each request. A page load's scripts
    and data calls go out together, as from any browser: Fresno's first load was about 40
    requests. Images, fonts and media are never requested. Scripts and stylesheets are fetched
    once for as long as the server lets them be cached, as a browser keeps them. Every request
    counts against the run's request budget, and each saved page's row records how many requests
    it took, so the report gives the requests per portal.

This tilts the sample toward vendors that serve an identified crawler. The pipeline view, which
the headline comes from, only ever used such portals. The layout view now covers fewer products,
and the report names the ones it leaves out.

**One portal, several offices.** A portal that serves several offices (MGO Connect, LOGIS) is
sampled once. It counts once in the portal weights and with every office's units in the unit
weights.

**Development portals.** Kyle TX (EnerGov), whose markup was read to write capture's record-card
check on 2026-10-04, and the next card or list layout in draw order on another product, so that the
check is designed on two layouts and EnerGov does not lose a second place. They are used to design
the check's record detection and are not scored. No EnerGov portal can be fetched (Tyler's hosting
refuses the crawler, and the offices' own servers need a script robots.txt disallows), so EnerGov
has no tested portal unless one is saved by hand. If one is, the check was designed on an EnerGov
page, and its EnerGov results are reported with that noted. Clark stays the development portal for the Clark pilot. The
other existing targets are not part of the population estimate.

**Where locating stops** (approved by the owner on 2026-10-04): offices 1 to 150, plus a take-all
stratum of the frame's 50 largest offices (3,144 units or more; 29.9% of the frame's units). Offices
1 to 150 are located (2026-10-04): 23 Accela offices (21 answered the crawler), 21 other named
products (about 40 portals under the cap) and 16 offices on their own or unidentified systems,
before the usability check.

The take-all stratum answers the concentration above. Each of the 50 largest offices stands only
for itself. Each drawn office outside it stands for about 6.7 offices (the other 950 over the 141
drawn). Without it, Harris County stands for 6.7 offices its size, and 10.1% of every unit-weighted
figure rests on its one portal. With it, Harris is 1.7%, no office carries more than 2.0%, and the
drawn offices count as about 90 of equal size instead of 36. The cost is 41 more offices to locate.
Nine of the 50 are already in offices 1 to 150.

- A take-all office joins the product groups after office 150 in draw order. It takes a place only
  on a product that still has one.
- An office on its own system is a product of its own, so it is tested.
- New York City's boroughs share one Department of Buildings and are sampled once.
- Clark and St. Johns are among the 50 and are handled as above: recorded and skipped.

## Pages and references

**Search rule, every portal, crawled or saved by hand.** Building permits (the Permits or Building
module if the search asks for one, else the module the portal files them under, recorded per
portal: Fort Worth's is Development; one permit type only if the search will not run without it);
dates 2026-08-01 to 2026-08-31 on the issued date if offered, otherwise on the date offered, and
which one is recorded; 2026-08-03 to 2026-08-14 if the month is refused; sort order and page size
left at their defaults.

**A portal with no date field** (approved by the owner on 2026-10-07). Manatee County's
Accela search offers no date, and it will not search without a criterion. The search then runs
with the one permit type allowed above, chosen by its name before any row is read (Manatee:
"Residential"). The portal is usable if its list shows a date on each row and is in date order,
so that a pipeline could page back to any month. The first 4 pages are saved as a snapshot of the
newest records, as Santa Barbara's were in v2. A portal whose list shows no dates stays lookup
only (Santa Fe TX). Manatee's list is dated and newest first (2026-10-05 back to 2026-10-01).

**Pages.** The first 4 result pages, or all of them if there are fewer. Each has a manifest row
saying how it was got: `permits.capture` for server-built pages; Playwright sending the crawler's
identity for pages built in the browser; `BROWSER` for pages saved by hand. A page built in the
browser is saved as rendered, whichever way it was got.

**Reference, in order of preference:**

1. The portal's own export of each page. Kyle's "Export Current View" lists the same 10 permits as
   its page, in the same order, on all 4 pages (2026-10-04). Accela's result pages offer
   "Download results" for the whole search (seen on Polk's, Oregon's and Clark's saved pages); each
   page's rows are matched to it by permit number and order, and that alignment is checked on the
   first tenancy before it is relied on. Checked on North Port (2026-10-05): the crawler fetches it
   as the page's script does (the export postback, then `Export2CSV.ashx` in the same session),
   and the 40 rows of the 4 saved pages are its first 40, in order, with the same dates, types and
   addresses. The alignment is checked again for every portal (`spikes/population_onboard.py`).
2. Otherwise, a parser written for the portal, checked as below.

Exports format some values differently from the page (dates, addresses split into columns). The
mapping from export columns to the contract's fields is written per product before any extractor
is scored on it.

**Checking the reference** (approved by the owner on 2026-10-04; the owner's part replaced on
2026-10-20 by "Without the owner's review", below). Checking every row by hand would
be 2,000-3,000 rows over about 40 portals, or 1,000-2,000 without the portals that export. A
parser's errors are not scattered at random. They are per column (the wrong field, a misread
date, a cut address), so they show on every row, or they are on unusual rows. The check is aimed
at both:

1. **Automatic, every row, every portal.** The reference's row count on each page equals the
   page's own count (its "showing" line, its record links or its record blocks). Every value
   appears verbatim in that record's text on the page. Permit numbers are unique across the
   pages. Where there is an export, the parser's rows equal the export's under the written
   mapping. Every failure goes to the owner.
   - **Open data, where the office publishes it** (owner's approval, 2026-10-04). Each reference row
     is matched to the office's dataset by permit number, and the fields both carry (issue date,
     address, permit type) are compared under a mapping written per dataset, as for exports. The
     match rate is reported per portal. A row that is missing or differs goes to the owner and
     counts as a reference error only once checked, since a dataset can lag the portal, format
     fields differently or hold a subset. Nine offices have both open data and a portal that
     answered the crawler: Baltimore, Tempe, Austin, Nashville, Philadelphia, Mecklenburg,
     Miami-Dade, Seattle and Denver.
2. **Model-assisted, before any extractor is scored** (owner, 2026-10-05). This replaces a full
   check by hand of 15-30 rows a portal, which would have been 500-1,000 rows. For each portal
   without an export:
   - a checker model reads all of page 1 and every row the automatic checks flag, straight from
     the page's text, without writing code. Its reading is compared with the parser's, field by
     field.
   - the owner looks, on the side-by-side review page, at every disagreement, and at 2 rows per
     portal drawn with a fixed seed whatever the checker said.

   One confirmed error means the parser is fixed and the portal is checked again. Two on one
   portal means the checker reads all of its rows. The checker is a paid call and runs only with
   the owner's go-ahead.
   - **Checker model:** outside the scored arms and, where possible, from a different family from
     the one writing the parsers (Claude). A checker that misreads a column the same way as the
     parser lets the error through, and would favour a scored arm from that family. It is chosen
     with the arms. The owner suggested Sonnet or another Opus variant. Settled on 2026-10-20:
     Claude Sonnet 5.5 (below).
3. **After scoring, by hand, capped** (owner, 2026-10-05). It runs once, after every arm has run.
   Reviewing every row where an extractor that passed the check disagrees with the reference
   would grow with portals, arms and repeat runs, with no known limit. It is cut down in fixed
   steps:
   - **One review per reference value, not per extractor.** Disagreements are pooled over arms
     and repeat runs onto the reference cell (portal, permit, field). Cells are grouped by portal
     and field, since a parser's errors are per column, and the owner looks at one example row
     per group.
   - **Only values that could be right.** An extractor's value that does not appear verbatim in
     that record's text on the page is the extractor's error, with no review, since the
     reference passed the same check. So is a permit number the reference lacks that is not on
     the page.
   - **Only where arms agree.** A group is reviewed when at least two arms give the same value,
     different from the reference, on one of its rows. A value from one arm alone, however many
     of its repeats give it, is scored as that arm's error.
   - **At most 30 groups**, about 30 minutes, in order of how many arms agree against the
     reference, then how many rows the group holds. Where the reference is wrong, the parser is
     fixed, the portal's reference passes the automatic checks again, every extractor is
     rescored, and the correction is reported.
   - **Groups beyond the cap** are not reviewed. The report gives how many there were and their
     rows, and each arm's score two ways: with the reference as it stands, and with the agreeing
     arms' value taken as right. If the ranking of arms differs between the two, the report says
     so beside the headline.

Layer 3 cannot catch an error that the parser and the extractors share: both are written by
language models and can misread a column the same way. It also leaves alone a reference error
that only one arm reads right. The checker's reading of all of page 1 is
the guard against that. Where the office publishes open data, the dataset is a second guard that
no model wrote. The report gives the checker's agreement rate and the pooled bound from the
owner's seeded rows. With no errors in about 80, that is under 3.7% at 95%, weaker than the 0.6%
a full check by hand would have given. It notes that a per-portal bound is loose.

**Without the owner's review** (approved by the owner on 2026-10-20). The owner no longer has
time to review references by hand. This replaces every step above that sends something to the
owner, and no step of the check waits on the owner:

- **Failed automatic checks** are parser bugs. The parser is fixed and the portal checked again;
  a portal that still fails is dropped and reported.
- **Open-data mismatches** are reported in each portal's match rate, not reviewed.
- **Checker model: Claude Sonnet 5.5** (`claude-sonnet-5-5`), which is not a scored arm; the
  cheap arms are chosen from models other than the two checkers. It reads every saved row of
  every portal, not only page 1. That is about 3,000 rows, about $5 at list price ($2 and $10 per
  million input and output tokens, 2026-10-06). Both checkers run through the API like every
  scored call (owner, 2026-10-20): each call has a row in the spend ledger and each response is
  kept on disk, so everything computed from them can be recomputed without paying again. A dry
  run prices the exact requests before the go-ahead.
- **Parser and checker disagreements** are grouped by portal and field. Where the page shows the
  parser is wrong (the value is under another column, or cut short), the parser is fixed and the
  portal checked again. The rest are contested cells, scored two ways, with the parser's value
  and with the checker's.
- **After scoring**, no group needs review. Every group where arms agree against the reference is
  scored two ways, as groups beyond the cap were. A change in the ranking of arms, from either
  kind of contested cell, is reported beside the headline. Any group the owner does review, in
  the fixed order, is settled.
- **The checker's error rate, measured**, in place of the owner's seeded rows. The checker also
  reads the portals whose reference is the portal's own export (the 11 Accela exports and Kyle's),
  without seeing the export. A parser and checker can only agree on a wrong value where the
  checker is wrong, so the checker's error rate against the exports bounds how often that happens.
  It is measured on two products, Accela and EnerGov (Kyle, not scored but readable), and the
  report says so.
- **Whether a Claude reference favours the Claude arm.** The parsers and the checker are Claude,
  and so is one strong arm, Opus 5.5. It is measured on the 11 scored Accela portals with an
  export, holding the portals and rows fixed so that only the answer key changes (revised
  2026-10-20: comparing those portals' ranking with the ranking over all portals would have mixed
  a difference between products into it). Every arm is scored four times on the same rows:
  against the export, which no model wrote; against Sonnet 5.5's reading; against GPT-6 Sol's; and
  against the reference the pipeline builds where there is no export. That last one is the Accela
  parser's output (`permits/adapters/accela.py`, written 2026-09-22, before any export was
  fetched), checked against Sonnet 5.5 as on every other portal and frozen before it is compared
  with the export (added 2026-10-20: the checkers' keys alone leave out the parsers, which build
  most references).
  - **A second checker from another family** (owner, 2026-10-20): OpenAI's GPT-6 Sol
    (`openai/gpt-6-sol`) reads the export portals only, the same way as Sonnet 5.5, about 780 rows
    for about $1.50 at list price. An arm can gain from a checker's answer key because they share
    a blind spot, or because some rows are hard for every model. The second checker tells the two
    apart.
  - **The estimates**, each with a paired bootstrap interval over the 11 portals:
    - the checker: each arm's gain in score from Sonnet 5.5's key over the export, minus its gain
      from GPT-6 Sol's key. A Claude bias shows as that difference being larger for Opus 5.5 than
      for the other arms;
    - the whole reference: each arm's gain from the pipeline's key over the export, Opus 5.5
      against the other arms. This one covers the parsers as well.

    Both are reported beside the headline, as measured on Accela only.

## Weighting

- **Per product:** each approach's result pooled over that product's sampled portals, reported
  unweighted.
- **Two population views**, both reported. Pages saved by hand answer whether a model can read a
  layout, but no polite pipeline could fetch them (owner's point, 2026-10-04).
  - **Layout view:** the per-product results weighted by each product's share of all usable
    portals in the located range, including the one hand-saved portal of each product only a
    browser can reach. Each portal needs its own extractor,
    so portals are the weight. This answers "can an extractor be made for the portals that
    exist, and at what cost?"
  - **Pipeline view:** the same per-product results, weighted only over the usable portals a
    polite crawler can fetch. That means robots.txt allows the path and the portal serves the
    crawler's declared identity, with or without a headless browser. It is weighted by portals
    for cost per trusted extractor, and by 12-month units for coverage. **A sentence of the form
    "covering X% of housing costs $Y" may come only from this view.** It always sits beside the
    share of units behind portals that refuse an identified crawler, which no price covers.
  - Which portals a polite crawler can fetch is read from the probe and recorded per portal before
    any extractor is scored.
  - An office counted as open data is covered in the pipeline view with no extractor, and its
    portal leaves the pipeline view's portal weights. Coverage is reported in two parts: through
    open data, and through portals with a trusted extractor.
- **One product, one kind of access.** Since 2026-10-05 no product has both fetched and
  hand-saved portals in the sample, so the planned EnerGov comparison of the two is dropped.
- **No imputation.** A product with no estimable portal is reported as an uncovered share.
- **Design weights:** 1 for a take-all office, 950/141 for a
  drawn office outside it. They apply to every population figure, whether it is weighted by
  portals or by units.
- **Intervals:** stratified bootstrap. It resamples the drawn offices, keeps the take-all offices
  fixed, and then resamples portals within each product and draws within each portal. Resampling
  offices carries the uncertainty over which offices the draw happened to take; resampling portals
  alone would leave it out. A heavily weighted product estimated from 3 portals widens the
  interval, and the report says which products drive it.
- **Largest contributors.** Each unit-weighted figure lists the 5 offices that contribute most to
  it, with their shares, and is also given without the largest one.

## Carried over from the agent-run pre-registration

Confirmed by the owner on 2026-10-03:

- OpenInference is ignored as a host for deepseek-v4-flash.
- 10 baseline draws per cell.
- A spend limit for each stage.
- St. Johns is out.

## To be written before any paid call

- **Arms and models.** The strong one-shot models (Gemini 3.8 Flash, Opus 5.5) and the cheap ones,
  chosen by the agent-run pre-registration's rule.
- **The check, generalized beyond `<tr>` grids.** Designed on the development portals and frozen
  before any test portal's pages are seen by a model.
- **The repair loop and the agent.**
- **Stages with stop rules and spend limits.** Estimated earlier at $15-40 in all: a Clark pilot
  (~$1), cheap one-shot on every portal, strong one-shot, then loop and agent where there is room.

## What this does not establish

- Only the 1,000 largest offices. Smaller offices more often have no portal at all (Spike A).
- Portals as found in October 2026. Offices change systems: Boerne moved from SmartGov to MyGov in
  July 2025, and Albuquerque replaced its permit systems with ABQ-PLAN in 2025.
- Saving by hand and crawling capture pages in different ways. Each page records how it was got,
  and the results are also reported split by access method.
- What a polite crawler can fetch, as of October 2026, for a crawler that states who it is and
  never changes that. Blocking rules change. An operator can also ask an office or vendor for
  access, which is outside this study.
