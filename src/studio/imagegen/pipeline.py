"""選出済み1案のB-roll画像生成オーケストレーション（SPEC 7章 Stage 3.5）。

各Broll.promptをLLMで検査→画像生成API呼び出し。失敗・reject・日次上限超過時は
そのbrollをスキップして image_path=None のままにする（rendererが固定背景で代替）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..shared.config import settings
from ..shared.db import Database
from ..shared.llm import LLMClient
from ..shared.models import Script
from .generate import generate_image
from .inspect import inspect_with_one_retry

logger = logging.getLogger(__name__)


def generate_brolls(db: Database, llm: LLMClient, script: Script, out_dir: Path) -> Script:
    new_brolls = []
    for i, b in enumerate(script.brolls):
        if db.images_today() >= settings.image_daily_limit:
            logger.info("画像日次上限に到達。broll[%d]は固定背景で代替", i)
            new_brolls.append(b)
            continue

        prompt = inspect_with_one_retry(llm, b.prompt)
        if prompt is None:
            logger.warning("broll[%d]のプロンプトがreject。固定背景で代替", i)
            new_brolls.append(b)
            continue

        out_path = out_dir / f"broll_{i}.png"
        try:
            generate_image(prompt, out_path)
        except Exception:
            logger.warning("broll[%d]の画像生成に失敗。固定背景で代替", i, exc_info=True)
            new_brolls.append(b)
            continue

        db.log_llm_usage(
            purpose="imagegen",
            model="fal-ai/flux/schnell",
            input_tokens=0,
            output_tokens=0,
            est_cost_jpy=0.0,
        )
        new_brolls.append(b.model_copy(update={"image_path": str(out_path)}))

    return script.model_copy(update={"brolls": new_brolls})
