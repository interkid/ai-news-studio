"""LLM日次上限とscorerの選定ロジックのテスト（SPEC 12章・7章 Stage5）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.scorer.score import select_script
from studio.shared.db import Database
from studio.shared.llm import DailyLimitExceeded, LLMClient, MockProvider


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _sample_script_json(hook: str) -> str:
    return json.dumps(
        {
            "corner": "paper",
            "hook": hook,
            "exchanges": [
                {
                    "speaker": "fox",
                    "text": "精度94%、AIが医療診断を大きく変えます",
                    "emotion": "surprised",
                },
                {
                    "speaker": "rabbit",
                    "text": "えっ、お医者さんいらずになるの？",
                    "emotion": "curious",
                },
                {
                    "speaker": "fox",
                    "text": "画像診断で専門医に並ぶ正答率が出たんだ",
                    "emotion": "smug",
                },
                {
                    "speaker": "rabbit",
                    "text": "あなたの健康にも直結する大事な話だね",
                    "emotion": "normal",
                },
            ],
            "brolls": [{"prompt": "x", "caption_ja": "y", "start_line": 0}],
            "caption": "解説。※AI生成/出典はコメント欄",
            "source_url": "https://example.com/x",
            "fact_claims": ["a"],
            "visual_keyword": "医療AI診断",
        },
        ensure_ascii=False,
    )


def test_daily_limit_exceeded_stops_calls(tmp_path):
    db = _make_db(tmp_path)
    llm = LLMClient(db, MockProvider({"p": '{"a": 1}'}))
    for _ in range(3):
        db.log_llm_usage(
            purpose="p", model="m", input_tokens=1, output_tokens=1, est_cost_jpy=0.0
        )
    from studio.shared.config import settings

    original = settings.daily_llm_call_limit
    settings.daily_llm_call_limit = 3
    try:
        with pytest.raises(DailyLimitExceeded):
            llm.complete(purpose="p", system="s", user="u")
    finally:
        settings.daily_llm_call_limit = original
    db.close()


def test_select_script_picks_highest_score_and_rejects_rest(tmp_path):
    db = _make_db(tmp_path)
    tid = db.insert_topic(
        source_url="https://example.com/x", source_type="rss", title="t", summary="s"
    )
    ids = [
        db.insert_script(
            topic_id=tid,
            corner="paper",
            script_json=_sample_script_json(hook),
            fact_check_passed=True,
            status="draft",
        )
        for hook in ("案A", "案B", "案C")
    ]
    resp = json.dumps(
        {
            "scores": [
                {"index": 0, "quality_score": 70.0, "reason": "普通"},
                {"index": 1, "quality_score": 92.0, "reason": "刺さる"},
                {"index": 2, "quality_score": 60.0, "reason": "弱い"},
            ]
        }
    )
    llm = LLMClient(db, MockProvider({"scorer": resp}))
    winner = select_script(db, llm, ids)
    assert winner == ids[1]

    statuses = {
        r["id"]: r["status"] for r in db.conn.execute("SELECT id, status FROM scripts")
    }
    assert statuses[ids[1]] == "selected"
    assert statuses[ids[0]] == "rejected"
    assert statuses[ids[2]] == "rejected"
    db.close()


def test_select_script_empty_ids_returns_none(tmp_path):
    db = _make_db(tmp_path)
    llm = LLMClient(db, MockProvider({}))
    assert select_script(db, llm, []) is None
    db.close()
