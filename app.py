import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

# --- 物理エンドポイント構成 ---
BLOB_ACCOUNT_URL = "https://koujisoutatsuwatcher.blob.core.windows.net/"
CONTAINER_NAME = "logs"
FUNCTION_TRIGGER_URL = "https://func-soutatsu-watcher.azurewebsites.net/api/search_now"
DEVELOPER_RESET_KEY = "developer-reset-9999"

# 1. Streamlit ページ基盤構成（必ず最初に記述）
st.set_page_config(
    page_title="Legal Guard Dashboard",
    page_icon="⚖️",
    layout="wide"
)

# 2. グローバル共有メモリ（アプリインスタンス内永続化スロット）
@st.cache_resource
def get_global_password_storage():
    return {"registered_password": None}

global_storage = get_global_password_storage()

# 3. Azure Blob Storage 実データ動的フェッチロジック
@st.cache_data(ttl=60)
def fetch_latest_log_data() -> pd.DataFrame:
    """Blobコンテナ内の時系列JSONログから最新のファイルを特定してDataFrameとして抽出"""
    try:
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(account_url=BLOB_ACCOUNT_URL, credential=credential)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        
        # 存在する全Blobをリスト化し、作成日時が最新のものを抽出
        blob_list = list(container_client.list_blobs())
        if not blob_list:
            return pd.DataFrame()
            
        latest_blob = max(blob_list, key=lambda b: b.creation_time)
        blob_client = container_client.get_blob_client(latest_blob.name)
        
        # バイナリロードおよびJSONデコード
        downloader = blob_client.download_blob()
        json_data = json.loads(downloader.readall())
        
        # Pandasデータフレームへのフラット化構造マッピング
        df = pd.json_normalize(json_data)
        return df
    except Exception as e:
        st.error(f"データ同期エラー: {str(e)}")
        return pd.DataFrame()

# 4. メインダッシュボードUIセクター
def main_dashboard():
    st.title("⚖️ 公示送達 常時監視ダッシュボード")
    st.markdown("---")
    
    df = fetch_latest_log_data()
    
    if df.empty:
        st.warning("Blob Storageに巡回ログが存在しません。右側サイドバーの「今すぐ自動巡回を実行」を押してください。")
    else:
        # タイムスタンプ構造の標準化
        latest_time = pd.to_datetime(df['datetime'].iloc[0]).strftime('%Y-%m-%d %H:%M:%S')
        st.caption(f"最終同期日時: {latest_time} (JST)")
        
        # 一致判定フラグの集計
        # 変更後
        matched_count = len(df[df['similarity'] >= 0.5]) if 'similarity' in df.columns else 0
        total_targets = len(df)
        
        # KPI メトリクス表示
        col1, col2 = st.columns(2)
        col1.metric(label="監視対象者 総数", value=f"{total_targets} 名")
        col2.metric(
            label="完全一致検出（警告）", 
            value=f"{matched_count} 件", 
            delta="即時対応を推奨" if matched_count > 0 else "異常なし", 
            delta_color="inverse"
        )
        
        st.markdown("### 📊 巡回解析結果一覧")
        
        # レンダリング用データフレームのアセンブル
        required_cols = ['name', 'similarity', 'url', 'emotion_score.sadness', 'emotion_score.anger']
        for col in required_cols:
            if col not in df.columns:
                df[col] = "データなし" if col == 'url' else 0.0
                
        display_df = df[required_cols].copy()
        display_df.columns = ['対象者氏名', '一致度(1.0=完全)', '該当URL', 'AI判定:悲壮感', 'AI判定:怒り']
        
        # 一致度最高値に対する条件付きグラフィカルハイライト
        st.dataframe(
            display_df.style.highlight_max(subset=['一致度(1.0=完全)'], color='#ffcccc'),
            use_container_width=True,
            height=400
        )

    # --- サイドバー・システム制御セクター ---
    with st.sidebar:
        st.header("⚡ システム制御")
        st.markdown("---")
        if st.button("🔄 今すぐ自動巡回を実行", use_container_width=True, type="primary"):
            with st.spinner("Azure Functionsを遠隔駆動中..."):
                try:
                    res = requests.get(FUNCTION_TRIGGER_URL, timeout=120)
                    if res.status_code == 200:
                        st.success("巡回完了。データを再同期します。")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"通信エラー (Status: {res.status_code}) - {res.text}")
                except Exception as e:
                    st.error(f"システム障害: {str(e)}")

# 5. セキュリティゲートキーパー
def check_auth():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if st.session_state["authenticated"]:
        return True

    if global_storage["registered_password"] is None:
        st.title("🔒 システム初期化：審査員専用ゲート")
        st.markdown("---")
        st.info("システムの確認・評価を開始するために、このアプリで使用する任意の評価用パスワードを設定してください。")
        pwd = st.text_input("設定するパスワード", type="password", key="gate_init")
        pwd_confirm = st.text_input("確認用入力", type="password", key="gate_init_confirm")
        if st.button("設定を確定してロックする", use_container_width=True):
            if pwd and pwd == pwd_confirm:
                global_storage["registered_password"] = pwd
                st.session_state["authenticated"] = True
                st.success("パスワードが正常にロックインされました。")
                st.rerun()
            else:
                st.error("入力が一致しないか、または空です。")
    else:
        st.title("🔒 Legal Guard - サインイン")
        st.markdown("---")
        st.warning("本システムは保護されています。初回設定時のパスワードを入力してください。")
        input_pwd = st.text_input("パスワードを入力", type="password", key="gate_login")
        if st.button("サインイン", use_container_width=True):
            if input_pwd == global_storage["registered_password"]:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("パスワードが正しくありません。")

    # 未認証画面でもリセットメニューを提供（st.stop()より前に完結）
    with st.sidebar:
        st.markdown("---")
        with st.expander("🛠️ 開発者・管理者メニュー"):
            master_key = st.text_input("マスターリセットキー", type="password", key="sys_dev_reset")
            if st.button("システム全初期化（初回画面へ戻す）", use_container_width=True):
                if master_key == DEVELOPER_RESET_KEY:
                    global_storage["registered_password"] = None
                    st.session_state["authenticated"] = False
                    st.cache_data.clear()
                    st.success("アプリのグローバルメモリを完全に初期化しました。")
                    st.rerun()
                else:
                    st.error("マスターキーが不正です。")
    return False


# --- ライフサイクル制御実行 ---
if check_auth():
    main_dashboard()
    with st.sidebar:
        st.markdown("---")
        with st.expander("🛠️ 開発者・管理者メニュー"):
            with st.form(key="reset_form"):
                master_key = st.text_input("マスターリセットキー", type="password")
                submitted = st.form_submit_button("システム全初期化（初回画面へ戻す）", use_container_width=True)
                if submitted:
                    if master_key == DEVELOPER_RESET_KEY:
                        global_storage["registered_password"] = None
                        st.session_state["authenticated"] = False
                        st.cache_data.clear()
                        st.success("アプリのグローバルメモリを完全に初期化しました。")
                        st.rerun()
                    else:
                        st.error("マスターキーが不正です。")
else:
    st.stop()