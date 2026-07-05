"""台本モデルの制約テスト（SPEC 5章）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from studio.shared.models import Broll, Line, Script


def _valid_kwargs(**over):
    base = dict(
        corner="paper",
        hook="精度94%の衝撃",
        exchanges=[
            Line(speaker="fox", text="精度94%、AIが医療診断を大きく変えます", emotion="surprised"),
            Line(speaker="rabbit", text="えっ、お医者さんいらずになるの？", emotion="curious"),
            Line(speaker="fox", text="画像診断で専門医に並ぶ正答率が出たんだ", emotion="smug"),
            Line(speaker="rabbit", text="あなたの健康にも直結する大事な話だね", emotion="normal"),
        ],
        brolls=[Broll(prompt="x", caption_ja="y", start_line=0)],
        caption="解説。※AI生成/出典はコメント欄",
        source_url="https://arxiv.org/abs/2401.00001",
        fact_claims=["a"],
        visual_keyword="医療AI",
    )
    base.update(over)
    return base


def test_valid_script():
    s = Script(**_valid_kwargs())
    assert s.total_duration_sec is None  # duration未付与


def test_rabbit_length_limit():
    with pytest.raises(ValidationError):
        Line(
            speaker="rabbit",
            text="これは二十五文字を確実に超える非常に長いうさぎのセリフですよ",
            emotion="normal",
        )


def test_caption_requires_ai_label():
    with pytest.raises(ValidationError):
        Script(**_valid_kwargs(caption="AIラベルなしのキャプション"))


def test_total_text_length_range():
    short = [
        Line(speaker="fox", text="短い", emotion="normal"),
        Line(speaker="rabbit", text="短い", emotion="normal"),
    ]
    with pytest.raises(ValidationError):
        Script(**_valid_kwargs(exchanges=short))


def test_broll_start_line_out_of_range():
    with pytest.raises(ValidationError):
        Script(**_valid_kwargs(brolls=[Broll(prompt="x", caption_ja="y", start_line=9)]))


def test_llm_overflow_is_truncated_not_rejected():
    """LLM生成JSON(生dict)で文字数がわずかに超過していても自動トリミングされる。"""
    payload = {
        "corner": "paper",
        "hook": "これは十五文字を確実に超える長いフックです",  # 15文字超
        "exchanges": [
            {
                "speaker": "fox",
                "text": "これは三十五文字を確実に超えるとても長いきつねのセリフになっています",
                "emotion": "surprised",
            },
            {
                "speaker": "rabbit",
                "text": "これは二十五文字を確実に超える長いうさぎのセリフですね",
                "emotion": "curious",
            },
            {
                "speaker": "fox",
                "text": "これも三十五文字を確実に超えるとても長いきつねのセリフになっています",
                "emotion": "normal",
            },
        ],
        "brolls": [{"prompt": "x", "caption_ja": "y", "start_line": 0}],
        "caption": "解説。※AI生成/出典はコメント欄",
        "source_url": "https://arxiv.org/abs/2401.00001",
        "fact_claims": ["a"],
        "visual_keyword": "これは八文字を超える名詞句",  # 8文字超
    }
    s = Script.model_validate(payload)
    assert len(s.hook) <= 15
    assert len(s.visual_keyword) <= 8
    assert len(s.exchanges[0].text) <= 35
    assert len(s.exchanges[1].text) <= 25
