# 次にやることリスト

CLAUDE.mdのマイルストーン順（M4→M5→M6→M7）に対応するタスク一覧。
外部サービスの設定手順は `manual.md` を参照。

---

## M4: TikTok連携（運用開始・次はここ）

### あなたの作業（進行中）
- [x] TikTok Developersでアカウント作成・アプリ登録（アプリ名: `ai-news-studio`）
- [x] Privacy Policy / Terms of Service / Web-Desktop URLをGitHub Pagesで公開
      （`https://interkid.github.io/ai-news-studio/`、`docs/`配下。リポジトリ: `github.com/interkid/ai-news-studio`）
- [x] ドメイン所有権検証（signature file方式、URL prefix）完了・Verify通過済み
- [x] Products追加: **Login Kit** / **Content Posting API**（Share Kit・Webhook・Data Portability APIは不要と判断し追加せず）
- [x] 各Productの設定画面でスコープ有効化: `video.upload` / `user.info.basic` / `video.list`
- [x] Content Posting APIの設定内容を確認 → **「Upload to TikTok」（inbox下書き）はデフォルトで
      有効・審査不要**と明記されているのを確認（Target users登録などの追加対応は不要と判明）。
      「Direct Post」は使わない。「Verify domains」は`pull_by_url`方式専用で、本プロジェクトは
      `push_by_file`（チャンクアップロード）方式のため不要
- [x] **対応不要と判断**: 「Upload at least one demo video showing end-to-end flow with TikTok」欄は
      Submit for Review（本審査）フロー内の項目であり、Content Posting API設定ページで
      「Upload to TikTok（inbox下書き）はデフォルト有効・審査不要」と確認できたため、
      本審査自体を提出する必要がない。よってこの欄は未入力のまま、Submit for Reviewは押さずに進める
- [x] アプリ管理画面から **Client Key** / **Client Secret** を取得し `.env` に設定

### 実装（私が対応・完了）
- [x] `studio auth tiktok` コマンド実装（初回OAuth認可 → ローカルコールバックでcode受信 →
      トークン交換 → `oauth_tokens`テーブル(DB)に保存）
- [x] `publisher/tiktok.py`: OAuthトークン管理(自動リフレッシュ・ローテーション対応) +
      inboxチャンクアップロード + `status/fetch` でのポーリング
- [x] `publisher/kv.py`: Cloudflare Workers KVから承認状態(`video:{script_id}`)を読む
- [x] `studio publish` 実装（`src/studio/publish.py`）: KVポーリング→承認済み動画をTikTok
      下書きへ送信→LINEに完了通知。ローカルにレンダ済みファイルが無い場合はR2からダウンロード
      （GitHub Actions上でdaily/publishが別ジョブになる前提の設計）
- [x] `pipeline.run()` で R2アップロード後の`video_url`を`videos.r2_url`に永続化するよう修正
- [x] GitHub Actions ワークフロー新設（`.github/workflows/daily.yml` / `publish.yml`）:
      Python 3.11 + uv、VOICEVOXはDockerサービス、`data/studio.db`をactions/cacheで永続化
- [x] pytest追加（DB repository・チャンク分割・トークンrefresh・publish orchestration）、ruff通過

### 判明した問題と方針: Redirect URIはhttps必須
TikTok Login KitのRedirect URI(Web)は `https://` 以外を受け付けない
（`http://localhost:8921/callback` を登録しようとして実際に拒否されるのを確認済み）。
CLIツールなのでローカルでcodeを受け取りたいが、直接localhostを登録できない。

**方針**: GitHub Pages上に橋渡し用の静的ページ`docs/oauth-callback.html`を追加した。
このページはJSで`window.location.search`(code/state)をそのまま
`http://localhost:8921/callback`へリダイレクトするだけの中継地点。
TikTokにはこのhttpsページを登録し、実際のcode受信はそこからのJSリダイレクト経由でローカルの
`studio auth tiktok`が行う。実装済み(`config.py`の`tiktok_redirect_uri`のデフォルト値を
`https://interkid.github.io/ai-news-studio/oauth-callback.html`に変更、`cli.py`のローカル
サーバは`tiktok_local_callback_port`(デフォルト8921)で固定運用)。

### 次にやること
- [x] **`docs/oauth-callback.html` をGitHubにpush**
- [x] TikTok Developers側で **Login Kit の Redirect URI(Web) に
      `https://interkid.github.io/ai-news-studio/oauth-callback.html` を登録**
- [x] `studio auth tiktok` を実際に一度ローカル実行し、TikTokの認可・トークン取得までE2Eで確認
      （**重要**: 本番アプリの認可リクエストは`unauthorized_client`/`client_key`エラーで失敗した。
      未審査アプリはSandbox機能でTarget usersを登録しないとOAuthが通らないと判明。
      Manage apps → アプリ名横のスイッチを **Sandbox** に切替 → Create Sandbox →
      Sandbox側でもLogin Kit/Content Posting APIのProducts追加・スコープ有効化が別途必要
      （本番アプリの設定は引き継がれない）→ Sandbox settings → Target users → Add account
      でテスト用TikTokアカウントを登録（反映まで最大1時間）→ **`.env`の`TIKTOK_CLIENT_KEY`/
      `TIKTOK_CLIENT_SECRET`をSandbox側の値に差し替えて**`studio auth tiktok`実行→成功、
      `oauth_tokens`テーブルにトークン保存済み。
      本番運用時は審査済み本番アプリのclient_key/secretに戻す必要がある点に注意）
- [x] **方針決定**: GitHub Actionsで使うTikTokのclient_key/secretは当面Sandboxのまま進める
      （本番アプリの審査は待たない。Sandboxのtarget usersは自分のアカウントのみなので、
      無人自動投稿を本格運用する際は本番アプリの審査が別途必要になる点に注意）
- [ ] リポジトリ本体（`src/`・`tests/`・`.github/`等）のpushタイミングを相談
      （現状GitHubには`docs/`のみpush済み。daily.yml/publish.ymlをworkflow_dispatchで
      動かすにはこのpushが先に必要）
- [ ] GitHub Secretsへの全キー登録（`manual.md` 7章の一覧、TIKTOK_CLIENT_KEY/SECRETはSandbox側の値）
- [ ] `workflow_dispatch`で`daily.yml`→`publish.yml`を手動起動し、承認済み動画が実際に
      TikTokアプリの下書きに現れることを確認（E2Eテスト）
- [ ] （E2E確認が済み、必要と判明した場合のみ）TikTok連携の一連の流れを画面録画し、
      デモ動画として提出

### 保留中(意図的にOFF)
- [ ] **GitHub Actionsのcronは意図的に無効のまま**: `daily.yml`/`publish.yml`とも
      `workflow_dispatch`のみ有効。`# schedule:`をコメントアウトしてある
      （動画の品質チェックがまだのため、無人自動投稿はONにしない方針。M5の品質確認後に解禁）

### 補足: リポジトリの状態
- `github.com/interkid/ai-news-studio` は今回のTikTok申請対応で新規に作成・接続した
  （ローカルの`ticktok_auto/`ディレクトリを`git init`し、リモートとして接続済み）
- **現時点でpush済みなのは`docs/`配下のみ**（index.html / privacy.html / terms.html / 検証ファイル / `.nojekyll`）。
  プロジェクト本体のソースコード一式（`src/`・`tests/`等）はまだpushしていない
  （GitHub Actions運用開始時に別途pushタイミングを相談する）

---

## M5: デザイン・ネタ・インパクト構成強化

- [ ] **キャラ/背景素材の刷新**: `assets/characters/`・`assets/layout/` のプレースホルダ（自作イラスト）を
      本番品質の素材に差し替え（`manifest.json` 経由なのでレンダラー側の改修は不要な想定）
- [ ] **演出バリエーション追加**: `renderer/effects.py` に新しいエフェクトを追加
- [ ] **ネタ選定への人間の事前レビュー機能**: `studio pipeline` のcollector実行後・台本生成前に、
      LINE等で収集した候補トピック一覧を確認し、選定に人間の判断を挟める仕組みを追加
      （現状は`collector`のLLM採点のみで自動的に上位1件へ進む設計）
- [ ] **フック/展開/オチのテンプレ化**: `scriptwriter/generate.py` のプロンプトを
      「つかみ→展開→オチ/示唆」の型に沿うよう構成強化し、10〜20秒でのインパクトを安定させる

---

## M6: 分析ループ（SPEC原文のM5をここに移動）

- [ ] `analytics/` モジュール: TikTok Display APIで投稿48h後・7日後のviews/likes/comments/sharesを取得
- [ ] `weekly.yml`: 週次でLLMに直近4週の成績・却下理由を渡し、「伸びた型/沈んだ型」分析
- [ ] `prompt_insights` テーブルの自動更新（旧行はinactive化、新知見を台本生成プロンプトへ反映）
- [ ] 週次レポートのLINE送信

---

## M7: 運用強化（任意・元M6の残り）

- [ ] コメント返信ドラフト生成（`video.list` + LLM → LINEに返信案送付）
- [ ] 1日2〜3本への増産スイッチ、コーナー別A/B集計ビュー
- [ ] Layer3: 週1〜2本の勝負ネタ限定フック映像（動画生成AI、予備費の範囲内）

---

## 現在地点

M1〜M3実装済み・E2E動作確認済み（`studio render` / `studio pipeline` / LINE承認フロー）。
M4はTikTok Developer側の準備完了（アプリ登録・URL検証・Products追加・スコープ有効化・
Client Key/Secret取得まですべて完了）、コード実装（`studio auth tiktok` / `publisher/tiktok.py` /
`studio publish` / GitHub Actions）も完了。

現在のブロッカー: Login KitのRedirect URIがhttps必須と判明し、GitHub Pages経由の橋渡しページ
(`docs/oauth-callback.html`)を用意して対応済みだが**まだpush・TikTok側への登録が済んでいない**。
これが済めば`studio auth tiktok`でトークン取得→E2E確認に進める。
GitHub Actionsのcronは品質チェック待ちで意図的に保留中(手動実行のみ有効)。
未設定: `FAL_KEY`（任意）。`TIKTOK_REFRESH_TOKEN`はDB(`oauth_tokens`)にもまだ無く未認可の状態。
