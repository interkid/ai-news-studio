"""台本パイプライン Stage 2 の全体オーケストレーション。

3案生成→ファクト検証→scripts保存。3案全滅なら検証コメントを添えて1回だけ再生成、
それでも全滅なら当日は投稿しない（呼び出し側が空リストで判断する）。
"""

from __future__ import annotations

import sqlite3

from ..shared.db import Database
from ..shared.llm import LLMClient
from ..shared.models import Script
from .factcheck import FactCheckResult, fact_check
from .generate import TopicInput, generate_variants


def _persist_round(
    db: Database, topic_id: int, llm: LLMClient, variants: list[Script]
) -> tuple[list[int], list[FactCheckResult]]:
    passed_ids: list[int] = []
    results: list[FactCheckResult] = []
    for v in variants:
        r = fact_check(llm, v)
        results.append(r)
        sid = db.insert_script(
            topic_id=topic_id,
            corner=v.corner,
            script_json=v.model_dump_json(),
            fact_check_passed=r.passed,
            fact_check_notes=r.notes,
            status="draft" if r.passed else "rejected",
        )
        if r.passed:
            passed_ids.append(sid)
    return passed_ids, results


def write_scripts(db: Database, llm: LLMClient, topic_row: sqlite3.Row) -> list[int]:
    """topic 1件につき台本を作り、fact_check_passed な script_id の一覧を返す（空もありうる）。"""
    topic = TopicInput(
        source_url=topic_row["source_url"],
        title=topic_row["title"],
        summary=topic_row["summary"],
    )
    insights = db.active_insights()

    variants, gen_errors = generate_variants(llm, topic, insights)
    passed_ids, results = _persist_round(db, topic_row["id"], llm, variants)
    if passed_ids:
        db.set_topic_status(topic_row["id"], "scripted")
        return passed_ids

    # 生成段階(スキーマ違反)とファクト検証段階、両方の失敗理由を再生成へフィードバックする
    fact_notes = "; ".join(r.notes for r in results if r.notes)
    notes = "; ".join(n for n in (fact_notes, "; ".join(gen_errors)) if n)
    variants2, _ = generate_variants(llm, topic, insights, retry_notes=notes)
    passed_ids2, _ = _persist_round(db, topic_row["id"], llm, variants2)
    if passed_ids2:
        db.set_topic_status(topic_row["id"], "scripted")
        return passed_ids2

    db.set_topic_status(topic_row["id"], "skipped")
    return []
