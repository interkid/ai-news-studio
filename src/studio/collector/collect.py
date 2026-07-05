"""収集の実行エントリ（SPEC 7章 Stage 1）。

3ソースを集約 → LLM一括採点 → 上位3件を topics に保存。
ソースURLのない候補は破棄する。
"""

from __future__ import annotations

import logging

from ..shared.config import settings
from ..shared.db import Database
from ..shared.llm import LLMClient
from .score import score_candidates
from .sources import Candidate, fetch_arxiv, fetch_hn, fetch_rss

logger = logging.getLogger(__name__)


def _safe(fn, *args, **kwargs) -> list[Candidate]:
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("収集ソース %s の取得に失敗（skip）", getattr(fn, "__name__", fn))
        return []


def collect_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    candidates += _safe(fetch_arxiv)
    candidates += _safe(fetch_rss, settings.rss_feeds)
    candidates += _safe(fetch_hn)
    return [c for c in candidates if c.source_url]


def run(db: Database, llm: LLMClient, top_n: int = 3) -> list[int]:
    """候補収集→採点→上位N件を topics に保存し、topic idの一覧を返す。"""
    candidates = collect_candidates()
    scores = score_candidates(llm, candidates)
    ranked = sorted(zip(candidates, scores, strict=True), key=lambda cs: cs[1], reverse=True)
    ids: list[int] = []
    for c, score in ranked[:top_n]:
        tid = db.insert_topic(
            source_url=c.source_url,
            source_type=c.source_type,
            title=c.title,
            summary=c.summary,
            relevance_score=score,
        )
        ids.append(tid)
    return ids
