"""収集の実行エントリ（SPEC 7章 Stage 1 + M5-3a ネタストック化）。

3ソースを集約 → 既知URLを除外 → LLM一括3軸採点 → 閾値以上を全件ストックに保存 →
鮮度切れを失効 → ストック全体の実効スコア(鮮度減衰込み)ランキングを返す。
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


# これ未満の加重合計はストックに入れない（ノイズでDBを太らせない）
STOCK_MIN_SCORE = 40.0


def run(db: Database, llm: LLMClient, top_n: int = 3) -> list[int]:
    """候補収集→3軸採点→ストック更新をしたうえで、ストック全体の上位N件のidを返す。

    返るidは「今日集めたもの」ではなく鮮度減衰込みのストック全体ランキング。
    当日の新着が弱ければ、数日前の強いネタが選ばれる。
    """
    candidates = [c for c in collect_candidates() if not db.topic_url_known(c.source_url)]
    scores = score_candidates(llm, candidates)
    stocked = 0
    for c, score in zip(candidates, scores, strict=True):
        if score.total < STOCK_MIN_SCORE:
            continue
        db.insert_topic(
            source_url=c.source_url,
            source_type=c.source_type,
            title=c.title,
            summary=c.summary,
            relevance_score=score.total,
            catchy_score=score.catchy,
            impact_score=score.impact,
            useful_score=score.useful,
        )
        stocked += 1
    expired = db.expire_stale_topics()
    logger.info(
        "ネタストック更新: 新着%d件収集 / %d件ストック追加 / %d件失効",
        len(candidates),
        stocked,
        expired,
    )
    return [r["id"] for r in db.stock_ranking(top_n)]
