"""M4: DB(videos/oauth_tokens)・tiktok.py・publish.py のテスト(SPEC 8章)。

ネットワークI/O(TikTok API・Cloudflare KV・R2)は行わず、純粋なロジックと
依存注入したモジュール関数(kv_client/tiktok_client)の呼び出しのみを検証する。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from studio import publish as publish_mod
from studio.publisher import tiktok as tiktok_client
from studio.publisher.tiktok import MAX_SINGLE_CHUNK_BYTES, TikTokNotConfigured, _chunk_ranges
from studio.shared.db import Database


def _db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


# --- db.py: videos / oauth_tokens ------------------------------------------


def test_video_r2_url_and_approval_lifecycle(tmp_path):
    db = _db(tmp_path)
    tid = db.insert_topic(
        source_url="https://example.com/x", source_type="rss", title="t", summary="s"
    )
    sid = db.insert_script(topic_id=tid, corner="paper", script_json="{}")
    db.insert_video(script_id=sid, file_path="out.mp4", duration_sec=12.0)

    db.set_video_r2_url(sid, "https://r2.example/out.mp4")
    row = db.get_video_by_script_id(sid)
    assert row["r2_url"] == "https://r2.example/out.mp4"
    assert row["approval_status"] == "pending"
    assert len(db.videos_awaiting_publish()) == 1

    db.set_video_approval_status(sid, "rejected", "bad hook")
    assert db.videos_awaiting_publish() == []
    row = db.get_video_by_script_id(sid)
    assert row["approval_status"] == "rejected"
    assert row["rejection_reason"] == "bad hook"
    db.close()


def test_set_video_published_removes_from_pending(tmp_path):
    db = _db(tmp_path)
    tid = db.insert_topic(
        source_url="https://example.com/x", source_type="rss", title="t", summary="s"
    )
    sid = db.insert_script(topic_id=tid, corner="paper", script_json="{}")
    db.insert_video(script_id=sid, file_path="out.mp4")

    db.set_video_published(sid, "publish123")
    row = db.get_video_by_script_id(sid)
    assert row["tiktok_publish_id"] == "publish123"
    assert row["posted_at"] is not None
    assert db.videos_awaiting_publish() == []
    db.close()


def test_oauth_token_upsert(tmp_path):
    db = _db(tmp_path)
    db.set_oauth_token(
        "tiktok", access_token="a1", refresh_token="r1", expires_at="2026-01-01T00:00:00+00:00"
    )
    assert db.get_oauth_token("tiktok")["access_token"] == "a1"

    db.set_oauth_token(
        "tiktok", access_token="a2", refresh_token="r2", expires_at="2026-02-01T00:00:00+00:00"
    )
    row = db.get_oauth_token("tiktok")
    assert row["access_token"] == "a2"
    assert row["refresh_token"] == "r2"
    db.close()


# --- publisher/tiktok.py ----------------------------------------------------


def test_chunk_ranges_single_chunk_for_small_file():
    assert _chunk_ranges(1000) == [(0, 999)]


def test_chunk_ranges_splits_large_file_without_gaps():
    total = MAX_SINGLE_CHUNK_BYTES + 1
    ranges = _chunk_ranges(total, chunk_size=10_000_000)
    assert ranges[0] == (0, 9_999_999)
    assert ranges[-1][1] == total - 1
    for (_s1, e1), (s2, _e2) in zip(ranges, ranges[1:], strict=False):
        assert s2 == e1 + 1


def test_build_authorize_url_requires_client_credentials(monkeypatch):
    from studio.shared.config import settings

    monkeypatch.setattr(settings, "tiktok_client_key", None)
    with pytest.raises(TikTokNotConfigured):
        tiktok_client.build_authorize_url("state123")


def test_get_access_token_uses_cached_token_when_not_expired(tmp_path, monkeypatch):
    db = _db(tmp_path)
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    db.set_oauth_token("tiktok", access_token="cached", refresh_token="r", expires_at=future)

    def _fail_refresh(refresh_token):
        raise AssertionError("有効なトークンがある間はリフレッシュされるべきではない")

    monkeypatch.setattr(tiktok_client, "refresh_access_token", _fail_refresh)
    assert tiktok_client.get_access_token(db) == "cached"
    db.close()


def test_get_access_token_refreshes_when_expired(tmp_path, monkeypatch):
    db = _db(tmp_path)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    db.set_oauth_token("tiktok", access_token="old", refresh_token="r-old", expires_at=past)

    def _fake_refresh(refresh_token):
        assert refresh_token == "r-old"
        return {"access_token": "new", "refresh_token": "r-new", "expires_in": 86400}

    monkeypatch.setattr(tiktok_client, "refresh_access_token", _fake_refresh)
    assert tiktok_client.get_access_token(db) == "new"
    assert db.get_oauth_token("tiktok")["refresh_token"] == "r-new"
    db.close()


# --- publish.py --------------------------------------------------------------


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


def _make_video(db: Database, tmp_path: Path, *, hook: str = "hook") -> int:
    tid = db.insert_topic(
        source_url="https://example.com/x", source_type="rss", title="t", summary="s"
    )
    sid = db.insert_script(topic_id=tid, corner="paper", script_json=_sample_script_json(hook))
    video_file = tmp_path / "out.mp4"
    video_file.write_bytes(b"fake-mp4")
    db.insert_video(script_id=sid, file_path=str(video_file), duration_sec=12.0)
    return sid


def test_publish_skips_when_pending(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sid = _make_video(db, tmp_path)

    monkeypatch.setattr(publish_mod.kv_client, "get_video_approval", lambda video_id: None)

    outcomes = publish_mod.run(db)
    assert [(o.script_id, o.status) for o in outcomes] == [(sid, "pending")]
    db.close()


def test_publish_marks_rejected_and_stops_polling(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sid = _make_video(db, tmp_path)

    monkeypatch.setattr(
        publish_mod.kv_client,
        "get_video_approval",
        lambda video_id: {"status": "rejected", "reason": "微妙"},
    )

    outcomes = publish_mod.run(db)
    assert outcomes[0].status == "rejected"
    row = db.get_video_by_script_id(sid)
    assert row["approval_status"] == "rejected"
    assert row["rejection_reason"] == "微妙"

    assert publish_mod.run(db) == []
    db.close()


def test_publish_uploads_and_notifies_on_approval(tmp_path, monkeypatch):
    db = _db(tmp_path)
    sid = _make_video(db, tmp_path)

    monkeypatch.setattr(
        publish_mod.kv_client, "get_video_approval", lambda video_id: {"status": "approved"}
    )
    monkeypatch.setattr(publish_mod.tiktok_client, "publish_to_inbox", lambda db, path: "pub-123")
    notified = {}

    def _fake_notify(*, script, publish_id):
        notified["hook"] = script.hook
        notified["publish_id"] = publish_id

    monkeypatch.setattr(publish_mod, "notify_publish_complete", _fake_notify)

    outcomes = publish_mod.run(db)
    assert outcomes[0].status == "published"
    assert notified == {"hook": "hook", "publish_id": "pub-123"}

    row = db.get_video_by_script_id(sid)
    assert row["tiktok_publish_id"] == "pub-123"
    assert row["posted_at"] is not None
    db.close()
