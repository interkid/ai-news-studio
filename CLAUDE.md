# CLAUDE.md — AI産業革命報道局 / TikTok半自動運用システム

このファイルはプロジェクトの**大枠**を示す。詳細な仕様・スキーマ・段取りは
[`AI_NEWS_STUDIO_SPEC.md.docx`](./AI_NEWS_STUDIO_SPEC.md.docx)（正典）を必ず参照すること。
両者が食い違う場合は SPEC を優先し、本ファイルを更新する。

## 進め方の原則（Claude Codeへの指示）
- SPEC に従って実装する。**不明点は実装前に質問**し、各マイルストーン完了時に**動作確認手順を提示**する。
- 迷ったら「品質 > 頻度」。生成・検証に失敗する日は**投稿しない**が正。
- コスト超過を防ぐため、LLM/画像生成には**日次上限**を設ける（デフォルト LLM 30回 / 画像 5枚、環境変数で変更可）。
- コードスタイルは **ruff + type hints 必須**、設定より規約、過剰な抽象化をしない。

## 何を作るか（1行）
AIニュース・論文を **垂れ耳解説うさぎ×白い聞き役うさぎ** の掛け合い **10〜25秒 縦型ショート動画** に自動変換し、
**LINEで管理者承認**を経て **TikTokにドラフト送信**するシステム。
（2026-07-07: きつね×うさぎから変更。内部スピーカーID/素材ディレクトリは `fox` のまま）

## 絶対に守る制約
- 全動画は**ソースURLに基づく事実のみ**。ファクト検証に落ちた台本は自動リジェクト。
- 全投稿に **AI生成ラベル**を付与（キャプションに「※AI生成」明記 + TikTok側ラベルON）。
- **実在人物の顔・声は生成しない**。挿絵はイラスト調のみ（写実調は誤認リスクで禁止）。
- 尺 10〜25秒 / **1080x1920 / 30fps** 縦型。
- **予算 月5,000円以内**（有料は LLM API と画像生成 API のみ、他は無料枠）。
- アセットは**商用利用可ライセンスのみ**。出典を `assets/LICENSES.md` に記録。

## 技術スタック（要点）
- **言語**: Python 3.11+ / パッケージ管理は **uv**（`pyproject.toml`）
- **CLI**: typer（`studio` コマンド）
- **動画**: MoviePy **2.x** + Pillow + FFmpeg（テンプレート合成。フル生成AIは使わない）
  - ⚠️ MoviePy 2.x は 1.x とAPIが違う（`with_position` 等）。**1.xのサンプルを流用しない**。
  - 日本語字幕は TextClip ではなく **Pillowで字幕PNG生成 → ImageClip**。フォント: Noto Sans CJK JP。
- **型/検証**: Pydantic v2（台本JSON・設定・DB入出力を一元管理）
- **LLM**: Anthropic 公式SDK（claude-haiku系）。呼び出しは `shared/llm.py` に集約し**コストを必ず記録**。
- **画像生成**: fal.ai の FLUX schnell を第一候補（httpx）
- **音声**: VOICEVOX Engine（Docker, 無料）
- **HTTP/リトライ**: httpx + tenacity / **収集**: feedparser + arXiv Atom API
- **DB**: sqlite3 + 薄いリポジトリ層（ORM不使用）
- **保存/配信**: Cloudflare R2（boto3, S3互換）
- **承認**: Cloudflare Workers（唯一のJS部品・約50行、署名検証→KV書き込みのみ）
- **通知**: LINE Messaging API（Flex Message）
- **投稿**: TikTok Content Posting API（**inbox ドラフトモード**）
- **実行基盤**: GitHub Actions cron（毎朝 JST 7:00）

## パイプライン（実行順＝コスト最適化順）
収集 → 台本2案+ファクト検証 → **採点で1案に絞る** → TTS → 挿絵生成 → レンダ → 承認依頼。
（2026-07-05: LLM日次呼び出し上限の消費を抑えるため3案→2案に変更）
TTS・画像生成・レンダは**選ばれた1案のみ**に実行。実測尺が25秒超なら次点へフォールバック。

- **daily.yml** (`studio pipeline`): 収集(ネタストック更新+LINEランキングTOP10配信)→台本→音声→レンダ→採点→承認依頼
  （2026-07-08: ネタは3軸採点(キャッチー/インパクト/有用)で全件ストックし、鮮度減衰込みの
  ストック全体ランキングから当日の1本を選ぶ。DBは run 終了時にR2へバックアップ）
- **publish.yml** (`studio publish`, 15分間隔): KVで承認検知→TikTokドラフト送信→LINE完了通知
- **weekly.yml** (`studio analyze`): 成績分析→`prompt_insights` 更新→翌週の台本プロンプトへ反映

## モジュール地図（`src/studio/`）
`shared/`(models・db・llm・config) / `collector/` / `scriptwriter/` / `tts/` /
`imagegen/` / `renderer/`(**最重要**) / `scorer/` / `publisher/` / `notifier/` / `analytics/`。
承認Workerは `workers/approval/`、アセットは `assets/`（characters は `manifest.json` 経由で差し替え可能）。
→ 全体構成・データモデル(SQLite 6テーブル)・台本スキーマは SPEC の 3〜5章。

## レンダラーの肝（詳細は SPEC 6章）
- テンポ規則: 画面のどこかが **1.5〜2.5秒ごとに必ず変化**。無変化2.5秒超は自動ズーム挿入。
- タイミングは全て `Line.duration_sec` の**実測値**から組む。マジックナンバーは `renderer/layout.py` に定数化。
- 演出は `renderer/effects.py`（zoom_in / pop_in / shake / flash / slide_in）で全動画共通化。

## マイルストーン（この順。M5以降はSPEC原文から並び替え・再定義済み — 詳細は本ファイルが正）
- **M1 レンダリング基盤**（完了）: CLI骨格・Pydantic Script・renderer・effects・Ken Burns・VOICEVOX起動構成。
  完了条件 = `studio render --script sample.json` で口パク/字幕同期/テロップ演出が入った15秒動画が出る + pytest通過。
- **M2 台本パイプライン**（完了）: collector・scriptwriter+検証・scorer・imagegen / `studio pipeline --dry-run`。
- **M3 承認フロー**（完了）: R2アップロード・LINE Flex・Worker+KV+却下理由紐付け。実LINE通知・承認/却下ボタン・
  却下理由紐付けまでE2Eで動作確認済み。
- **M4 TikTok連携（運用開始・次はここ）**: `studio auth tiktok`・inboxチャンクアップロード・publish.yml。
- **M5 デザイン・ネタ・インパクト構成強化**（SPEC原文の「M6運用強化」の一部を再定義。分析ループより先に実施）:
  - キャラ/背景素材の刷新（`assets/characters`・`assets/layout` のプレースホルダを本番品質へ差し替え）
  - 演出バリエーション追加（`renderer/effects.py` の拡充）
  - ネタ選定への人間の事前レビュー機能（`studio pipeline` のcollector後、台本生成前にLINE等で候補トピックを
    確認・選択できる仕組みを追加。自動選定一本ではなく人間の目を挟む）
  - フック/展開/オチのテンプレ化（`scriptwriter/generate.py` のプロンプトを、
    「つかみ→展開→オチ/示唆」の型に沿うよう構成強化し、10〜20秒でのインパクトを安定させる）
- **M6 分析ループ**（SPEC原文のM5をここに移動）: metrics収集・weekly.yml・prompt_insights自動更新。
- **M7 運用強化（任意・元M6の残り）**: コメント返信案・増産スイッチ・Layer3 フック映像。

## 現在の状態（2026-07-07時点）
- M1〜M4実装済み・E2E確認済み。**M4は全段通しで成功**: `daily.yml`（収集→台本→TTS→レンダ→R2→
  LINE承認依頼）→ LINE承認 → `publish.yml`（KV検知→TikTok inboxドラフト送信→LINE完了通知）。
  GitHub Actionsの自動実行(cron)は**引き続き意図的に無効**（`workflow_dispatch`のみ有効）。
  動画の品質チェック（M5）が済むまで無人自動投稿はONにしない方針。
- M5進行中: キャラ刷新完了（うさぎペア・ピクサー調3DCG・11状態、`assets/characters/`にコミット済み）、
  ビート構成テンプレ+文字数リペア実装済み。ネタストック（3軸採点・鮮度減衰・R2 DBバックアップ・
  LINEランキングTOP10配信）実装済み・CI検証済み（2026-07-08）。
  残り = 演出バリエーション → LINEからの手動ストック → ランキングからの選択生成ボタン、
  layoutのロゴ/バッジ刷新（詳細は `NEXT_STEPS.md`）。
- 設定済み: `ANTHROPIC_API_KEY` / `FAL_KEY` / `LINE_*` / `R2_*` / `CF_*` / `TIKTOK_*`（ローカル`.env`と
  GitHub Secretsの両方。Secretsがローカルと食い違って落ちた前例あり→`.env`正としてAPIで同期する）。
  Cloudflare Worker(`workers/approval/`)は `ai-news-studio-approval.ai-news-studio.workers.dev` にデプロイ済み。
- 外部サービスの設定手順は `manual.md` を参照。
- リポジトリ本体は GitHub(`github.com/interkid/ai-news-studio`) の master へpush済み。
