# -*- coding: utf-8 -*-
"""Which permitting product a portal runs, from its address and its page.

A portal's vendor decides most of what an extractor faces: Accela tenancies
share a grid, Tyler EnerGov renders record cards in the browser, a city's own
system can be anything. The portal population study (`spikes/population_*`)
classifies every portal it finds with these fingerprints, and finds portals
on an office's own website by the same list.

Fingerprints are matched case-insensitively. First match wins, so the
specific products come before the catch-alls for a vendor's other products.
"""
import re

from permits.capture import strip_scripts

VENDORS = [
    # Seattle's Services Portal is Accela Citizen Access under its own start
    # page; its links into the search (Cap/CapHome.aspx) give it away.
    ("Accela", r"accela\.com|/CitizenAccess/|ACA_TabRow|Accela Citizen Access|"
               r"/Cap/CapHome\.aspx"),
    ("Tyler EnerGov", r"energov|tylerhost\.net/apps/selfservice"),
    ("CentralSquare eTRAKiT", r"etrakit"),
    ("CentralSquare Click2Gov", r"click2gov"),
    ("CityView", r"cityview|CVProdPortal"),
    ("Citizenserve", r"citizenserve"),
    ("iWorQ", r"iworq"),
    ("MyGov", r"mygov\.us|mygovernmentonline|mgoconnect"),
    ("OpenGov", r"viewpointcloud|opengov\.com"),
    ("BS&A", r"bsaonline"),
    ("SmartGov", r"smartgov"),
    ("Cloudpermit", r"cloudpermit"),
    ("Oracle", r"oraclecloud|Oracle Public Sector"),
    ("Avolve ProjectDox", r"avolve|projectdox"),
    ("SagesGov", r"sagesgov"),
    ("CommunityCore", r"communitycore"),
    ("Clariti", r"clariti"),
    ("Cityworks", r"cityworks"),
    ("GovPilot", r"govpilot"),
    ("Municity", r"municity"),
    ("ASPGov", r"aspgov"),
    ("Infor", r"infor\s*public\s*sector|hansen"),
    ("Tyler Munis", r"munis"),
    # "edgesuite" is Akamai, and its block page names it.
    ("Tyler eSuite", r"(?<![a-z])esuite"),
    ("Cityworks", r"/publicapp/"),
    ("CivicGov", r"civicgov"),
    ("Perconti CD Plus", r"perconti|cd plus"),
    ("Evolve", r"evolvepublic"),
    ("FastTrackGov", r"fasttrackgov"),
    ("eProcess360", r"eprocess360"),
    ("LOGIS ePermits", r"epermits\.logis\.org"),
    ("GovWell", r"govwell"),
    # Austin's Build + Connect and Volusia's Connect Live: AMANDA's citizen
    # portal, whose page script names its back end.
    ("AMANDA", r"/citizenportal/app/|Amanda services"),
    # Philadelphia's eCLIPSE is a POSSE application; its page title says so.
    ("Computronix POSSE", r"computronix|\bPOSSE\b"),
    ("Tyler (other)", r"tylertech|tyler technologies|tylerhost"),
    ("CentralSquare (other)", r"centralsquare"),
]
VENDOR_RES = [(n, re.compile(p, re.I)) for n, p in VENDORS]
TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")


def from_url(url):
    """The product an address names, or ""."""
    for name, rx in VENDOR_RES:
        if rx.search(url):
            return name
    return ""


def identify(final_url, html):
    """(product, where it was read): from the URL, then the page title, then
    the page body, then its scripts. The title outranks the body because a
    portal's page can link to another vendor's (Bay County's CityView page
    links to an eTRAKiT one)."""
    name = from_url(final_url)
    if name:
        return name, "url"
    m = TITLE.search(html)
    for name, rx in VENDOR_RES:
        if m and rx.search(m.group(1)):
            return name, "title"
    body = strip_scripts(html)
    for name, rx in VENDOR_RES:
        if rx.search(body):
            return name, "page"
    for name, rx in VENDOR_RES:
        if rx.search(html):
            return name, "script"
    return "", ""
