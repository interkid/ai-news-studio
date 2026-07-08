# アセット出典・ライセンス

商用利用可のアセットのみを使用し、ここに出典を記録する（SPEC 12章）。

## キャラクター（characters/）
- `fox/*`（=垂れ耳解説うさぎ。内部IDのみfox）, `rabbit/*`（=白い聞き役うさぎ）, `manifest.json`:
  **本番素材（2026-07-07コミット）**。fal.ai経由の Nano Banana Pro（Gemini 3 Pro Image）で
  本プロジェクトが生成し、rembgで背景透過・共通bboxで切り出したオリジナルキャラクター
  （実在人物・既存キャラの模倣なし）。生成・仕上げ手順は `scripts/gen_character_assets.py` /
  `scripts/finalize_character_assets.py` で再現可能。fal.ai の利用規約上、生成物は商用利用可。

## レイアウト（layout/）
- `bg.png`: **本番素材（2026-07-07コミット）**。キャラと同じく fal.ai / Nano Banana Pro で生成
  （夜空+雲+ボケ光の3DCG調背景）。商用利用可（同上）。
- `broll_placeholder.png`, `logo.png`, `badge_*.png`: **自作プレースホルダ**
  （`scripts/gen_placeholders.py` のPillow描画）。M5で刷新予定（`NEXT_STEPS.md` 参照）。

## フォント（fonts/）
- 本番は **Noto Sans CJK JP**（SIL Open Font License 1.1）を `assets/fonts/` に配置予定。
  ローカル開発では未配置時にシステムフォント（Meiryo 等）へフォールバックする。

## BGM・効果音（bgm/）
- 未配置。商用利用可の素材を追加した際に、素材名 / 配布元URL / ライセンスを本ファイルへ追記すること。

| 種別 | ファイル | 配布元 | ライセンス |
|------|----------|--------|-----------|
| （例）BGM | bgm/paper.mp3 | — | — |
