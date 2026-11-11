"""Pengambil data dari Google News (RSS) dan Reddit (JSON publik).

Hanya memakai pustaka standar Python agar ringan.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "isu-populer-app/1.0 (aplikasi pribadi perangkum berita)"
TIMEOUT = 15

# Pengaturan wilayah/bahasa Google News
REGIONS = {
    "Indonesia (Bahasa Indonesia)": {"hl": "id", "gl": "ID", "ceid": "ID:id", "lang": "id"},
    "Malaysia (Bahasa Melayu)": {"hl": "ms", "gl": "MY", "ceid": "MY:ms", "lang": "id"},
    "Amerika Serikat (English)": {"hl": "en-US", "gl": "US", "ceid": "US:en", "lang": "en"},
    "Inggris (English)": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en", "lang": "en"},
    "Singapura (English)": {"hl": "en-SG", "gl": "SG", "ceid": "SG:en", "lang": "en"},
}

# Rentang waktu: (operator Google News, parameter Reddit)
TIME_RANGES = {
    "24 jam terakhir": ("1d", "day"),
    "7 hari terakhir": ("7d", "week"),
    "30 hari terakhir": ("30d", "month"),
}


@dataclass
class Item:
    title: str
    link: str
    source: str
    platform: str  # "Google News" atau "Reddit"
    published: datetime | None = None
    snippet: str = ""
    score: int = 0  # upvote Reddit
    comments: int = 0
    extra: dict = field(default_factory=dict)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_google_news(query: str, region: str, time_range: str, limit: int = 100) -> list[Item]:
    cfg = REGIONS[region]
    when = TIME_RANGES[time_range][0]
    params = {
        "q": f"{query} when:{when}",
        "hl": cfg["hl"],
        "gl": cfg["gl"],
        "ceid": cfg["ceid"],
    }
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    root = ET.fromstring(_get(url))

    items: list[Item] = []
    for node in root.iter("item"):
        raw_title = (node.findtext("title") or "").strip()
        source_el = node.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        # Judul Google News berformat "Judul berita - Nama Media"
        title = raw_title
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        elif " - " in title:
            title, _, maybe_src = title.rpartition(" - ")
            source = source or maybe_src

        published = None
        pub = node.findtext("pubDate")
        if pub:
            try:
                published = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                pass

        desc = _strip_html(node.findtext("description") or "")
        # Deskripsi Google News biasanya hanya mengulang judul; pakai jika berbeda
        snippet = desc if desc and title.lower() not in desc.lower() else ""

        items.append(
            Item(
                title=title.strip(),
                link=(node.findtext("link") or "").strip(),
                source=source or "Google News",
                platform="Google News",
                published=published,
                snippet=snippet,
            )
        )
        if len(items) >= limit:
            break
    return items


def fetch_reddit(query: str, time_range: str, limit: int = 50) -> list[Item]:
    """Coba API JSON (ada upvote & komentar); jika diblokir, pakai RSS Reddit."""
    try:
        return _fetch_reddit_json(query, time_range, limit)
    except Exception:  # noqa: BLE001 - Reddit sering memblokir JSON tanpa login
        return _fetch_reddit_rss(query, time_range, limit)


def _fetch_reddit_rss(query: str, time_range: str, limit: int) -> list[Item]:
    t = TIME_RANGES[time_range][1]
    params = {"q": query, "sort": "top", "t": t, "limit": str(limit)}
    url = "https://www.reddit.com/search.rss?" + urllib.parse.urlencode(params)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(_get(url))

    items: list[Item] = []
    for entry in root.findall("a:entry", ns):
        link_el = entry.find("a:link", ns)
        cat_el = entry.find("a:category", ns)
        sub = cat_el.get("term", "?") if cat_el is not None else "?"
        published = None
        stamp = entry.findtext("a:published", default="", namespaces=ns) or entry.findtext(
            "a:updated", default="", namespaces=ns
        )
        if stamp:
            try:
                published = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                pass
        content = _strip_html(entry.findtext("a:content", default="", namespaces=ns))
        # Buang teks bawaan RSS seperti "submitted by /u/xxx [link] [comments]"
        content = re.sub(r"submitted by\s+/u/\S+.*$", "", content).strip()
        items.append(
            Item(
                title=(entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                link=link_el.get("href", "") if link_el is not None else "",
                source="r/" + sub,
                platform="Reddit",
                published=published,
                snippet=content[:400],
            )
        )
    return items[:limit]


def _fetch_reddit_json(query: str, time_range: str, limit: int) -> list[Item]:
    t = TIME_RANGES[time_range][1]
    params = {"q": query, "sort": "top", "t": t, "limit": str(limit), "raw_json": "1"}
    url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url))

    items: list[Item] = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        if d.get("over_18"):
            continue
        selftext = re.sub(r"\s+", " ", d.get("selftext") or "").strip()
        items.append(
            Item(
                title=(d.get("title") or "").strip(),
                link="https://www.reddit.com" + d.get("permalink", ""),
                source="r/" + d.get("subreddit", "?"),
                platform="Reddit",
                published=datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc),
                snippet=selftext[:400],
                score=int(d.get("score") or 0),
                comments=int(d.get("num_comments") or 0),
            )
        )
    return items
