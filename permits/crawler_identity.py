# -*- coding: utf-8 -*-
"""The identity this project presents to the servers it fetches from.

docs/design/history.md section 11 commits to identifying the crawler with a real contact
address. That commitment was previously honoured by a literal string copied
into eight scripts, which made the contact address the one value in the
project that could not be changed in one place - and which put a personal
mailbox into the access logs of every municipal server touched.

Both problems have the same fix: the contact is configuration, not source. It
lives in the environment or in an untracked file, never in the tree, so that
publishing this repository does not publish a mailbox, and so that changing it
is one edit rather than eight.

What the contact should be is a judgement about where inquiries should land.
An address that reaches a person who can actually stop the crawler is the
point; a URL describing the study is usually better than a mailbox, because it
answers the operator's question without requiring anyone to send mail.

Deliberately not a silent default. A crawler that quietly loses its contact
address while still crawling is worse than one that stops, because the posture
degrades invisibly - the same failure shape as a page on disk with no verdict
recorded against it (Spike C). `user_agent()` raises rather than emitting an
anonymous or placeholder identity.
"""
import io
import os

NAME = "PermitsResearchBot"
VERSION = "0.1"
PURPOSE = "municipal open-data coverage study"

CONTACT_ENV = "PERMITS_CONTACT"
CONTACT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".permits-contact")


class ContactNotConfigured(RuntimeError):
    """Raised when a request is about to be made with no contact to present."""


def contact():
    """The configured contact string, or None.

    Environment first so a run can override without touching the filesystem;
    the untracked file second so routine local runs need no ceremony.
    """
    v = (os.environ.get(CONTACT_ENV) or "").strip()
    if v:
        return v
    try:
        with io.open(CONTACT_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.split("#")[0].strip()
                if line:
                    return line
    except IOError:
        pass
    return None


def user_agent():
    """The User-Agent header value. Raises if no contact is configured."""
    c = contact()
    if not c:
        raise ContactNotConfigured(
            "No crawler contact configured, so there is no identity to "
            "present and no request will be made.\n"
            "Set %s, or write one line into %s.\n"
            "A contact URL or role address is preferred over a personal "
            "mailbox - see docs/design/history.md section 11."
            % (CONTACT_ENV, CONTACT_FILE))
    return "%s/%s (%s; contact: %s)" % (NAME, VERSION, PURPOSE, c)
