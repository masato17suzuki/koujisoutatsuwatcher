# 送達ウォッチャー（Soutatsu Watcher）

## 概要

令和8年5月21日施行の改正民事訴訟法（民訴111条）により、公示送達がオンライン公開に移行したことを受け、裁判所サイト（courts.go.jp）における公示送達情報をAIで自動監視するサービスです。

「多分日本一早く公開された公示送達のAI化」として、Microsoft Agent Hackathon 2026に提出しています。

---

## アーキテクチャ
Azure Functions（HTTPトリガー / 日次タイマー）
　　↓
Bing Search API（site:courts.go.jp クエリ）
　　↓
Azure Blob Storage（JSONログ永続化）
　　↓
Streamlit Dashboard（監視結果可視化）

---

## 機能

- 登録対象者名をBing Search APIでcourts.go.jp内検索
- 一致度スコアリング（1.00=完全一致 / 0.50=部分一致 / 0.00=未検出）
- 完全一致時にDiscord Webhookでアラート発火
- Streamlitダッシュボードで監視結果をリアルタイム表示
- 審査員専用パスワードゲート搭載

---

## 技術スタック

| レイヤー | 技術 |
|---|---|
| バックエンド | Azure Functions v4 (Python) |
| 検索 | Bing Search API v7 |
| 秘密情報管理 | Azure Key Vault |
| ストレージ | Azure Blob Storage |
| フロントエンド | Streamlit (Community Cloud) |

---

## デモ

[Streamlit Dashboard URL]（審査員用パスワードは提出フォームに記載）

---

## 制約事項

Bing SearchのインデックスおよびスニペットはGoogle比で収録率・精度が低く、courts.go.jpの一部ページが検索結果に反映されない制約が確認されています。次バージョンではcourts.go.jp直接ポーリングへの移行を予定しています。

---

## セットアップ

### バックエンド

1. Azure Key Vaultに以下のシークレットを登録
   - `target-list`：監視対象者のJSON（例：`{"1": "山田太郎"}`）
   - `bing-search-key`：Bing Search APIキー
   - `alert-webhook-url`：Discord Webhook URL（任意）

2. Azure Functionsにデプロイ
func azure functionapp publish func-soutatsu-watcher

### フロントエンド

1. Streamlit Community CloudのSecretsに以下を設定
```toml
AZURE_STORAGE_CONNECTION_STRING = "接続文字列"
```

2. `frontend/app.py` をデプロイ

---

## ライセンス

MIT
