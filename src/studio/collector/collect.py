"""収集の実行エントリ（SPEC 7章 Stage 1 + M5-3a ネタストック化 + M5-3e 曜日ローテ）。

3ソースを集約 → 既知URLを除外 → LLM一括3軸採点+ジャンル分類 → 閾値以上を全件ストック →
鮮度切れを失効 → **当日ジャンル（曜日ローテ）のTOP3** を返す。
当日ジャンルの在庫が0件なら全体ランキングで代替する（投稿を止めない）。
ソースURLのない候補は破棄する。
"""

from __future__ import annotations

import logging
import sqlite3

from ..shared.config import settings
from ..shared.db import Database
from ..shared.genres import genre_for_today
from ..shared.llm import LLMClient
from .score import classify_topics, score_candidates
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


def todays_top(db: Database, top_n: int = 3) -> tuple[str, list[sqlite3.Row], bool]:
    """当日ジャンル（曜日ローテ・JST）とそのTOP{n}を返す。

    戻り値は (genre, rows, fallback)。当日ジャンルの在庫が0件のときは
    全体ランキングで代替し fallback=True を返す（投稿を止めない）。
    """
    genre = genre_for_today()
    rows = db.stock_ranking_by_category(genre, top_n)
    if rows:
        return genre, list(rows), False
    return genre, list(db.stock_ranking(top_n)), True


def _backfill_categories(db: Database, llm: LLMClient) -> None:
    """ジャンル未分類の旧ストックをまとめて後付け分類する（M5-3e移行。スコアは再利用）。

    失敗しても収集全体は止めず、次回実行に持ち越す。
    """
    rows = db.topics_missing_category()
    if not rows:
        return
    try:
        categories = classify_topics(llm, [(r["title"], r["summary"]) for r in rows])
    except Exception:
        logger.exception("旧ストック%d件のジャンル後付け分類に失敗（次回に持ち越し）", len(rows))
        return
    for r, category in zip(rows, categories, strict=True):
        db.set_topic_category(r["id"], category)
    logger.info("旧ストック%d件にジャンルを後付けしました", len(rows))


def run(db: Database, llm: LLMClient, top_n: int = 3) -> list[int]:
    """候補収集→3軸採点+ジャンル分類→ストック更新をしたうえで、当日ジャンルのTOP N件のidを返す。

    返るidは「今日集めたもの」ではなく鮮度減衰込みの当日ジャンル内ランキング。
    当日の新着が弱ければ、数日前の強いネタが選ばれる。
    """
    candidates = [c for c in collect_candidates() if not db.topic_url_known(c.source_url)]
    scores = score_candidates(llm, candidates)
    stocked = 0
    for c, score in zip(candidates, scores, strict=True):
        if score.total < STOCK_MIN_SCORE:
            continue
        # arXiv は常に論文なのでLLM分類より優先して paper 固定
        category = "paper" if c.source_type == "arxiv" else score.category
        db.insert_topic(
            source_url=c.source_url,
            source_type=c.source_type,
            title=c.title,
            summary=c.summary,
            relevance_score=score.total,
            catchy_score=score.catchy,
            impact_score=score.impact,
            useful_score=score.useful,
            category=category,
        )
        stocked += 1
    _backfill_categories(db, llm)
    expired = db.expire_stale_topics()
    logger.info(
        "ネタストック更新: 新着%d件収集 / %d件ストック追加 / %d件失効",
        len(candidates),
        stocked,
        expired,
    )
    genre, rows, fallback = todays_top(db, top_n)
    if fallback:
        logger.warning("当日ジャンル'%s'の在庫が0件のため全体ランキングで代替します", genre)
    logger.info("当日ジャンル'%s'のTOP%d を選抜（%d件）", genre, top_n, len(rows))
    return [r["id"] for r in rows]
