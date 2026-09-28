#!/usr/bin/env python3
"""
arxiv_pull.py — Pull papers from arXiv's latest daily announcement for a given
set of categories.

Scope: this script ONLY fetches papers. It does no filtering, ranking, or
digesting — that is left to a downstream step (e.g. handing metadata.json to
Claude). It can pull any subset of metadata fields (title, authors, abstract,
...) and optionally download the raw full text as the .tex source archive.

Papers are selected by ANNOUNCEMENT date — i.e. when a paper actually appears
in arXiv's daily listing — NOT by submission date. The arXiv query API only
knows submission dates, so selection instead uses arXiv's daily RSS
announcement feed (https://rss.arxiv.org/rss/<category>): it covers the most
recent announcement and tags each paper as new / cross / replace. Full metadata
for the selected papers is then fetched from the arXiv API by id, so the output
keeps abstracts, authors, the .tex source, etc. The feed only carries the most
recent announcement, so this is meant for a once-a-day run (no date ranges).

Uses only the Python standard library (urllib + xml.etree) — no third-party
packages. We handle the arXiv API rate limit (one request / 3s) and retries
ourselves; a single throttle spaces the feed fetch, the API queries, and the
.tex downloads so the 3s rule holds across all requests together.

Environment: any Python 3.9+ interpreter works; no dependencies to install.
    python arxiv_pull.py ...

Examples
--------
# Latest announcement in the default categories, metadata only:
python arxiv_pull.py

# Latest announcement in two categories, all metadata, download .tex source:
python arxiv_pull.py --categories astro-ph.CO astro-ph.IM --fields all --fulltext tex

# Only genuinely new submissions (exclude cross-lists):
python arxiv_pull.py --announce-types new

# Specific papers by id, only titles + abstracts:
python arxiv_pull.py --ids 2401.12345 1706.03762v1 --fields title abstract

Output
------
<out>/                          (default: ./arxiv_pull_<YYYY-MM-DD>)
  metadata.json                 query info + list of papers (selected fields)
  source/<id>.tar.gz|.gz        raw .tex source archive (only if --fulltext tex)

In announcement mode each paper also carries `announce_type` (new/cross/replace)
and `announced` (the announcement datetime), so you can tell how it appeared.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------- #
# Configuration / defaults
# --------------------------------------------------------------------------- #

# arXiv asks clients to make no more than one request every 3 seconds over a
# single connection. That limit is shared across all of arXiv's endpoints, so
# the feed fetch, the API queries and our source downloads all use the same
# minimum interval. https://info.arxiv.org/help/api/tou.html
API_URL = "https://export.arxiv.org/api/query"
RSS_URL = "https://rss.arxiv.org/rss/{category}"   # daily announcement feed
USER_AGENT = "arxiv_pull/3.0 (personal daily paper puller; contact: local user)"
MIN_REQUEST_INTERVAL = 5.0   # min seconds between requests (arXiv ToU asks >= 3s;
                             # we leave headroom since the run isn't time-critical)
NUM_RETRIES = 5              # retries for API queries and downloads
MAX_RETRY_WAIT = 120.0       # cap on how long we'll honor a Retry-After / backoff
_last_request_time = 0.0     # monotonic timestamp of the last arXiv request

# Atom / arXiv / OpenSearch XML namespaces used in the API + RSS responses.
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"

# Edit this list (or pass --categories) to change what gets pulled.
# A handful of common astro categories for reference:
#   astro-ph.CO  Cosmology and Nongalactic Astrophysics
#   astro-ph.GA  Astrophysics of Galaxies (incl. IGM)
#   astro-ph.IM  Instrumentation and Methods for Astrophysics
#   astro-ph.HE  High Energy Astrophysical Phenomena
#   astro-ph.EP / astro-ph.SR  Earth/Planetary, Solar/Stellar
# Full list: https://arxiv.org/category_taxonomy
DEFAULT_CATEGORIES = ["astro-ph.CO", "astro-ph.IM", "astro-ph.GA"]

# How a paper appeared in the daily announcement.
#   new      originally submitted to one of the requested categories
#   cross    cross-listed into a requested category from elsewhere
#   replace  a revised version of an older paper, re-announced
ANNOUNCE_TYPES = ["new", "cross", "replace"]

# Optional metadata fields the user may choose to include in metadata.json.
# id, abs_url and pdf_url are ALWAYS included so the output is self-contained.
# (published/updated are SUBMISSION dates; `announced` carries the appearance.)
OPTIONAL_FIELDS = [
    "title",
    "authors",
    "abstract",
    "primary_category",
    "categories",
    "comment",
    "doi",
    "journal_ref",
    "published",
    "updated",
]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Rate limiting (shared by the feed fetch, API queries and source downloads)
# --------------------------------------------------------------------------- #

def _throttle(min_interval: float) -> None:
    """Block until >= min_interval has passed since the last arXiv request."""
    global _last_request_time
    wait = min_interval - (time.monotonic() - _last_request_time)
    if wait > 0:
        time.sleep(wait)
    _last_request_time = time.monotonic()


def _retry_after_seconds(headers, attempt: int, min_interval: float) -> float:
    """How long to wait after a 429/503: honor Retry-After, else back off."""
    value = headers.get("Retry-After") if headers else None
    if value:
        try:
            return min(MAX_RETRY_WAIT, float(value))  # delta-seconds form
        except ValueError:
            parsed = email.utils.parsedate_to_datetime(value)  # HTTP-date form
            if parsed is not None:
                delta = (parsed - dt.datetime.now(parsed.tzinfo)).total_seconds()
                return min(MAX_RETRY_WAIT, max(0.0, delta))
    return min(MAX_RETRY_WAIT, min_interval * (2 ** attempt))


# --------------------------------------------------------------------------- #
# arXiv API query model (replaces the `arxiv` library)
# --------------------------------------------------------------------------- #

def _parse_dt(text: str | None) -> dt.datetime | None:
    """Parse an Atom timestamp (e.g. '2024-01-23T18:00:00Z') to a tz-aware datetime."""
    if not text:
        return None
    return dt.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))


class Result:
    """A single parsed arXiv API <entry>."""

    def __init__(self, entry_id: str, title: str, authors: list[str],
                 summary: str, primary_category: str | None,
                 categories: list[str], comment: str | None, doi: str | None,
                 journal_ref: str | None, published: dt.datetime | None,
                 updated: dt.datetime | None, pdf_url: str | None) -> None:
        self.entry_id = entry_id
        self.title = title
        self.authors = authors
        self.summary = summary
        self.primary_category = primary_category
        self.categories = categories
        self.comment = comment
        self.doi = doi
        self.journal_ref = journal_ref
        self.published = published
        self.updated = updated
        self.pdf_url = pdf_url

    @classmethod
    def from_entry(cls, entry: ET.Element) -> "Result":
        pc = entry.find(f"{ARXIV_NS}primary_category")
        pdf_url = None
        for link in entry.findall(f"{ATOM_NS}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
        return cls(
            entry_id=(entry.findtext(f"{ATOM_NS}id") or "").strip(),
            title=entry.findtext(f"{ATOM_NS}title") or "",
            authors=[a.findtext(f"{ATOM_NS}name") or ""
                     for a in entry.findall(f"{ATOM_NS}author")],
            summary=entry.findtext(f"{ATOM_NS}summary") or "",
            primary_category=pc.get("term") if pc is not None else None,
            categories=[term for c in entry.findall(f"{ATOM_NS}category")
                        if (term := c.get("term"))],
            comment=entry.findtext(f"{ARXIV_NS}comment"),
            doi=entry.findtext(f"{ARXIV_NS}doi"),
            journal_ref=entry.findtext(f"{ARXIV_NS}journal_ref"),
            published=_parse_dt(entry.findtext(f"{ATOM_NS}published")),
            updated=_parse_dt(entry.findtext(f"{ATOM_NS}updated")),
            pdf_url=pdf_url,
        )

    def get_short_id(self) -> str:
        """Short id (with version), e.g. '2401.12345v1' or 'cond-mat/0703041v1'."""
        return self.entry_id.split("/abs/")[-1]

    def source_url(self) -> str:
        """URL of the raw .tex e-print source archive."""
        url = self.entry_id.replace("/abs/", "/e-print/")
        return re.sub(r"^http://", "https://", url)


class Search:
    """An arXiv API query for an explicit list of ids."""

    def __init__(self, id_list: list[str]) -> None:
        self.id_list = list(id_list)
        self.max_results = None  # bounded by len(id_list) via totalResults

    def params(self, start: int, page_size: int) -> dict:
        return {
            "start": start,
            "max_results": page_size,
            "id_list": ",".join(self.id_list),
        }


class Client:
    """Fetches URLs and pages through arXiv API results, pacing + retrying."""

    def __init__(self, page_size: int, delay_seconds: float,
                 num_retries: int = NUM_RETRIES) -> None:
        self.page_size = page_size
        self.delay_seconds = delay_seconds
        self.num_retries = num_retries

    def get_url(self, url: str) -> bytes:
        """GET a URL with the shared throttle + retry on 429/503/network errors."""
        last_err: Exception | None = None
        for attempt in range(1, self.num_retries + 1):
            _throttle(self.delay_seconds)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.read()
            except urllib.error.HTTPError as err:
                last_err = err
                if attempt < self.num_retries:
                    if err.code in (429, 503):
                        wait = _retry_after_seconds(err.headers, attempt,
                                                    self.delay_seconds)
                    else:
                        wait = min(MAX_RETRY_WAIT,
                                   self.delay_seconds * (2 ** attempt))
                    log(f"  HTTP {err.code} (attempt {attempt}/"
                        f"{self.num_retries}); waiting {wait:.0f}s")
                    time.sleep(wait)
                    continue
            except urllib.error.URLError as err:
                last_err = err
                if attempt < self.num_retries:
                    wait = min(MAX_RETRY_WAIT, self.delay_seconds * (2 ** attempt))
                    log(f"  request failed (attempt {attempt}/{self.num_retries}): "
                        f"{err.reason}; retrying in {wait:.0f}s")
                    time.sleep(wait)
                    continue
        raise RuntimeError(
            f"request failed after {self.num_retries} attempts: {url}"
        ) from last_err

    def _get(self, params: dict) -> bytes:
        return self.get_url(API_URL + "?" + urllib.parse.urlencode(params))

    def results(self, search: Search):
        """Yield Results, paging through the API until exhausted/capped."""
        fetched = 0
        start = 0
        while True:
            if search.max_results is not None and fetched >= search.max_results:
                return
            page_size = self.page_size
            if search.max_results is not None:
                page_size = min(page_size, search.max_results - fetched)
            root = ET.fromstring(self._get(search.params(start, page_size)))

            total_text = root.findtext(f"{OPENSEARCH_NS}totalResults")
            total = int(total_text) if total_text else None
            entries = root.findall(f"{ATOM_NS}entry")
            if not entries:
                return

            for entry in entries:
                yield Result.from_entry(entry)
                fetched += 1
                if search.max_results is not None and fetched >= search.max_results:
                    return
            start += len(entries)
            if total is not None and start >= total:
                return


def make_client(page_size: int, delay_seconds: float,
                num_retries: int = NUM_RETRIES) -> Client:
    """A Client that paces + retries requests for us."""
    return Client(page_size=page_size, delay_seconds=delay_seconds,
                  num_retries=num_retries)


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

def _bare_id(short_id: str) -> str:
    """Strip a trailing version (v1, v2, ...) from an arXiv short id."""
    return re.sub(r"v\d+$", "", short_id)


def _id_from_link(link: str) -> str:
    """Extract the bare arXiv id from an abstract-page URL."""
    return _bare_id(link.rsplit("/abs/", 1)[-1].strip())


def _parse_rss_date(text: str | None) -> str | None:
    """Parse an RSS pubDate (RFC 822) to an ISO-8601 string."""
    if not text:
        return None
    parsed = email.utils.parsedate_to_datetime(text)
    return parsed.isoformat() if parsed else None


def fetch_announced(client: Client, categories: list[str],
                    announce_types: list[str], max_results: int
                    ) -> tuple[list[Result], dict[str, dict[str, str | None]]]:
    """
    Select papers from each category's latest daily announcement (RSS feed),
    keep the chosen announce types, then fetch full metadata via the API by id.

    Returns (results, announced) where `announced` maps bare arXiv id ->
    {"announce_type": str, "announced": iso-datetime}.
    """
    announced: dict[str, dict[str, str | None]] = {}
    order: list[str] = []
    for cat in categories:
        log(f"Announcement feed: {cat}")
        url = RSS_URL.format(category=urllib.parse.quote(cat))
        channel = ET.fromstring(client.get_url(url)).find("channel")
        if channel is None:
            log(f"  no <channel> in feed for {cat}; skipping")
            continue
        for item in channel.findall("item"):
            atype = (item.findtext(f"{ARXIV_NS}announce_type") or "").strip()
            if atype not in announce_types:
                continue
            link = item.findtext("link") or ""
            if "/abs/" not in link:
                continue
            bid = _id_from_link(link)
            if bid in announced:
                continue
            announced[bid] = {
                "announce_type": atype,
                "announced": _parse_rss_date(item.findtext("pubDate")),
            }
            order.append(bid)

    ids = order[:max_results]
    capped = f" (capped to {len(ids)})" if len(ids) < len(order) else ""
    log(f"{len(order)} paper(s) in latest announcement{capped}; "
        f"types kept: {', '.join(announce_types)}")
    if not ids:
        return [], announced
    return fetch_by_ids(client, ids), announced


def fetch_by_ids(client: Client, ids: list[str]) -> list[Result]:
    """Fetch specific papers by arXiv id (bare, versioned, or old-style)."""
    log(f"Fetching metadata for {len(ids)} paper(s) by id ...")
    results = list(client.results(Search(id_list=ids)))
    if len(results) < len(ids):
        log(f"Warning: requested {len(ids)} id(s) but the API returned "
            f"{len(results)}; some ids may be invalid or not found.")
    return results


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def _clean(s: str | None) -> str:
    """Collapse the newlines/indentation arXiv puts in titles & abstracts."""
    return re.sub(r"\s+", " ", s).strip() if s else ""


def _safe_id(result: Result) -> str:
    """Filesystem-safe form of the short id (old ids contain '/')."""
    return re.sub(r"[^0-9A-Za-z._-]", "_", result.get_short_id())


def result_to_dict(result: Result, fields: list[str],
                   files: dict[str, str] | None = None,
                   extra: dict[str, str | None] | None = None) -> dict:
    """Serialize a Result, including only the chosen optional fields.

    id, abs_url and pdf_url are always present so the entry is self-contained.
    `extra` (e.g. announce_type/announced) is merged in right after them.
    """
    values = {
        "title": _clean(result.title),
        "authors": list(result.authors),
        "abstract": _clean(result.summary),
        "primary_category": result.primary_category,
        "categories": list(result.categories),
        "comment": _clean(result.comment) or None,
        "doi": result.doi or None,
        "journal_ref": _clean(result.journal_ref) or None,
        "published": result.published.isoformat() if result.published else None,
        "updated": result.updated.isoformat() if result.updated else None,
    }
    out: dict = {
        "arxiv_id": result.get_short_id(),
        "abs_url": result.entry_id,
        "pdf_url": result.pdf_url,
    }
    if extra:
        out.update(extra)
    for f in fields:
        out[f] = values[f]
    if files:
        out["files"] = files
    return out


# --------------------------------------------------------------------------- #
# Full-text downloads (.tex source archive only — no extraction)
# --------------------------------------------------------------------------- #

def _detect_extension(data: bytes) -> str:
    """Pick a sensible extension for raw arXiv e-print bytes."""
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:2] == b"\x1f\x8b":  # gzip; arXiv source is usually a .tar.gz
        return ".tar.gz"
    return ".bin"


def download_source(result: Result, out_dir: str, min_interval: float,
                    retries: int = NUM_RETRIES) -> str:
    """Download the raw .tex source archive, respecting the rate limit."""
    os.makedirs(out_dir, exist_ok=True)
    url = result.source_url()
    if not url:
        raise RuntimeError("no source_url for this result")
    base = os.path.join(out_dir, _safe_id(result))

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        _throttle(min_interval)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            path = base + _detect_extension(data)
            with open(path, "wb") as fh:
                fh.write(data)
            return path
        except urllib.error.HTTPError as err:
            last_err = err
            if attempt < retries:
                if err.code in (429, 503):
                    wait = _retry_after_seconds(err.headers, attempt, min_interval)
                    log(f"  HTTP {err.code} rate-limited "
                        f"(attempt {attempt}/{retries}); waiting {wait:.0f}s")
                else:
                    wait = min(MAX_RETRY_WAIT, min_interval * (2 ** attempt))
                    log(f"  download failed (attempt {attempt}/{retries}): "
                        f"HTTP {err.code}; retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
        except urllib.error.URLError as err:
            last_err = err
            if attempt < retries:
                wait = min(MAX_RETRY_WAIT, min_interval * (2 ** attempt))
                log(f"  download failed (attempt {attempt}/{retries}): "
                    f"{err.reason}; retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
    raise RuntimeError(f"source download failed after {retries} attempts: {url}") \
        from last_err


def fetch_fulltext(results: list[Result], mode: str, out_dir: str,
                   min_interval: float) -> dict[str, dict[str, str]]:
    """Download the .tex source for each result; return {short_id: {"source": path}}."""
    files: dict[str, dict[str, str]] = {}
    if mode == "none":
        return files
    src_dir = os.path.join(out_dir, "source")
    for i, result in enumerate(results, 1):
        sid = result.get_short_id()
        log(f"[{i}/{len(results)}] source for {sid}")
        try:
            path = download_source(result, src_dir, min_interval)
            files[sid] = {"source": path}
        except Exception as err:  # noqa: BLE001
            log(f"  source download failed: {err}")
    return files


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def resolve_fields(requested: list[str]) -> list[str]:
    """Expand 'all' and validate requested optional metadata fields."""
    if not requested or requested == ["all"]:
        return list(OPTIONAL_FIELDS)
    bad = [f for f in requested if f not in OPTIONAL_FIELDS]
    if bad:
        raise SystemExit(
            f"Unknown field(s): {', '.join(bad)}. "
            f"Choose from: {', '.join(OPTIONAL_FIELDS)} (or 'all')."
        )
    return requested


def write_metadata(results: list[Result], fields: list[str],
                   files: dict[str, dict[str, str]],
                   announced: dict[str, dict[str, str | None]],
                   args: argparse.Namespace, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    by_ids = bool(args.ids)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "id_list" if by_ids else "announcement",
        "ids": args.ids if by_ids else None,
        "categories": None if by_ids else args.categories,
        "announce_types": None if by_ids else args.announce_types,
        "fields": fields,
        "fulltext": args.fulltext,
        "count": len(results),
        "papers": [
            result_to_dict(
                r, fields, files.get(r.get_short_id()),
                extra=announced.get(_bare_id(r.get_short_id())),
            )
            for r in results
        ],
    }
    path = os.path.join(out_dir, "metadata.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull papers from arXiv's latest daily announcement.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--ids", "-i", nargs="+", default=None, metavar="ARXIV_ID",
        help="Fetch specific papers by arXiv id (e.g. 2401.12345 2402.06789v2). "
             "Overrides announcement selection; --categories/--announce-types "
             "are ignored.",
    )
    p.add_argument(
        "--categories", "-c", nargs="+", default=DEFAULT_CATEGORIES,
        help="arXiv categories whose latest announcement to pull, "
             "e.g. astro-ph.CO astro-ph.IM.",
    )
    p.add_argument(
        "--announce-types", nargs="+", choices=ANNOUNCE_TYPES,
        default=["new", "cross"], metavar="TYPE",
        help="Which announcement types to keep: new (originally submitted to a "
             "requested category), cross (cross-listed in), replace (revised "
             "re-announcement). Choices: " + ", ".join(ANNOUNCE_TYPES) + ".",
    )
    p.add_argument(
        "--max-results", "-n", type=int, default=400,
        help="Hard cap on number of papers kept from the announcement.",
    )
    p.add_argument(
        "--fields", "-f", nargs="+", default=["title", "authors", "abstract"],
        metavar="FIELD",
        help="Optional metadata fields to include, or 'all'. Choices: "
             + ", ".join(OPTIONAL_FIELDS)
             + ". (id, abs_url, pdf_url always included; announcement mode also "
             "adds announce_type and announced.)",
    )
    p.add_argument(
        "--fulltext", choices=["none", "tex"], default="none",
        help="Download the raw .tex source archive (tex) or nothing (none).",
    )
    p.add_argument(
        "--page-size", type=int, default=100,
        help="Results requested per API call (arXiv recommends <= a few hundred).",
    )
    p.add_argument(
        "--out", "-o", default=None,
        help="Output directory (default: ./arxiv_pull_<YYYY-MM-DD>).",
    )
    p.add_argument(
        "--min-interval", type=float, default=MIN_REQUEST_INTERVAL,
        help="Minimum seconds between arXiv requests (feed + API + downloads). "
             "arXiv's limit is one request per 3s; raise if you hit 429.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fields = resolve_fields(args.fields)
    out_dir = args.out or os.path.join(
        os.getcwd(), f"arxiv_pull_{dt.date.today().isoformat()}"
    )

    if args.ids:
        log(f"IDs           : {', '.join(args.ids)}")
    else:
        log(f"Categories    : {', '.join(args.categories)}")
        log(f"Announce types: {', '.join(args.announce_types)}")
    log(f"Fields        : {', '.join(fields)}")
    log(f"Full text     : {args.fulltext}")
    log(f"Output dir    : {out_dir}")

    client = make_client(page_size=args.page_size, delay_seconds=args.min_interval)
    announced: dict[str, dict[str, str | None]] = {}
    if args.ids:
        results = fetch_by_ids(client, args.ids)
    else:
        results, announced = fetch_announced(
            client=client,
            categories=args.categories,
            announce_types=args.announce_types,
            max_results=args.max_results,
        )
    log(f"Found {len(results)} paper(s).")

    files: dict[str, dict[str, str]] = {}
    if args.fulltext != "none" and results:
        files = fetch_fulltext(results, args.fulltext, out_dir, args.min_interval)

    meta_path = write_metadata(results, fields, files, announced, args, out_dir)
    log(f"Wrote metadata for {len(results)} paper(s) -> {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
