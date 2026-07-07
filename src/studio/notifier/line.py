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
        raise LineNotConfigured(
            "LINE_CHANNEL_ACCESS_TOKEN / LINE_ADMIN_USER_ID が未設定です"
        )
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
        raise LineNotConfigured(
            "LINE_CHANNEL_ACCESS_TOKEN / LINE_ADMIN_USER_ID が未設定です"
        )
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
