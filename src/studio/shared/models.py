"""台本・DB入出力の Pydantic モデル（SPEC 5章 正典）。

台本JSONの型を一元管理する。文字数・キャプション・合計尺の制約は
SPEC の「絶対条件」「フック生成ガイドライン」に対応する validator で表現する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

Speaker = Literal["fox", "rabbit"]
Emotion = Literal["normal", "surprised", "smug", "worried", "curious"]
Corner = Literal["paper", "news", "society", "work"]

# セリフ全文合計の許容レンジ（SPEC 5章「全セリフ合計70〜100文字」）
TOTAL_TEXT_MIN = 70
TOTAL_TEXT_MAX = 100
# rabbit のセリフ上限（SPEC: rabbitは25文字まで）
RABBIT_MAX_LEN = 25
# AI生成ラベル（キャプション末尾に必須）
AI_LABEL = "※AI生成"


class Line(BaseModel):
    """1セリフ。TTS後に wav_path / duration_sec が付与される。"""

    speaker: Speaker
    text: str = Field(max_length=35)
    emotion: Emotion
    wav_path: str | None = None
    duration_sec: float | None = None

    @model_validator(mode="after")
    def _rabbit_length(self) -> Line:
        if self.speaker == "rabbit" and len(self.text) > RABBIT_MAX_LEN:
            raise ValueError(
                f"rabbit のセリフは{RABBIT_MAX_LEN}文字以内: {len(self.text)}文字 -> {self.text!r}"
            )
        return self


class Broll(BaseModel):
    """挿絵(B-roll)。prompt は内容のみ、スタイル指定は imagegen 側で付与する。"""

    prompt: str
    caption_ja: str
    start_line: int = Field(ge=0)
    image_path: str | None = None


class Script(BaseModel):
    """1本の動画に対応する台本。"""

    corner: Corner
    hook: str = Field(max_length=15)
    exchanges: list[Line] = Field(min_length=2, max_length=4)
    brolls: list[Broll] = Field(min_length=1, max_length=3)
    caption: str
    source_url: HttpUrl
    fact_claims: list[str]
    visual_keyword: str = Field(max_length=8)

    @model_validator(mode="before")
    @classmethod
    def _truncate_llm_overflow(cls, data):
        """LLM生成JSONの軽微な文字数超過を自動トリミングする（生成やり直しを避ける）。

        LLMは日本語の文字数を正確に数えるのが苦手で、数文字だけ上限を超える出力を
        しばしば返す。構造そのもの(必須キー欠落等)には関与せず、文字列の長さだけを
        安全側に丸める。
        """
        if not isinstance(data, dict):
            return data
        if isinstance(data.get("hook"), str):
            data["hook"] = data["hook"][:15]
        if isinstance(data.get("visual_keyword"), str):
            data["visual_keyword"] = data["visual_keyword"][:8]
        exchanges = data.get("exchanges")
        if isinstance(exchanges, list):
            for line in exchanges:
                if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                    continue
                limit = RABBIT_MAX_LEN if line.get("speaker") == "rabbit" else 35
                line["text"] = line["text"][:limit]
        return data

    @field_validator("caption")
    @classmethod
    def _caption_has_ai_label(cls, v: str) -> str:
        if AI_LABEL not in v:
            raise ValueError(f"caption には「{AI_LABEL}」を含めること: {v!r}")
        return v

    @model_validator(mode="after")
    def _total_text_length(self) -> Script:
        total = sum(len(line.text) for line in self.exchanges)
        if not (TOTAL_TEXT_MIN <= total <= TOTAL_TEXT_MAX):
            raise ValueError(
                f"全セリフ合計は{TOTAL_TEXT_MIN}〜{TOTAL_TEXT_MAX}文字: 実際{total}文字"
            )
        return self

    @model_validator(mode="after")
    def _broll_start_lines_in_range(self) -> Script:
        n = len(self.exchanges)
        for b in self.brolls:
            if b.start_line >= n:
                raise ValueError(
                    f"broll.start_line({b.start_line}) は exchanges 数({n})未満であること"
                )
        return self

    @property
    def total_duration_sec(self) -> float | None:
        """全セリフの実測尺合計（TTS前は None）。"""
        if any(line.duration_sec is None for line in self.exchanges):
            return None
        return sum(line.duration_sec for line in self.exchanges)  # type: ignore[misc]
