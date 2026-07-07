"""台本2案生成（SPEC 5章スキーマ + 7章 Stage 2 + フックガイドライン。LLM日次上限対策で3→2に変更）。

Script モデル自体の validator（文字数制約・AI生成ラベル等）を
LLM出力の受け入れ基準として再利用する。validator に落ちた案はそのままスキップし、
呼び出し側には合格した Script のみを返す。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from ..shared.llm import LLMCallError, LLMClient
from ..shared.models import Script

logger = logging.getLogger(__name__)

SCRIPT_SYSTEM_PROMPT = """あなたは「AI産業革命報道局」というTikTok向け縦型ショート動画番組の台本作家です。
きつね(解説役)とうさぎ(聞き役)の掛け合いで、10〜25秒の台本を1本作ってください。

台本は必ず次のビート構成(つかみ→展開→オチ)に沿って組むこと:
- ①つかみ(きつねの第一声): hookをそのまま言い直すのではなく、具体的な事実・数字で
  一撃を放つ。視聴者がスクロールの指を止める1文。
- ②リアクション+疑問(うさぎ): 視聴者の代弁者として驚き・疑問を短く返す。
  次のセリフを聞きたくさせる引きを作る。
- ③核心・根拠(きつね): ニュースの核心を数字や固有の事実で裏づける。①で放った
  一撃の種明かしになるようにする。
- ④オチ/示唆(最後のセリフ): 視聴者自身に引きつけて終える(例: 「あなたの仕事にも
  来るかも」「あなたならどう使う?」)。コメントしたくなる問いかけ・示唆で締める。
exchanges が4個ならビートを①②③④に1対1で対応させる。3個なら③と④を最後の
きつねのセリフに統合する。2個なら①にきつねのつかみ+核心、②にうさぎのオチ/示唆を置く。
どの長さでも「最後のセリフが視聴者への引きで終わる」ことは必須。

制約(すべて厳守。文字数は英数字記号も1文字として数える。出力前に必ず1文字ずつ数えて
確認し、絶対上限に近い場合は短く言い換えること):
- exchanges は2〜4個。各要素は speaker・text・emotion の3キーを必ず持つ。
  - speaker は "fox" か "rabbit" のみ。
  - emotion は "normal"/"surprised"/"smug"/"worried"/"curious" のいずれか必須(省略不可)。
  - rabbit の text は目標16〜20文字・絶対上限25文字。fox の text は目標21〜26文字・
    絶対上限32文字。上限ぎりぎりも下限割れも避け、必ず目標レンジの範囲内に収めること。
  - exchanges が fox,rabbit,fox,rabbit の4個の場合、text文字数合計は目安として
    21+16+21+16=74文字前後になる。これが70〜100文字の範囲に必ず収まるよう
    各textの文字数を調整すること(合計が70文字を切りそうなら各textを目標レンジの
    上限寄りにし、100文字を超えそうなら下限寄りにする。超過時はまずうさぎのセリフから削る)。
- hook(きつねの第一声)は目標6〜10文字・絶対上限15文字。「嘘をつかずに驚かせる」に全振り
  する。使ってよい型: (a)原文にある最も強い数字の切り出し(例: 精度94%) (b)視聴者を
  主語にする(例: あなたの仕事の話) (c)疑問形で関心を突く(例: 気づいてますか?)。
  原文にない最上級・断定・恐怖煽り(例: 人類終了、○○消滅)は禁止。
- caption の末尾付近に「※AI生成」を含めること。
- visual_keyword は目標4〜6文字・絶対上限8文字の名詞句。
- hook・visual_keywordに英字の製品名/サービス名(ChatGPT等)を入れると文字数を圧迫するため、
  できる限り日本語の意訳・略語(例: "ChatGPT"→"AI"、"生成AI")に置き換えること。
  英字を使う場合は必ず全体の文字数上限を優先し、他の語を削ってでも上限を守ること。
- fact_claims には台本内で使った事実主張を、原文に基づくもののみ列挙する。
- corner は内容から paper / news / society / work のいずれかを判定する。
- brolls は1〜3件。各要素は prompt・caption_ja・start_line の3キーを必ず持つ
  (start_line のみでprompt/caption_jaを省略するのは不可)。start_line は exchanges の
  該当セリフのindex(0始まり)。
- source_url は与えられたURLをそのまま使う。

出力形式の例(このJSON構造を寸分違わず守ること。内容はダミー):
{{
  "corner": "paper",
  "hook": "精度94%の衝撃",
  "exchanges": [
    {{"speaker": "fox", "text": "精度94%、新研究の衝撃の結果です", "emotion": "surprised"}},
    {{"speaker": "rabbit", "text": "えっ、そんなに違うの?", "emotion": "curious"}},
    {{"speaker": "fox", "text": "専門家の予測を大きく上回ったんだ", "emotion": "smug"}},
    {{"speaker": "rabbit", "text": "私たちの仕事にも影響ありそうだね", "emotion": "normal"}}
  ],
  "brolls": [
    {{"prompt": "a cute cartoon chart showing rising accuracy", "caption_ja": "精度上昇のイメージ", "start_line": 0}}
  ],
  "caption": "研究内容の解説。※AI生成/出典はコメント欄",
  "source_url": "https://example.com/paper",
  "fact_claims": ["精度94%という結果が報告された"],
  "visual_keyword": "研究成果"
}}

{insights_block}
出力はJSONオブジェクトのみ。上記例と同じキー構成(corner, hook, exchanges, brolls, \
caption, source_url, fact_claims, visual_keyword)を過不足なく使うこと。"""


@dataclass
class TopicInput:
    source_url: str
    title: str
    summary: str | None


def _insights_block(insights: list[str]) -> str:
    if not insights:
        return ""
    bullet = "\n".join(f"- {i}" for i in insights)
    return f"直近の分析で得られた改善指示(必ず反映すること):\n{bullet}\n\n"


def _topic_prompt(topic: TopicInput, retry_notes: str | None) -> str:
    parts = [f"ソースURL: {topic.source_url}", f"タイトル: {topic.title}"]
    if topic.summary:
        parts.append(f"概要: {topic.summary}")
    if retry_notes:
        parts.append(f"\n前回案が却下された理由(必ず修正すること): {retry_notes}")
    parts.append("\n上記の内容に基づき、Scriptスキーマ通りのJSONを1件生成してください。")
    return "\n".join(parts)


def generate_variants(
    llm: LLMClient,
    topic: TopicInput,
    insights: list[str],
    n: int = 2,
    retry_notes: str | None = None,
) -> tuple[list[Script], list[str]]:
    """temperatureを変えたn案を生成する。

    戻り値は (Scriptのvalidatorを満たした案のみ, 失敗した案のエラー要約)。
    エラー要約は全滅時の再生成プロンプトへのフィードバックに使う。
    """
    system = SCRIPT_SYSTEM_PROMPT.format(insights_block=_insights_block(insights))
    user = _topic_prompt(topic, retry_notes)
    temperatures = [0.4, 0.7, 1.0][:n]
    variants: list[Script] = []
    errors: list[str] = []
    for i, temp in enumerate(temperatures):
        try:
            script = llm.complete_json(
                purpose="scriptwriter_generate",
                system=system,
                user=user,
                schema=Script,
                temperature=temp,
                max_tokens=1200,
            )
        except ValidationError as e:
            summary = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
            )
            logger.warning("台本案%d生成失敗(skip): %s", i, summary)
            errors.append(f"案{i}: {summary}")
            continue
        except LLMCallError as e:
            logger.warning("台本案%d生成失敗(skip): %s", i, e)
            errors.append(f"案{i}: {e}")
            continue
        variants.append(script)
    return variants, errors
