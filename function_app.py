import azure.functions as func
import logging
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import requests
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient

# 物理エンドポイント定義
KEYVAULT_ENDPOINT = "https://koujisoutatsu.vault.azure.net/"
BLOB_ENDPOINT = "https://koujisoutatsuwatcher.blob.core.windows.net/"
CONTAINER_NAME = "logs"
BING_SEARCH_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
JST = timezone(timedelta(hours=9))

app = func.FunctionApp()

def execute_巡回_pipeline() -> str:
    """エンタープライズ対応: 公示送達自動巡回コアパイプライン"""
    logging.info("共通自動巡回コアロジックが始動しました。")
    credential = DefaultAzureCredential()
    secret_client = SecretClient(vault_url=KEYVAULT_ENDPOINT, credential=credential)

    # 1. 秘密情報のセキュアな抽出
    try:
        target_list = json.loads(secret_client.get_secret("target-list").value)
        bing_key = secret_client.get_secret("bing-search-key").value
    except Exception as e:
        error_msg = f"致命的エラー: Key Vaultからの必須リソース抽出に失敗 - {str(e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg)

    try:
        alert_webhook_url = secret_client.get_secret("alert-webhook-url").value
    except Exception:
        alert_webhook_url = None
        logging.warning("通知用Webhookが未登録です。アラート機能はバイパスされます。")

    if not target_list:
        return "監視対象者が空のため、走査シーケンスを安全に終了しました。"

    # 2. TCPセッションプーリングによるBing API高速走査
    results: List[Dict[str, Any]] = []
    alert_targets: List[Dict[str, str]] = []
    current_jst_str = datetime.now(JST).isoformat()

    with requests.Session() as session:
        session.headers.update({"Ocp-Apim-Subscription-Key": bing_key})

        for target_id, target_name in target_list.items():
            params = {
                "q": f'site:courts.go.jp {target_name}',
                "count": 5,
                "mkt": "ja-JP",
                "safesearch": "Off"
            }

            similarity_score = 0.00
            detected_url = "該当なし"
            sadness_score, anger_score = 0, 0
            api_error = False

            try:
                # レートリミット保護のための微小ジッター
                time.sleep(0.3)
                response = session.get(BING_SEARCH_ENDPOINT, params=params, timeout=10)
                response.raise_for_status()

                web_pages = response.json().get("webPages", {}).get("value", [])

                if web_pages:
                    detected_url = web_pages[0].get("url", "")
                    snippet = f"{web_pages[0].get('name', '')} {web_pages[0].get('snippet', '')}"

                    if target_name in snippet:
                        similarity_score = 1.00
                        alert_targets.append({
                            "name": target_name,
                            "url": detected_url,
                            "snippet": web_pages[0].get("snippet", "")
                        })
                    else:
                        similarity_score = 0.50

                    if any(x in snippet for x in ["離婚", "破産", "訴訟", "差押", "支払督促"]):
                        sadness_score, anger_score = 90, 50
                    else:
                        sadness_score, anger_score = 30, 10

            except requests.exceptions.RequestException as api_err:
                logging.error(f"Bing API通信例外（ターゲット: {target_name}）: {str(api_err)}")
                api_error = True

            results.append({
                "datetime": current_jst_str,
                "id": int(target_id),
                "name": target_name,
                "similarity": similarity_score,
                "url": detected_url,
                "api_error": api_error,
                "emotion_score": {"sadness": sadness_score, "anger": anger_score}
            })

    # 3. アラート発火セクター（バルク送信最適化）
    if alert_targets and alert_webhook_url:
        embeds = [{
            "title": "🚨 【警告】公示送達・裁判所インデックス完全一致検出",
            "description": f"監視対象者: **{t['name']}** が裁判所の公開情報内に捕捉されました。\n速やかに本番システムを確認してください。",
            "url": t["url"],
            "color": 15158332,
            "fields": [
                {"name": "検出スニペット", "value": t["snippet"][:250], "inline": False},
                {"name": "証拠URL", "value": t["url"], "inline": False}
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        } for t in alert_targets]

        payload = {
            "username": "Legal Guard Bot",
            "content": f"⚠️ **【重大警告】計 {len(alert_targets)} 件の対象者痕跡を検知しました。**",
            "embeds": embeds[:10]
        }
        try:
            requests.post(alert_webhook_url, json=payload, timeout=10)
        except Exception as alert_err:
            logging.error(f"アラート送信例外: {str(alert_err)}")

    # 4. Blob Storageへの永続化
    blob_service_client = BlobServiceClient(account_url=BLOB_ENDPOINT, credential=credential)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)

    try:
        container_client.create_container()
    except Exception:
        pass  # コンテナ既存時は無視

    blob_name = f"run_{datetime.now(JST).strftime('%Y%m%d_%H%M%S')}_log.json"

    try:
        container_client.upload_blob(
            name=blob_name,
            data=json.dumps(results, ensure_ascii=False, indent=4),
            overwrite=True
        )
    except Exception as blob_err:
        logging.error(f"Blob書き込み例外: {str(blob_err)}")
        raise

    return f"自動巡回正常完了: {blob_name} へログを書き込みました。検知数: {len(alert_targets)}"


# --- トリガー定義 ---
@app.schedule(schedule="0 0 0 * * *", arg_name="myTimer", run_on_startup=False, use_monitor=True)
def timer_search_now(myTimer: func.TimerRequest) -> None:
    logging.info("タイマートリガー定時バッチ起動")
    try:
        logging.info(execute_巡回_pipeline())
    except Exception as e:
        logging.error(f"定時巡回システム例外: {str(e)}")

@app.route(route="search_now", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def http_search_now(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("HTTPトリガー手動巡回要求受信")
    try:
        msg = execute_巡回_pipeline()
        return func.HttpResponse(json.dumps({"status": "success", "message": msg}, ensure_ascii=False), mimetype="application/json", status_code=200)
    except Exception as e:
        return func.HttpResponse(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False), mimetype="application/json", status_code=500)