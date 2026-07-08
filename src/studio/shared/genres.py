"""ジャンル週間ローテーションの定義（M5-3e）。

ネタは6ジャンルに分類してストックし、台本を書くジャンルは曜日で1つに固定する
（1週間で全ジャンルを1周。ホットニュースのみ週2回）。
曜日の判定は**JST**で行う（LLM日次上限のUTC境界とは別物。混同しないこと）。
"""

from __future__ import annotations

import datetime as dt

JST = dt.timezone(dt.timedelta(hours=9))

# ジャンルID（topics.category に保存する値）
GENRES = ("hot_news", "tech_update", "workflow_case", "paper", "work_style", "vision")

GENRE_LABELS = {
    "hot_news": "ホットなAIニュース",
    "tech_update": "AIテック最新更新情報",
    "workflow_case": "個人の作業効率化事例",
    "paper": "AI論文",
    "work_style": "AIと働き方",
    "vision": "AIの将来・ビジョン",
}

# 曜日→ジャンル（index は date.weekday() と同じ 月=0 … 日=6）。
# ホットニュースのみ週2回（月・日）。
WEEKLY_ROTATION = (
    "hot_news",  # 月
    "tech_update",  # 火
    "workflow_case",  # 水
    "paper",  # 木
    "work_style",  # 金
    "vision",  # 土
    "hot_news",  # 日
)

# 動画のコーナー（バッジ・ハッシュタグ）は既存4種のまま、ジャンルから決定する。
# これによりコーナー分類のLLM判定は不要になり、バッジ素材の追加も不要。
GENRE_TO_CORNER = {
    "hot_news": "news",
    "tech_update": "news",
    "workflow_case": "work",
    "paper": "paper",
    "work_style": "work",
    "vision": "society",
}


def today_jst(now: dt.datetime | None = None) -> dt.date:
    """JSTでの今日の日付。now はテスト用の注入ポイント（awareであること）。"""
    return (now or dt.datetime.now(JST)).astimezone(JST).date()


def genre_for_date(d: dt.date) -> str:
    return WEEKLY_ROTATION[d.weekday()]


def genre_for_today(now: dt.datetime | None = None) -> str:
    return genre_for_date(today_jst(now))


def genre_for_tomorrow(now: dt.datetime | None = None) -> str:
    return genre_for_date(today_jst(now) + dt.timedelta(days=1))


def corner_for_genre(genre: str | None) -> str | None:
    """ジャンル→コーナー。未知/未分類は None（呼び出し側でLLM判定値を残す）。"""
    return GENRE_TO_CORNER.get(genre or "")


def label_for(genre: str) -> str:
    return GENRE_LABELS.get(genre, genre)


def normalize_genre(value: str | None, default: str = "hot_news") -> str:
    """LLM出力のジャンルを検証し、未知の値は default に落とす。"""
    v = (value or "").strip()
    return v if v in GENRES else default
