"""
Blog Posting Schema Markup Generator (v2 — Python-native)
----------------------------------------------------------
Instead of asking an LLM to write JSON-LD, we extract the data with BeautifulSoup and construct the schema as Python dicts, then serialize with json.dumps(). The result is always valid JSON, deterministic, and free.

Flow for each URL in URLS_TO_PROCESS:
  1. Fetch the HTML (requests, browser-like headers)
  2. Parse with BeautifulSoup + lxml
  3. Extract metadata (canonical, title, description, dates, author, images,
     social profiles, body text, FAQ candidates)
  4. Build five JSON-LD objects: WebSite, BlogPosting, Organization,
     BreadcrumbList, and (if found) FAQPage
  5. [Optional] Use Gemini 2.5 Flash ONLY to generate answers for detected FAQ
     questions — enable via USE_GEMINI_FOR_FAQ = True
  6. Write each schema as its own <script type="application/ld+json"> block
     to output/<slug>-schema.txt

Usage:
    1. pip install -r requirements_v2.txt
    2. Paste your URL(s) into URLS_TO_PROCESS below
    3. (optional) put GEMINI_API_KEY in a .env file for FAQ answer generation
    4. python blog_schema_builder_v2.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# trafilatura is used for clean article-body extraction; it's optional.
try:
    import trafilatura  # type: ignore
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

load_dotenv()

# --- URL(s) to process -------------------------------------------------------
# Paste the URL(s) you want schema markup for. Add as many as you like.
# Optionally pair each URL with an author profile URL (used for the BlogPosting
# author @id). Leave author_url as "" to let the script auto-detect it.
# add author name
URLS_TO_PROCESS: list[dict[str, str]] = [
    {
        "url": "https://www.savvywealth.com/blog-posts/the-ai-bubble-the-ice-maker",
        "author_name": "Lindsey K. Leaverton"
        "author_url": "https://www.savvywealth.com/advisor/lindsey-k-leaverton",
    },
    {
        "url": "https://www.savvywealth.com/blog-posts/construction-and-renovation-financing-in-an-era-of-economic-fragility",
        "author_name": "David Gottlieb"
        "author_url": "https://www.savvywealth.com/advisor/david-gottlieb",
    },
    # Add more entries like:
    # {"url": "https://www.savvywealth.com/blog/another-post", "author_url": ""},
]

# --- Organization-level constants (Savvy Wealth defaults) --------------------
ORG_NAME = "Savvy Wealth"
ORG_URL = "https://www.savvywealth.com/"
ORG_ID = "https://www.savvywealth.com/#organization"
WEBSITE_ID = "https://www.savvywealth.com/#website"
ORG_LOGO = (
    "https://cdn.prod.website-files.com/6479cdbae84fd9792129c576/"
    "647dd6624b8fd164bb0f9637_Savvy%20Logo.svg"
)
ORG_SAME_AS = [
    "https://www.linkedin.com/company/savvywealth",
    "https://x.com/SavvyWealthInc",
    "https://www.facebook.com/SavvyWealthInc",
    "https://www.instagram.com/savvywealth_/",
]
ORG_CONTACT_POINT = {
    "@type": "ContactPoint",
    "telephone": "+1-833-745-6789",
    "contactType": "Customer Service",
    "areaServed": "US",
    "availableLanguage": ["English"],
}
BREADCRUMB_HOME = {"name": "Home", "url": "https://www.savvywealth.com"}
BREADCRUMB_BLOG = {"name": "Blog", "url": "https://www.savvywealth.com/blog"}

# --- HTTP settings -----------------------------------------------------------
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
HTTP_TIMEOUT_SECONDS = 30

# --- Optional Gemini FAQ-answer generation -----------------------------------
USE_GEMINI_FOR_FAQ = False  # set True to have Gemini answer detected FAQ Qs
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

# --- Output folder -----------------------------------------------------------
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# DATA CLASS — one structured container for everything we pull from a page
# =============================================================================
@dataclass
class PageData:
    url: str
    canonical_url: str = ""
    slug: str = "page"
    title: str = ""
    description: str = ""
    h1: str = ""
    og_image: str = ""
    site_name: str = ""
    date_published: str = ""   # ISO 8601 (e.g., "2026-01-15T08:00:00+00:00")
    date_modified: str = ""
    author_name: str = ""
    author_url: str = ""
    body_text: str = ""        # cleaned article body (up to 8000 chars)
    faq_pairs: list[tuple[str, str]] = field(default_factory=list)


# =============================================================================
# STEP 1 — FETCH
# =============================================================================
def fetch_html(url: str) -> str:
    """Download HTML with browser-like headers. Raises on HTTP error."""
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    # Respect server-declared encoding where available; fall back to UTF-8
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


# =============================================================================
# STEP 2 — EXTRACT
# =============================================================================
def _meta(soup: BeautifulSoup, **attrs: str) -> str:
    """Small helper: return the `content` of the first <meta ...> that matches."""
    tag = soup.find("meta", attrs=attrs)
    return (tag.get("content") or "").strip() if tag else ""


def _normalize_date(raw: str) -> str:
    """Accept common date formats and return ISO-8601; empty string if unparseable."""
    if not raw:
        return ""
    # Most sites already use ISO 8601 (e.g., "2025-06-14T10:30:00+00:00");
    # if it parses with fromisoformat, we're done. Otherwise try a few fallbacks.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return ""


def _extract_author_from_jsonld(soup: BeautifulSoup) -> tuple[str, str]:
    """Look inside existing <script type='application/ld+json'> for an author."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # JSON-LD can be a single object, a list, or a @graph wrapper.
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            candidates = data["@graph"]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            author = item.get("author")
            if isinstance(author, dict):
                return author.get("name", ""), author.get("url", "")
            if isinstance(author, list) and author and isinstance(author[0], dict):
                return author[0].get("name", ""), author[0].get("url", "")
    return "", ""


# =============================================================================
# STEP 2 (continued) — full page extraction helpers
# =============================================================================
def _slug_from_url(url: str) -> str:
    parts = urlparse(url).path.rstrip("/").rsplit("/", 1)
    return parts[-1] if parts[-1] else "page"


def _extract_faq_candidates(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Heuristically find Q&A pairs on the page."""
    pairs: list[tuple[str, str]] = []

    # Pattern 1: <details><summary>Q</summary>A</details>
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        q = summary.get_text(strip=True)
        a_parts = []
        for sib in summary.next_siblings:
            text = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib).strip()
            if text:
                a_parts.append(text)
        a = " ".join(a_parts)
        if q and a:
            pairs.append((q, a))

    # Pattern 2: headings containing "?" in a FAQ-like section
    if not pairs:
        for heading in soup.find_all(["h2", "h3"]):
            text = heading.get_text(strip=True)
            if "?" in text:
                answer_parts = []
                for sib in heading.next_siblings:
                    if hasattr(sib, "name") and sib.name in ("h2", "h3", "h4"):
                        break
                    t = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else ""
                    if t:
                        answer_parts.append(t)
                answer = " ".join(answer_parts)[:500]
                if answer:
                    pairs.append((text, answer))

    return pairs[:8]


def extract_page_data(url: str, author_url_override: str, soup: BeautifulSoup, raw_html: str) -> "PageData":
    page = PageData(url=url)

    # Canonical URL
    canonical_tag = soup.find("link", rel="canonical")
    page.canonical_url = (
        (canonical_tag["href"] if canonical_tag and canonical_tag.get("href") else url).strip()
    )

    # Slug
    page.slug = _slug_from_url(page.canonical_url or url)

    # Title
    page.title = (
        _meta(soup, property="og:title")
        or _meta(soup, name="twitter:title")
        or (soup.title.get_text(strip=True) if soup.title else "")
    )

    # Description
    page.description = (
        _meta(soup, property="og:description")
        or _meta(soup, name="description")
        or _meta(soup, name="twitter:description")
    )

    # H1
    h1_tag = soup.find("h1")
    page.h1 = h1_tag.get_text(strip=True) if h1_tag else ""

    # OG image
    page.og_image = (
        _meta(soup, property="og:image")
        or _meta(soup, name="twitter:image")
    )

    # Site name
    page.site_name = _meta(soup, property="og:site_name") or ORG_NAME

    # Dates — try Open Graph / article meta first, then existing JSON-LD
    raw_pub = (
        _meta(soup, property="article:published_time")
        or _meta(soup, property="og:article:published_time")
    )
    raw_mod = (
        _meta(soup, property="article:modified_time")
        or _meta(soup, property="og:article:modified_time")
    )

    if not raw_pub:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text() or "")
            except json.JSONDecodeError:
                continue
            items = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and "@graph" in data:
                items = data["@graph"]
            for item in items:
                if isinstance(item, dict):
                    raw_pub = raw_pub or item.get("datePublished", "")
                    raw_mod = raw_mod or item.get("dateModified", "")
            if raw_pub:
                break

    page.date_published = _normalize_date(raw_pub)
    page.date_modified = _normalize_date(raw_mod) or page.date_published

    # Author
    jld_author_name, jld_author_url = _extract_author_from_jsonld(soup)
    page.author_name = jld_author_name or _meta(soup, name="author") or ORG_NAME
    page.author_url = author_url_override or jld_author_url or ""

    # Body text — prefer trafilatura for clean extraction
    if HAS_TRAFILATURA:
        extracted = trafilatura.extract(raw_html, include_comments=False, include_tables=False)
        page.body_text = (extracted or "")[:8000]
    else:
        article = soup.find("article") or soup.find("main") or soup.body
        if article:
            page.body_text = article.get_text(" ", strip=True)[:8000]

    # FAQ candidates
    page.faq_pairs = _extract_faq_candidates(soup)

    return page


# =============================================================================
# STEP 3 — OPTIONAL GEMINI FAQ ANSWERING
# =============================================================================
def _gemini_answer(question: str, context: str) -> str:
    """Call Gemini 2.5 Flash to generate a concise answer for a FAQ question."""
    if not GEMINI_API_KEY:
        return ""
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "You are an expert financial advisor writing FAQ answers for a website. "
                            "Using the article context below, write a concise, helpful answer (2-4 sentences) "
                            "to the following question. Do not include the question in your answer.\n\n"
                            f"Context:\n{context[:3000]}\n\nQuestion: {question}"
                        )
                    }
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.3},
    }
    try:
        resp = requests.post(
            GEMINI_URL,
            json=payload,
            params={"key": GEMINI_API_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as exc:
        print(f"    [Gemini] Warning: {exc}", file=sys.stderr)
        return ""


def enrich_faq_with_gemini(page: "PageData") -> None:
    """Replace short placeholder answers with Gemini-generated ones if enabled."""
    if not USE_GEMINI_FOR_FAQ or not page.faq_pairs:
        return
    print(f"  [Gemini] Generating answers for {len(page.faq_pairs)} FAQ question(s)…")
    enriched = []
    for q, a in page.faq_pairs:
        answer = a if len(a) > 80 else _gemini_answer(q, page.body_text)
        enriched.append((q, answer or a))
        time.sleep(0.5)
    page.faq_pairs = enriched


# =============================================================================
# STEP 4 — BUILD SCHEMA OBJECTS
# =============================================================================
def build_website_schema() -> dict[str, Any]:
    return {
        "@type": "WebSite",
        "@id": WEBSITE_ID,
        "url": ORG_URL,
        "name": ORG_NAME,
    }


def build_organization_schema() -> dict[str, Any]:
    return {
        "@type": "Organization",
        "@id": ORG_ID,
        "name": ORG_NAME,
        "url": ORG_URL,
        "logo": {
            "@type": "ImageObject",
            "url": ORG_LOGO,
        },
        "sameAs": ORG_SAME_AS,
        "contactPoint": [ORG_CONTACT_POINT],
    }


def build_breadcrumb_schema(page: "PageData") -> dict[str, Any]:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": BREADCRUMB_HOME["name"],
                "item": BREADCRUMB_HOME["url"],
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": BREADCRUMB_BLOG["name"],
                "item": BREADCRUMB_BLOG["url"],
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": page.title or page.slug,
                "item": page.canonical_url or page.url,
            },
        ],
    }


def build_blogposting_schema(page: "PageData") -> dict[str, Any]:
    post_url = page.canonical_url or page.url

    # Author: Person with @id pointing to their profile page, or fall back to org
    if page.author_url:
        author: dict[str, Any] = {
            "@type": "Person",
            "@id": f"{page.author_url.rstrip('/')}#person",
        }
    else:
        author = {
            "@type": "Organization",
            "@id": ORG_ID,
        }

    schema: dict[str, Any] = {
        "@type": "BlogPosting",
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": post_url,
        },
        "headline": page.title,
        "url": post_url,
    }
    if page.date_published:
        schema["datePublished"] = page.date_published
    if page.date_modified:
        schema["dateModified"] = page.date_modified
    if page.description:
        schema["description"] = page.description
    if page.body_text:
        schema["articleBody"] = page.body_text
    if page.og_image:
        schema["image"] = {"@type": "ImageObject", "url": page.og_image}
    schema["author"] = author
    schema["publisher"] = {"@type": "Organization", "@id": ORG_ID}
    return schema


def build_faq_schema(faq_pairs: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faq_pairs
            if q and a
        ],
    }


def wrap_jsonld(schema_obj: dict[str, Any]) -> str:
    """Serialize a schema dict as a <script type="application/ld+json"> block."""
    inner = json.dumps(
        {"@context": "https://schema.org", **schema_obj},
        indent=2,
        ensure_ascii=False,
    )
    return f'<script type="application/ld+json">\n{inner}\n</script>'


# =============================================================================
# STEP 5 — PROCESS ONE URL
# =============================================================================
def process_entry(entry: dict[str, str]) -> None:
    url = entry.get("url", "").strip()
    author_url_override = entry.get("author_url", "").strip()
    if not url:
        print("  [skip] Empty URL in entry.", file=sys.stderr)
        return

    print(f"\n{'=' * 60}")
    print(f"Processing: {url}")
    print("=" * 60)

    print("  Fetching HTML…")
    try:
        raw_html = fetch_html(url)
    except Exception as exc:
        print(f"  [error] Failed to fetch: {exc}", file=sys.stderr)
        return

    soup = BeautifulSoup(raw_html, "lxml")

    print("  Extracting metadata…")
    page = extract_page_data(url, author_url_override, soup, raw_html)

    enrich_faq_with_gemini(page)

    schemas = [
        build_website_schema(),
        build_blogposting_schema(page),
        build_organization_schema(),
        build_breadcrumb_schema(page),
    ]
    if page.faq_pairs:
        schemas.append(build_faq_schema(page.faq_pairs))

    output_text = "\n\n".join(wrap_jsonld(s) for s in schemas)

    out_file = OUTPUT_DIR / f"{page.slug}-schema.txt"
    out_file.write_text(output_text, encoding="utf-8")

    print(f"  Written  -> {out_file}")
    print(f"  Title    : {page.title}")
    print(f"  Author   : {page.author_name}")
    if page.date_published:
        print(f"  Published: {page.date_published}")
    if page.faq_pairs:
        print(f"  FAQ Q&As : {len(page.faq_pairs)}")


# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    if not URLS_TO_PROCESS:
        print("No URLs configured in URLS_TO_PROCESS. Add at least one entry and re-run.")
        return
    for entry in URLS_TO_PROCESS:
        process_entry(entry)
    print("\nDone. Output files are in the 'output/' folder.")


if __name__ == "__main__":
    main()