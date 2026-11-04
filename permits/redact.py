# -*- coding: utf-8 -*-
"""Pseudonymize the released fixtures: stripped portal pages, their
references, the excerpts the arms were shown and the stored extractors.

The pages are public records, but the release should not be a convenient
copy of who built what where. Every change is made one token at a time by
a keyed hash, so the same word or number becomes the same pseudonym in a
page, its reference, its excerpt and an extractor's string literals, and a
stored extractor scores the same on the redacted pages as on the originals
(`scripts/build_release.py` re-scores every one to show it).

Text between tags:

- a word is kept if it is in the vocabulary (words seen on the pages of 3
  or more jurisdictions, plus every status and permit-type value in the
  references, plus street suffixes and directionals), else it becomes a
  pronounceable word of the same length and case;
- a run of 2 or more digits becomes other digits of the same length, except
  inside a date and a 4-digit year (1900-2039);
- dates, status and permit-type values are kept whole.

Inside tags only `href` and `value` change: digit runs of 4 or more and
long mixed tokens (record ids such as Salesforce's) get the same treatment,
and the record's own values are replaced where they appear. Tag names,
`id`, `name`, `class` and `type` are untouched, because the record-count
check and the extractors read the page's structure.
"""
import hashlib
import hmac
import html
import re

TAG = re.compile(r"<[^>]*>?")
TOKEN = re.compile(r"[A-Za-z]+|\d+")
ATTR = re.compile(r'\b(href|value)="([^"]*)"', re.I)
ATTR_TOKEN = re.compile(r"[A-Za-z0-9]+")
DATE = re.compile(
    r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? "
    r"\d{1,2},? \d{4}"
    r"|\d{1,2}:\d{2}(?::\d{2})?(?: ?[AP]M)?)\b", re.I)
YEAR = re.compile(r"^(?:19\d\d|20[0-3]\d)$")
OWNER = re.compile(r"(?<![A-Za-z])([A-Za-z]+)(?=\s+(?:residence|res|family "
                   r"trust|living trust|trust)(?![A-Za-z]))", re.I)
DESCRIBES = frozenset("""
new single family existing primary private custom main guest model story
storey two one three sfr the a an of to for at and or with in on new
""".split())
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ENTITY = re.compile(r"&(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);")
STREET = frozenset("""
st street rd road ave avenue av dr drive ln lane ct court blvd boulevard way
pl place cir circle ter terrace loop hwy highway pkwy parkway trl trail sq
square run pt point xing cv cove pass path ste suite unit apt bldg fl lot
n s e w ne nw se sw north south east west united states usa
al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo
mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy
jan feb mar apr may jun jul aug sep sept oct nov dec january february march
april june july august september october november december mon tue wed thu
fri sat sun monday tuesday wednesday thursday friday saturday sunday
""".split())
# Counts and pager text: an extractor may check its rows against them.
PAGER = re.compile(
    r"\b\d[\d,]*\s*(?:[-\u2013\u2014]|to|through)\s*\d[\d,]*\s+of\s+\d[\d,]*\+?"
    r"|\b\d[\d,]*\+?\s+(?:record|result|item|row|permit|match)(?:e?s)?\b"
    r"|\bpage\s+\d+(?:\s+of\s+\d+)?"
    r"|\bper\s+page\s*[:=\-]?\s*\d+|\b\d+\s+(?:[a-z]+\s+)?per\s+page"
    r"|\bpage\s*size\s*[:=\-]?\s*\d+", re.I)
VOWELS, CONSONANTS = "aeiou", "bcdfghjklmnprstvwz"


class Redactor:
    """One keyed, memoized token map for a whole release."""

    def __init__(self, key, vocab=(), protected=()):
        self.key = key.encode("utf-8")
        self.vocab = {w.lower() for w in vocab} | STREET
        # Kept whole wherever they appear: status and permit-type values.
        ps = {p.strip() for p in protected if p and p.strip()}
        ps |= {html.escape(p, quote=False) for p in ps}
        ps = sorted(ps, key=len, reverse=True)
        self.protected = (re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])"
                                     % "|".join(map(re.escape, ps)))
                          if ps else None)
        self.digit_map, self.word_map = {}, {}
        self._used = set()

    # -------------------------------------------------------------- tokens
    def _stream(self, kind, s):
        n = 0
        while True:
            h = hmac.new(self.key, ("%s|%s|%d" % (kind, s, n)).encode("utf-8"),
                         hashlib.sha256).digest()
            yield from h
            n += 1

    def digits(self, s):
        """Another number of the same length, one-to-one per length."""
        if s in self.digit_map:
            return self.digit_map[s]
        if len(s) < 2:
            return s
        b = self._stream("d", s)
        # One-to-one while it can be: short lengths run out of fresh values.
        for tries in range(1000):
            out = "".join(str(next(b) % 10) for _ in s)
            if s[0] != "0" and out[0] == "0":
                out = str(next(b) % 9 + 1) + out[1:]
            if out != s and (("d", out) not in self._used or tries > 200):
                break
        self._used.add(("d", out))
        self.digit_map[s] = out
        return out

    def word(self, w):
        """A pronounceable word of the same length and case."""
        low = w.lower()
        if low not in self.word_map:
            b = self._stream("w", low)
            first = next(b) % 2
            self.word_map[low] = "".join(
                (CONSONANTS if (i + first) % 2 == 0 else VOWELS)
                [next(b) % (len(CONSONANTS) if (i + first) % 2 == 0
                            else len(VOWELS))]
                for i in range(len(w)))
        out = self.word_map[low]
        if w.isupper() and len(w) > 1:
            return out.upper()
        if w[0].isupper():
            return out[0].upper() + out[1:]
        return out

    def token(self, t):
        if t.isdigit():
            return t if len(t) < 2 or YEAR.match(t) else self.digits(t)
        return t if len(t) < 2 or t.lower() in self.vocab else self.word(t)

    # ---------------------------------------------------------------- text
    def email(self, m):
        """Every part of an address, vocabulary or not."""
        return re.sub(r"[A-Za-z]+|\d+", lambda t: (
            self.digits(t.group(0)) if t.group(0).isdigit()
            else self.word(t.group(0))), m.group(0))

    def owner(self, m):
        """The word before RESIDENCE is an owner's name unless it says
        what kind of residence."""
        w = m.group(1)
        return w if w.lower() in DESCRIBES else self.word(w)

    def text(self, s):
        """Text between tags (or any record value)."""
        s = EMAIL.sub(self.email, s)
        s = OWNER.sub(self.owner, s)
        keep = [m.span() for m in EMAIL.finditer(s)]
        for rx in (ENTITY, DATE, PAGER, self.protected):
            if rx is not None:
                keep += [m.span() for m in rx.finditer(s)]
        keep.sort()
        out, at = [], 0
        for a, b in keep:
            if a < at:
                continue
            out.append(TOKEN.sub(lambda m: self.token(m.group(0)), s[at:a]))
            out.append(s[a:b])
            at = b
        out.append(TOKEN.sub(lambda m: self.token(m.group(0)), s[at:]))
        return "".join(out)

    def attr_token(self, t):
        if t.isdigit():
            return t if len(t) < 4 or YEAR.match(t) else self.digits(t)
        if len(t) >= 8 and any(c.isdigit() for c in t) and any(
                c.isalpha() for c in t):
            # The first 3 characters name a type (Salesforce's key prefix
            # "a03", Accela's "PMT"), not a record: kept.
            return t[:3] + "".join(
                self.digits(x) if x.isdigit() else
                (x if x.lower() in self.vocab else self.word(x))
                for x in TOKEN.findall(t[3:]))
        return t

    def tag(self, t, values=()):
        """One tag: only `href` and `value` change."""
        def attr(m):
            v = m.group(2)
            for old, new in values:
                v = v.replace(old, new)
            return '%s="%s"' % (m.group(1), ATTR_TOKEN.sub(
                lambda x: self.attr_token(x.group(0)), v))
        return ATTR.sub(attr, t)

    def page(self, html, values=()):
        """A stripped page or excerpt. `values` are (original, redacted)
        record values, replaced inside `href` and `value` first."""
        out, at = [], 0
        for m in TAG.finditer(html):
            out.append(self.text(html[at:m.start()]))
            out.append(self.tag(m.group(0), values))
            at = m.end()
        out.append(self.text(html[at:]))
        return "".join(out)


def code_literals(src, changed):
    """An extractor with `changed` tokens ({original: pseudonym}) replaced
    inside its string literals and comments only, so a marker it copied from
    the page still finds the redacted page and no identifier moves. Code
    that does not tokenize is changed throughout."""
    import io
    import tokenize
    if not changed:
        return src
    rx = re.compile(r"(?<![A-Za-z0-9])(%s)(?![A-Za-z0-9])" % "|".join(
        map(re.escape, sorted(changed, key=len, reverse=True))))

    def sub(s):
        return rx.sub(lambda m: changed[m.group(1)], s)
    kinds = {tokenize.STRING, tokenize.COMMENT}
    kinds.update(getattr(tokenize, k) for k in ("FSTRING_MIDDLE",
                                                 "TSTRING_MIDDLE")
                 if hasattr(tokenize, k))
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
                if t.type in kinds]
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return sub(src)
    starts = [0]
    for line in src.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    out, at = [], 0
    for t in toks:
        a = starts[t.start[0] - 1] + t.start[1]
        b = starts[t.end[0] - 1] + t.end[1]
        out.append(src[at:a])
        out.append(sub(src[a:b]))
        at = b
    out.append(src[at:])
    return "".join(out)


def vocabulary(texts_by_place, min_places=3):
    """Words seen in the text of `min_places` or more jurisdictions:
    `texts_by_place` maps a jurisdiction to an iterable of text."""
    seen = {}
    for texts in texts_by_place.values():
        words = set()
        for t in texts:
            words.update(w.lower() for w in re.findall(r"[A-Za-z]{2,}", t))
        for w in words:
            seen[w] = seen.get(w, 0) + 1
    return {w for w, n in seen.items() if n >= min_places}


def text_nodes(html):
    """The text between a page's tags."""
    return [s for s in TAG.split(html) if s.strip()]
