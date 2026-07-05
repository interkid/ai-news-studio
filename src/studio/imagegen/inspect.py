"""B-rollプロンプトの安全性検査（SPEC 7章 Stage 3.5）。

実在人物・実在ロゴ・著作権キャラ・写実的人物描写を含むプロンプトはreject対象。
1回だけ修正案での再検査を許す。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..shared.llm import LLMClient

INSPECT_SYSTEM = (
    "あなたは画像生成プロンプトの安全性チェッカーです。プロンプトに実在人物、実在ロゴ、"
    "著作権のあるキャラクター、写実的な人物描写が含まれていないか判定してください。"
    "問題があれば ok=false とし、それらを取り除いたイラスト調のrevised_promptを提案してください。"
    '問題なければ ok=true, revised_prompt=null。出力はJSONのみ: {"ok": bool, "reason": "...", '
    '"revised_prompt": "..." or null}'
)


class InspectResult(BaseModel):
    ok: bool
    reason: str
    revised_prompt: str | None = None


def inspect_prompt(llm: LLMClient, prompt: str) -> InspectResult:
    return llm.complete_json(
        purpose="imagegen_inspect",
        system=INSPECT_SYSTEM,
        user=f"プロンプト: {prompt}",
        schema=InspectResult,
        temperature=0.0,
        max_tokens=300,
    )


def inspect_with_one_retry(llm: LLMClient, prompt: str) -> str | None:
    """検査に通ったプロンプト文字列を返す。reject確定ならNone。"""
    result = inspect_prompt(llm, prompt)
    if result.ok:
        return prompt
    if not result.revised_prompt:
        return None
    retry_result = inspect_prompt(llm, result.revised_prompt)
    return result.revised_prompt if retry_result.ok else None
