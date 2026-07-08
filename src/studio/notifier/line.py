"""LINE Flex Messageでの承認依頼送信（SPEC 7章 Stage6）。

動画リンク・台本全文・ソースURL・採点コメント + 「承認」「却下」postbackボタンを送る。
承認/却下の実処理はCloudflare Worker(workers/approval/)がWebhookで受ける。
"""

from __future__ import annotations

import httpx

from ..shared.config import settings
from ..shared.models import Script

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"


class LineNotConfigured(RuntimeError):
    pass


def _speaker_label(speaker: str) -> str:
    return "解説うさぎ" if speaker == "fox" else "聞き役うさぎ"


def build_flex_message(
    *, video_url: str, script: Script, quality_score: float, quality_reason: str, video_id: int
) -> dict:
    lines_text = "\n".join(f"{_speaker_label(ln.speaker)}: {ln.text}" for ln in script.exchanges)
    bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"[{script.corner}] {script.hook}",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": lines_text, "wrap": True, "size": "sm"},
                {"type": "separator"},
                {
                    "type": "text",
                    "text": f"出典: {script.source_url}",
                    "wrap": True,
                    "size": "xs",
                    "color": "#888888",
                },
                {
                    "type": "text",
                    "text": f"採点: {quality_score:.0f}点 - {quality_reason}",
                    "wrap": True,
                    "size": "xs",
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "link",
                    "action": {"type": "uri", "label": "動画を見る", "uri": video_url},
                },
                {
                    "type": "button",
                    "style": "primary",
                    "action": {
                        "type": "postback",
                        "label": "承認",
                        "data": f"action=approve&video_id={video_id}",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "却下",
                        "data": f"action=reject&video_id={video_id}",
                    },
                },
            ],
        },
    }
    return {
        "type": "flex",
        "altText": f"[{script.corner}] 動画の承認依頼: {script.hook}",
        "contents": bubble,
    }


def push_flex_message(flex: dict) -> None:
    if not (settings.line_channel_access_token and settings.line_admin_user_id):
        raise LineNotConfigured("LINE_CHANNEL_ACCESS_TOKEN / LINE_ADMIN_USER_ID が未設定です")
    resp = httpx.post(
        LINE_PUSH_ENDPOINT,
        headers={
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        },
        json={"to": settings.line_admin_user_id, "messages": [flex]},
        timeout=15.0,
    )
    resp.raise_for_status()


def notify_for_approval(
    *, video_url: str, script: Script, quality_score: float, quality_reason: str, video_id: int
) -> None:
    flex = build_flex_message(
        video_url=video_url,
        script=script,
        quality_score=quality_score,
        quality_reason=quality_reason,
        video_id=video_id,
    )
    push_flex_message(flex)


def push_text_message(text: str) -> None:
    if not (settings.line_channel_access_token and settings.line_admin_user_id):
        raise LineNotConfigured("LINE_CHANNEL_ACCESS_TOKEN / LINE_ADMIN_USER_ID が未設定です")
    resp = httpx.post(
        LINE_PUSH_ENDPOINT,
        headers={
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        },
        json={"to": settings.line_admin_user_id, "messages": [{"type": "text", "text": text}]},
        timeout=15.0,
    )
    resp.raise_for_status()


def notify_publish_complete(*, script: Script, publish_id: str) -> None:
    text = f"[{script.corner}] {script.hook}\nTikTokの下書きに送信しました(publish_id={publish_id})"
    push_text_message(text)


def build_ranking_flex(
    rows: list,
    *,
    genre_label: str | None = None,
    tomorrow_label: str | None = None,
    fallback: bool = False,
) -> dict:
    """ネタストック上位のランキングFlex（M5-3b + M5-3e 曜日ローテ対応）。

    rows は db.stock_ranking()/stock_ranking_by_category() の行
    （effective_score付きsqlite3.Row）。genre_label があれば「今日のジャンル」見出しに、
    tomorrow_label があれば明日の予告（手動ストック誘導）を末尾に付ける。
    fallback=True は当日ジャンルの在庫が無く全体ランキングで代替したことを示す。
    """
    items: list[dict] = []
    for rank, r in enumerate(rows, start=1):
        title = r["title"] if len(r["title"]) <= 40 else r["title"][:39] + "…"
        items.append(
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "none",
                "margin": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{rank}. {title}",
                        "size": "sm",
                        "weight": "bold",
                        "wrap": True,
                        "action": {"type": "uri", "label": "開く", "uri": r["source_url"]},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"{r['effective_score']:.0f}点 "
                            f"(キャッチー{r['catchy_score'] or 0:.0f}/"
                            f"インパクト{r['impact_score'] or 0:.0f}/"
                            f"有用{r['useful_score'] or 0:.0f})"
                        ),
                        "size": "xs",
                        "color": "#888888",
                    },
                ],
            }
        )
    if genre_label:
        title = f"今日のジャンル: {genre_label} TOP{len(rows)}"
    else:
        title = f"今日のネタストック TOP{len(rows)}"
    header_contents: list[dict] = [
        {"type": "text", "text": title, "weight": "bold", "size": "md", "wrap": True}
    ]
    if fallback:
        header_contents.append(
            {
                "type": "text",
                "text": "※当日ジャンルの在庫が無いため全体ランキングで代替",
                "size": "xs",
                "color": "#B71C1C",
                "wrap": True,
            }
        )
    if tomorrow_label:
        items.append(
            {
                "type": "text",
                "text": f"明日のジャンル: {tomorrow_label}",
                "size": "xs",
                "color": "#888888",
                "margin": "lg",
            }
        )
    bubble = {
        "type": "bubble",
        "header": {"type": "box", "layout": "vertical", "contents": header_contents},
        "body": {"type": "box", "layout": "vertical", "contents": items},
    }
    return {
        "type": "flex",
        "altText": title,
        "contents": bubble,
    }


def notify_topic_ranking(
    rows: list,
    *,
    genre_label: str | None = None,
    tomorrow_label: str | None = None,
    fallback: bool = False,
) -> None:
    """ストック上位をLINEに配信する。ストックが空なら送らない。"""
    if not rows:
        return
    push_flex_message(
        build_ranking_flex(
            rows, genre_label=genre_label, tomorrow_label=tomorrow_label, fallback=fallback
        )
    )
