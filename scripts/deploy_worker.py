"""Cloudflare Worker(workers/approval/)を非対話的にデプロイする。

.env から CF_API_TOKEN / CF_KV_NAMESPACE_ID / LINE_CHANNEL_SECRET / R2_ACCOUNT_ID を
読み込み、wrangler.toml生成 → secret登録 → deploy まで一括実行する。
機密値は本スクリプト内でのみ扱い、stdoutには一切出力しない
(deployで得られるWorkerのURLだけを最終出力する)。

    uv run python scripts/deploy_worker.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "workers" / "approval"


def _wrangler_cmd() -> str:
    # Windows の npm global bin は wrangler.cmd としてインストールされる
    for cand in ("wrangler.cmd", "wrangler"):
        from shutil import which

        if which(cand):
            return cand
    raise SystemExit("wrangler が見つかりません。`npm install -g wrangler` を先に実行すること。")


def main() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from studio.shared.config import settings

    missing = [
        name
        for name, val in [
            ("CF_API_TOKEN", settings.cf_api_token),
            ("CF_KV_NAMESPACE_ID", settings.cf_kv_namespace_id),
            ("LINE_CHANNEL_SECRET", settings.line_channel_secret),
            ("R2_ACCOUNT_ID", settings.r2_account_id),
        ]
        if not val
    ]
    if missing:
        raise SystemExit(f".envに未設定の値があります: {', '.join(missing)}")

    template = (WORKER_DIR / "wrangler.toml.template").read_text(encoding="utf-8")
    toml_content = template.replace("__CF_ACCOUNT_ID__", settings.r2_account_id).replace(
        "__CF_KV_NAMESPACE_ID__", settings.cf_kv_namespace_id
    )
    (WORKER_DIR / "wrangler.toml").write_text(toml_content, encoding="utf-8")

    env = {**os.environ, "CLOUDFLARE_API_TOKEN": settings.cf_api_token}
    wrangler = _wrangler_cmd()

    secret_proc = subprocess.run(
        [wrangler, "secret", "put", "LINE_CHANNEL_SECRET"],
        cwd=WORKER_DIR,
        input=settings.line_channel_secret,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        capture_output=True,
    )
    if secret_proc.returncode != 0:
        print("secret put に失敗しました(詳細は非表示。終了コード):", secret_proc.returncode)
        raise SystemExit(1)
    print("[ok] LINE_CHANNEL_SECRET をWorkerシークレットとして登録しました")

    deploy_proc = subprocess.run(
        [wrangler, "deploy"],
        cwd=WORKER_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        capture_output=True,
    )
    if deploy_proc.returncode != 0:
        print("deploy に失敗しました。stderr:")
        print(deploy_proc.stderr)
        raise SystemExit(1)

    m = re.search(r"https://[a-zA-Z0-9.\-]+\.workers\.dev\S*", deploy_proc.stdout)
    if m:
        print(f"[ok] Worker deployed: {m.group(0)}")
    else:
        print("[ok] deploy成功（URL抽出は失敗。stdout末尾を確認してください）")
        print(deploy_proc.stdout[-500:])


if __name__ == "__main__":
    main()
