"""ネタストック（M5-3a）のテスト: 3軸採点・鮮度減衰・失効・重複排除・ランキング。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from studio.collector.collect import run as collect_run
from studio.collector.score import TopicScore
from studio.notifier.line import build_ranking_flex
from studio.shared.db import Database
from studio.shared.llm import LLMClient, MockProvider


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _insert(db: Database, url: str, score: float, days_ago: float = 0.0) -> int:
    tid = db.insert_topic(
        source_url=url,
        source_type="rss",
        title=f"t-{url}",
        summary=None,
        relevance_score=score,
        catchy_score=score,
        impact_score=score,
        useful_score=score,
    )
    if days_ago:
        collected = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
        db.conn.execute("UPDATE topics SET collected_at = ? WHERE id = ?", (collected, tid))
        db.conn.commit()
    return tid


def test_topic_score_weighted_total():
    s = TopicScore(catchy=100, impact=50, useful=0)
    assert s.total == 100 * 0.4 + 50 * 0.3


def test_stock_ranking_applies_freshness_decay(tmp_path):
    db = _make_db(tmp_path)
    fresh = _insert(db, "https://a.example/1", score=70.0, days_ago=0)
    # 80点だが13日前 → 減衰 2.0*(13-3)=20点 → 実効60点で新しい70点に負ける
    _insert(db, "https://a.example/2", score=80.0, days_ago=13)
    rows = db.stock_ranking(10)
    assert [r["id"] for r in rows][0] == fresh
    assert rows[1]["effective_score"] < rows[0]["effective_score"]
    db.close()


def test_expire_stale_topics(tmp_path):
    db = _make_db(tmp_path)
    _insert(db, "https://a.example/old", score=90.0, days_ago=31)
    keep = _insert(db, "https://a.example/new", score=50.0, days_ago=5)
    assert db.expire_stale_topics() == 1
    rows = db.stock_ranking(10)
    assert [r["id"] for r in rows] == [keep]
    db.close()


def test_collect_run_dedups_and_stocks(tmp_path, monkeypatch):
    db = _make_db(tmp_path)
    _insert(db, "https://known.example/x", score=60.0)

    from studio.collector import collect as collect_mod
    from studio.collector.sources import Candidate

    candidates = [
        Candidate(
            source_url="https://known.example/x", source_type="rss", title="既知", summary=None
        ),
        Candidate(
            source_url="https://new.example/y", source_type="rss", title="新規", summary=None
        ),
        Candidate(
            source_url="https://weak.example/z", source_type="rss", title="低得点", summary=None
        ),
    ]
    monkeypatch.setattr(collect_mod, "collect_candidates", lambda: candidates)

    # 既知URLは採点前に除外されるので、採点対象は新規2件(index 0=新規, 1=低得点)
    resp = json.dumps(
        {
            "scores": [
                {"index": 0, "catchy": 80, "impact": 80, "useful": 80},
                {"index": 1, "catchy": 10, "impact": 10, "useful": 10},
            ]
        }
    )
    llm = LLMClient(db, MockProvider({"collector_score": resp}))
    ids = collect_run(db, llm, top_n=3)

    urls = {
        r["source_url"]: r
        for r in db.conn.execute("SELECT * FROM topics").fetchall()
    }
    assert "https://new.example/y" in urls  # 閾値以上 → ストック
    assert "https://weak.example/z" not in urls  # 閾値未満 → 破棄
    assert urls["https://new.example/y"]["catchy_score"] == 80
    # 返り値はストック全体のランキング（既知の60点も含む）
    assert urls["https://new.example/y"]["id"] == ids[0]
    assert len(ids) == 2
    db.close()


def test_build_ranking_flex_contains_titles_and_scores(tmp_path):
    db = _make_db(tmp_path)
    _insert(db, "https://a.example/1", score=88.0)
    flex = build_ranking_flex(db.stock_ranking(10))
    dumped = json.dumps(flex, ensure_ascii=False)
    assert "t-https://a.example/1" in dumped
    assert "88点" in dumped
    db.close()
