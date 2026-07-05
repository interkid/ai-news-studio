# アセット出典・ライセンス

商用利用可のアセットのみを使用し、ここに出典を記録する（SPEC 12章）。

## キャラクター（characters/）
- `fox/*`, `rabbit/*`, `manifest.json`: **本プロジェクト自作のプレースホルダ**
  （`scripts/gen_placeholders.py` で生成）。本番素材へは manifest.json 経由で差し替える。

## レイアウト（layout/）
- `bg.png`, `broll_placeholder.png`, `logo.png`, `badge_*.png`: **自作プレースホルダ**（同上）。

## フォント（fonts/）
- 本番は **Noto Sans CJK JP**（SIL Open Font License 1.1）を `assets/fonts/` に配置予定。
  ローカル開発では未配置時にシステムフォント（Meiryo 等）へフォールバックする。

## BGM・効果音（bgm/）
- 未配置。商用利用可の素材を追加した際に、素材名 / 配布元URL / ライセンスを本ファイルへ追記すること。

| 種別 | ファイル | 配布元 | ライセンス |
|------|----------|--------|-----------|
| （例）BGM | bgm/paper.mp3 | — | — |
