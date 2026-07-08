"""台本の合計文字数リペア経路のテスト（generate.py の局所編集リトライ）。"""

from __future__ import annotations

import json
from pathlib import Path

from studio.scriptwriter.generate import TopicInput, generate_variants
from studio.shared.db import Database
from studio.shared.llm import LLMClient, MockProvider


def _script_payload(fox_text: str, rabbit_text: str) -> dict:
    return {
        "corner": "paper",
        "hook": "精度94%の衝撃",
        "exchanges": [
            {"speaker": "fox", "text": fox_text, "emotion": "surprised"},
            {"speaker": "rabbit", "text": rabbit_text, "emotion": "curious"},
            {"speaker": "fox", "text": fox_text, "emotion": "smug"},
            {"speaker": "rabbit", "text": rabbit_text, "emotion": "normal"},
        ],
        "brolls": [{"prompt": "x", "caption_ja": "y", "start_line": 0}],
        "caption": "解説。※AI生成/出典はコメント欄",
        "source_url": "https://example.com/x",
        "fact_claims": ["a"],
        "visual_keyword": "医療AI",
    }


_TOPIC = TopicInput(source_url="https://example.com/x", title="t", summary="s")

# fox 30文字 + rabbit 25文字 ×2 = 110文字(超過) → リペアで 23+18 ×2 = 82文字(範囲内)
_OVERFLOW = json.dumps(_script_payload("あ" * 30, "い" * 25), ensure_ascii=False)
_REPAIRED = json.dumps(_script_payload("あ" * 23, "い" * 18), ensure_ascii=False)


def test_total_length_overflow_is_repaired(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    llm = LLMClient(
        db,
        MockProvider({"scriptwriter_generate": _OVERFLOW, "scriptwriter_repair": _REPAIRED}),
    )
    variants, errors = generate_variants(llm, _TOPIC, insights=[], n=1)
    assert len(variants) == 1
    assert sum(len(ln.text) for ln in variants[0].exchanges) == 82
    assert errors == []
    db.close()


def test_failed_repair_skips_variant(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    llm = LLMClient(
        db,
        MockProvider({"scriptwriter_generate": _OVERFLOW, "scriptwriter_repair": _OVERFLOW}),
    )
    variants, errors = generate_variants(llm, _TOPIC, insights=[], n=1)
    assert variants == []
    assert len(errors) == 1
    db.close()
