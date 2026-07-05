# AI産業革命報道局 — TikTok半自動運用システム

AIニュース・論文を **きつね(解説)×うさぎ(聞き役)** の掛け合い縦型ショート動画に自動変換し、
LINE承認を経てTikTokにドラフト送信するシステム。詳細は `AI_NEWS_STUDIO_SPEC.md.docx`（正典）を参照。
外部サービス（Anthropic/fal.ai/LINE/Cloudflare/TikTok等）の設定手順は **[`manual.md`](./manual.md)** を参照。

## セットアップ

```bash
uv sync                 # M1(render)に必要な依存のみ
uv sync --extra pipeline  # M2以降の外部連携込み
```

### 前提ソフト
- **Python 3.11+**（`uv` が自動管理）
- **FFmpeg**: システムにインストールし PATH を通すこと（MoviePy が呼び出す）。
  Windows は https://www.gyan.dev/ffmpeg/builds/ 、macOS は `brew install ffmpeg`。
- **VOICEVOX Engine**（M2以降の音声合成・任意）:
  - ローカル（Windows/Mac/Linux）: Docker不要。[VOICEVOX ENGINE Releases](https://github.com/VOICEVOX/voicevox_engine/releases)
    からOS別のスタンドアロン版をダウンロードし、`run.exe`（Windows）等を実行するだけで
    `localhost:50021` にAPIが立つ。軽量で起動も速い。
  - GitHub Actions（CI）: `docker-compose.yml` の Dockerイメージを `daily.yml` の `services:` として起動する
    （Actions環境はDocker前提のため、CIではDockerを使う）。
- **フォント**: `assets/fonts/` に Noto Sans CJK JP を配置（未配置ならローカルの Meiryo 等にフォールバック）。

## 使い方（M1）

```bash
uv run studio render --script sample.json --out out.mp4
uv run pytest
```

`sample.json` は `duration_sec` を埋めてあるため、VOICEVOX なしで単体レンダできる。

## マイルストーン
M1 レンダリング基盤 → M2 台本パイプライン → M3 承認フロー → M4 TikTok連携 → M5 分析ループ → M6 運用強化。
