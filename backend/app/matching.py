"""What makes two pasted links the same posting.

Pure functions, no database and no framework, so every rule below is testable
on its own. This is the one piece of real logic in MBS: without it the pool
fills with the same job five times under five referral links, and "you already
applied for this" never fires when it should.
"""
from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Sequence

# Legal suffixes and filler stripped before two client names are compared, so
# "Acme Solutions Pvt Ltd" and "ACME Solutions" collapse to one key.
_SUFFIX = re.compile(
    r"\b(pvt|private|ltd|limited|llc|inc|incorporated|corp|corporation|co|"
    r"gmbh|bv|nv|plc|llp|group|holdings|enterprises|international)\b"
)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = _SUFFIX.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# Ordered — the first pattern that hits wins. A platform's own job id is the
# most reliable identity there is: same posting, any link, same id.
#
# The third element says whether the id only means something within one site.
# The named platforms mint globally unique ids. The last two rules are
# shape-matchers — "a long number in the path" — and that shape repeats on
# every job board alive, so the host goes in the key or two unrelated postings
# fuse and one of them silently vanishes from the pool.
_ID_RULES: Sequence[tuple[re.Pattern, str, bool]] = (
    (re.compile(r"(~[0-9a-z]{12,})", re.I), "upwork", False),
    (re.compile(r"/jobs/view/(\d{6,})", re.I), "linkedin", False),
    (re.compile(r"[?&]jk=([0-9a-z]{8,})", re.I), "indeed", False),
    (re.compile(r"/projects/[^/]*?[-.](\d{6,})", re.I), "freelancer", False),
    (re.compile(r"/(?:job|jobs|gig|project)/[^/]*?[-/](\d{6,})", re.I), "board", True),
    (re.compile(r"/(\d{7,})(?:[/?#]|$)"), "numeric", True),
)

# Query parameters that name the posting rather than the search that found it.
# Everything else in a query string is dropped — that is what makes one job
# pasted through two referral links one job. Named conservatively: a bare `id`
# is as likely to be a session token, and keeping one of those would split a
# posting into a fresh row on every visit, which is the worse mistake.
_ID_PARAMS = frozenset({
    "jobid", "jobno", "jobcode", "currentjobid", "vjk", "jk", "gh_jid",
    "postingid", "requisitionid", "reqid", "vacancyid", "positionid",
})


def canonical_url(raw: object) -> str:
    """Host, path, and any query parameter that names the posting.

    Protocol, www, fragment, tracking parameters and the trailing slash all
    go. Kept parameters are sorted, so the same job pasted with its arguments
    in a different order is still the same job.
    """
    text = str(raw or "").strip()
    if not text or "." not in text:
        return ""
    text = text.lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("#")[0]
    head, _, query = text.partition("?")
    head = head.rstrip("/")
    keep = sorted((k, v) for k, v in urllib.parse.parse_qsl(query)
                  if k in _ID_PARAMS and v)
    if keep:
        head += "?" + "&".join(f"{k}={v}" for k, v in keep)
    return head


# The tail an apply flow leaves behind. One posting reached two ways: somebody
# browsing pastes the listing, somebody who actually applied pastes whatever
# the apply button left in the address bar.
#
# Only ever stripped from the END. The first group may carry a sub-path of its
# own (Workday's /apply/autofillWithResume); the second must be the very last
# segment, because "job" and "jobs" sit in the middle of nearly every careers
# URL and letting those swallow the rest turns one employer's whole board into
# a single row.
_APPLY_TAIL = re.compile(
    r"/(apply|apply-now|applynow|application|submit|autofillwithresume)(?:/.*)?$", re.I)
_APPLY_LAST = re.compile(r"/(job|jobs|start|login|register|confirm|review)$", re.I)


def posting_stem(raw: object) -> str:
    """One posting, however it was linked. Deliberately narrow.

    It merges a listing with its own apply flow and nothing else: two genuinely
    different openings still have different stems, because the part that names
    them survives.
    """
    clean = canonical_url(raw)
    if not clean or "/" not in clean:
        return ""
    if "?" in clean:
        return clean
    previous = None
    while previous != clean:
        previous = clean
        clean = _APPLY_LAST.sub("", _APPLY_TAIL.sub("", clean))
        if "/" not in clean:
            return ""
    return clean


def split_url(raw: object) -> tuple[str, str]:
    """(host, path). Both empty when there is no usable host."""
    clean = canonical_url(raw).split("?")[0]
    if not clean:
        return "", ""
    site, _, rest = clean.partition("/")
    return site, "/" + rest


def fingerprint(url: object, title: object, company: object) -> tuple[str, str]:
    """(fingerprint, tier). An empty fingerprint means the row is unusable.

    Three tiers, best first: a platform id, then the canonical URL, then the
    client and the role as written. L3 is a last resort and is exactly as good
    as the typing behind it — which is why the entry form asks for a link.
    """
    raw_url = str(url or "").strip()
    if raw_url:
        site, path = split_url(raw_url)
        for pattern, tag, site_scoped in _ID_RULES:
            if site_scoped and not site:
                continue
            # Site-scoped rules read the path only: a long hex run in a query
            # string is a session token shared across a whole visit, not an id.
            hit = pattern.search(path if site_scoped else raw_url)
            if hit:
                value = hit.group(1).lower()
                return (f"id:{tag}:{site}:{value}" if site_scoped
                        else f"id:{tag}:{value}"), "L1"
        stem = posting_stem(raw_url) or canonical_url(raw_url)
        if len(stem) > 8:
            return f"url:{stem}", "L2"

    client, role = normalize_text(company), normalize_text(title)
    if not client and not role:
        return "", "-"
    return f"ct:{client}|{role}", "L3"
