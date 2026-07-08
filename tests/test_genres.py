"""ジャンル週間ローテーション（M5-3e）のテスト: 曜日対応・JST境界・corner対応表。"""

from __future__ import annotations

import datetime as dt

from studio.shared.genres import (
    GENRE_LABELS,
    GENRE_TO_CORNER,
    GENRES,
    WEEKLY_ROTATION,
    corner_for_genre,
    genre_for_date,
    genre_for_today,
    genre_for_tomorrow,
    normalize_genre,
)

VALID_CORNERS = {"paper", "news", "society", "work"}


def test_rotation_covers_all_genres_in_a_week():
    assert len(WEEKLY_ROTATION) == 7
    assert set(WEEKLY_ROTATION) == set(GENRES)  # 1週間で全ジャンルを1周
    assert WEEKLY_ROTATION.count("hot_news") == 2  # ホットニュースのみ週2回


def test_genre_for_date_weekday_mapping():
    monday = dt.date(2026, 7, 6)
    assert genre_for_date(monday) == "hot_news"
    assert genre_for_date(dt.date(2026, 7, 9)) == "paper"  # 木曜
    assert genre_for_date(dt.date(2026, 7, 12)) == "hot_news"  # 日曜


def test_genre_for_today_uses_jst_boundary():
    # UTC 7/8(水) 23:30 は JST では 7/9(木) 08:30 → paper になること
    utc_wed_night = dt.datetime(2026, 7, 8, 23, 30, tzinfo=dt.UTC)
    assert genre_for_today(utc_wed_night) == "paper"
    # 同時刻をJSTのまま渡せば水曜 → workflow_case
    jst_wed_night = dt.datetime(2026, 7, 8, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=9)))
    assert genre_for_today(jst_wed_night) == "workflow_case"


def test_genre_for_tomorrow():
    utc_tue = dt.datetime(2026, 7, 7, 3, 0, tzinfo=dt.UTC)  # JST 7/7(火)
    assert genre_for_today(utc_tue) == "tech_update"
    assert genre_for_tomorrow(utc_tue) == "workflow_case"


def test_corner_mapping_covers_all_genres():
    for genre in GENRES:
        assert GENRE_TO_CORNER[genre] in VALID_CORNERS
        assert corner_for_genre(genre) == GENRE_TO_CORNER[genre]
    # 未分類・未知はNone（LLM判定値を残すシグナル）
    assert corner_for_genre(None) is None
    assert corner_for_genre("unknown") is None


def test_labels_cover_all_genres():
    assert set(GENRE_LABELS) == set(GENRES)


def test_normalize_genre():
    assert normalize_genre("paper") == "paper"
    assert normalize_genre("なにこれ") == "hot_news"
    assert normalize_genre(None) == "hot_news"
    assert normalize_genre(" vision ") == "vision"
