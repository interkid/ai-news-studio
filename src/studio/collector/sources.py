"""3ソース(arXiv/RSS/Hacker News)からの候補収集（SPEC 7章 Stage 1）。

ソースURLのない候補は破棄する。個々のフィード取得失敗は当該ソースのみ
skipし、収集全体は止めない（daily実行を壊さないための方針）。
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

ARXIV_CATEGORIES = ["cs.AI", "cs.CL", "cs.LG"]
ARXIV_API = "http://export.arxiv.org/api/query"
HN_SEARCH_API = "https://hn.algolia.com/api/v1/search"

# 3ソース共通の鮮度ウィンドウ。毎日インパクトのある論文/記事が出るとは限らないため、
# 1日単位ではなく1か月以内で統一する。
COLLECT_WINDOW_HOURS = 24 * 30

_retry = retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))


@dataclass
class Candidate:
    source_url: str
    source_type: str  # arxiv | rss | hn
    title: str
    summary: str | None


def _entry_time(entry: dict) -> dt.datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(parsed), tz=dt.UTC)


@_retry
def fetch_arxiv(hours: int = COLLECT_WINDOW_HOURS, max_results: int = 20) -> list[Candidate]:
    query = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    resp = httpx.get(ARXIV_API, params=params, timeout=20.0, follow_redirects=True)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
    out: list[Candidate] = []
    for e in feed.entries:
        t = _entry_time(e)
        if t is not None and t < cutoff:
            continue
        link = e.get("link") or e.get("id")
        if not link:
            continue
        out.append(
            Candidate(
                source_url=link,
                source_type="arxiv",
                title=(e.get("title") or "").strip(),
                summary=(e.get("summary") or "").strip()[:500],
            )
        )
    return out


def fetch_rss(feeds: list[str], hours: int = COLLECT_WINDOW_HOURS) -> list[Candidate]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
    out: list[Candidate] = []
    for url in feeds:
        try:
            resp = _retry(httpx.get)(url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception:
            continue  # このフィードのみskip。収集全体は継続する
        for e in feed.entries:
            t = _entry_time(e)
            if t is not None and t < cutoff:
                continue
            link = e.get("link")
            if not link:
                continue
            out.append(
                Candidate(
                    source_url=link,
                    source_type="rss",
                    title=(e.get("title") or "").strip(),
                    summary=(e.get("summary") or "").strip()[:500],
                )
            )
    return out


@_retry
def fetch_hn(
    query: str = "AI",
    min_points: int = 100,
    hits: int = 20,
    hours: int = COLLECT_WINDOW_HOURS,
) -> list[Candidate]:
    # Algolia HN Search API は points への numericFilters を許可していないため、
    # 通常検索を取得してから client 側で points>min_points・鮮度を絞り込む。
    params = {"query": query, "tags": "story", "hitsPerPage": hits}
    resp = httpx.get(HN_SEARCH_API, params=params, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
    out: list[Candidate] = []
    for hit in data.get("hits", []):
        url = hit.get("url")
        points = hit.get("points") or 0
        created_at_i = hit.get("created_at_i")
        if not url or points <= min_points:
            continue  # Ask HN等、外部URLのない投稿は破棄。スコア不足もskip
        if created_at_i is not None:
            created = dt.datetime.fromtimestamp(created_at_i, tz=dt.UTC)
            if created < cutoff:
                continue  # 過去にバズった古い記事は鮮度切れでskip
        out.append(
            Candidate(source_url=url, source_type="hn", title=hit.get("title") or "", summary=None)
        )
    return out
