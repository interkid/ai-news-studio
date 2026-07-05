"""`studio publish` の全体オーケストレーション(SPEC 8章)。

Cloudflare KVで承認状態をポーリング→承認済みならTikTok inboxへ送信→LINEに完了通知。
15分間隔での実行を想定するため、1回の呼び出しで送信待ちの動画をすべて処理する。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .notifier.line import notify_publish_complete
from .publisher import kv as kv_client
from .publisher import r2 as r2_client
from .publisher import tiktok as tiktok_client
from .shared.db import Database
from .shared.models import Script


def _resolve_video_path(script_id: int, file_path: str | None) -> Path:
    """レンダ済みmp4のローカルパスを解決する。無ければR2から取得し直す。

    (`studio pipeline`と`studio publish`はGitHub Actions上では別ジョブのため、
    ローカルファイルは残っていない前提で動く)
    """
    if file_path is not None and Path(file_path).exists():
        return Path(file_path)
    dest = Path(tempfile.gettempdir()) / f"studio_publish_{script_id}.mp4"
    r2_client.download_video(f"videos/{script_id}.mp4", dest)
    return dest


@dataclass
class PublishOutcome:
    script_id: int
    status: str  # "published" | "rejected" | "pending"
    detail: str = ""


def run(db: Database) -> list[PublishOutcome]:
    outcomes: list[PublishOutcome] = []
    for row in db.videos_awaiting_publish():
        script_id = row["script_id"]
        approval = kv_client.get_video_approval(script_id)
        if approval is None:
            outcomes.append(PublishOutcome(script_id, "pending"))
            continue

        status = approval.get("status")
        if status == "rejected":
            db.set_video_approval_status(script_id, "rejected", approval.get("reason"))
            outcomes.append(PublishOutcome(script_id, "rejected", approval.get("reason", "")))
            continue
        if status != "approved":
            outcomes.append(PublishOutcome(script_id, "pending"))
            continue

        db.set_video_approval_status(script_id, "approved")
        video_path = _resolve_video_path(script_id, row["file_path"])
        publish_id = tiktok_client.publish_to_inbox(db, video_path)
        db.set_video_published(script_id, publish_id)

        script = Script.model_validate_json(db.get_script(script_id)["script_json"])
        notify_publish_complete(script=script, publish_id=publish_id)
        outcomes.append(PublishOutcome(script_id, "published", publish_id))

    return outcomes
