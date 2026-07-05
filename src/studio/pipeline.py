"""`studio pipeline` の全体オーケストレーション（SPEC 7章「実行順の注意」）。

実行順: 収集(Stage1) → 台本3案+検証(Stage2) → 採点で1案に絞る(Stage5)
→ TTS(Stage3) → 挿絵(Stage3.5) → レンダ(Stage4) → 承認依頼(Stage6, dry-runは省略)。
TTS・画像生成・レンダは選ばれた1案のみに対して行う。実測尺が25秒を超えた場合のみ
次点の案へフォールバックする。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .collector.collect import run as collect_run
from .imagegen.pipeline import generate_brolls
from .notifier.line import notify_for_approval
from .publisher.r2 import upload_video
from .renderer.render import render_script_object
from .scorer.score import append_note, select_script
from .scriptwriter.write import write_scripts
from .shared.db import Database
from .shared.llm import LLMClient
from .shared.models import Script
from .tts.synthesize import synthesize_script

logger = logging.getLogger(__name__)

MAX_DURATION_SEC = 25.0


@dataclass
class PipelineResult:
    topic_id: int
    script_id: int
    video_path: Path
    duration_sec: float
    video_url: str | None = None


def _ranked_script_ids(db: Database, script_ids: list[int]) -> list[int]:
    """quality_score降順で並べ直す（scorer実行後を想定）。"""
    placeholders = ",".join("?" * len(script_ids))
    rows = db.conn.execute(
        f"SELECT id FROM scripts WHERE id IN ({placeholders}) "
        "ORDER BY quality_score DESC NULLS LAST",
        script_ids,
    ).fetchall()
    return [r["id"] for r in rows]


def _run_core(db: Database, llm: LLMClient, run_dir: Path) -> PipelineResult | None:
    """Stage1〜4を実行し、選出動画を作る（Stage6は呼び出し側の責務）。"""
    # Stage 1: 収集
    topic_ids = collect_run(db, llm, top_n=3)
    if not topic_ids:
        logger.info("収集できるトピックがありませんでした。本日は投稿しません。")
        return None
    topic_row = db.get_topic(topic_ids[0])  # Stage2以降は上位1トピックのみ対象

    # Stage 2: 台本3案生成 + ファクト検証
    script_ids = write_scripts(db, llm, topic_row)
    if not script_ids:
        logger.info("台本がファクト検証を通過できませんでした。本日は投稿しません。")
        return None

    # Stage 5: 採点で1案に絞る
    select_script(db, llm, script_ids)
    ranked_ids = _ranked_script_ids(db, script_ids)

    # Stage 3: TTS（実測尺が25秒超なら次点へフォールバック）
    final_id: int | None = None
    final_script: Script | None = None
    for sid in ranked_ids:
        candidate = Script.model_validate_json(db.get_script(sid)["script_json"])
        audio_dir = run_dir / f"script_{sid}" / "audio"
        with_audio = synthesize_script(candidate, audio_dir)
        total = with_audio.total_duration_sec or 0.0
        if total <= MAX_DURATION_SEC:
            final_id, final_script = sid, with_audio
            break
        logger.info(
            "script %d の実測尺%.1fsが%.0f秒超のため次点へフォールバック",
            sid,
            total,
            MAX_DURATION_SEC,
        )

    if final_id is None or final_script is None:
        logger.info("全案が尺超過のため本日は投稿しません。")
        return None

    if final_id != ranked_ids[0]:
        original = ranked_ids[0]
        db.update_script(original, status="rejected")
        append_note(db, original, "尺超過のため次点にフォールバック")
        db.update_script(final_id, status="selected")

    # Stage 3.5: 挿絵
    image_dir = run_dir / f"script_{final_id}" / "images"
    final_script = generate_brolls(db, llm, final_script, image_dir)

    # Stage 4: レンダ
    out_path = run_dir / f"script_{final_id}" / "out.mp4"
    result = render_script_object(final_script, out_path)
    db.insert_video(
        script_id=final_id, file_path=str(result.path), duration_sec=result.duration_sec
    )

    return PipelineResult(
        topic_id=topic_row["id"],
        script_id=final_id,
        video_path=result.path,
        duration_sec=result.duration_sec,
    )


def run_dry(db: Database, llm: LLMClient, run_dir: Path) -> PipelineResult | None:
    """Stage6(承認依頼)を省略する版。"""
    return _run_core(db, llm, run_dir)


def run(db: Database, llm: LLMClient, run_dir: Path) -> PipelineResult | None:
    """Stage6(R2アップロード + LINE承認依頼)まで行う本番実行。"""
    result = _run_core(db, llm, run_dir)
    if result is None:
        return None

    script_row = db.get_script(result.script_id)
    script = Script.model_validate_json(script_row["script_json"])
    quality_score = script_row["quality_score"] or 0.0
    quality_reason = script_row["fact_check_notes"] or ""

    video_url = upload_video(result.video_path, key=f"videos/{result.script_id}.mp4")
    db.set_video_r2_url(result.script_id, video_url)
    notify_for_approval(
        video_url=video_url,
        script=script,
        quality_score=quality_score,
        quality_reason=quality_reason,
        video_id=result.script_id,
    )
    result.video_url = video_url
    return result
