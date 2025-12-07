import streamlit as st
import keiba_bot  # keiba_bot.py を読み込む

# Supabase と日付用
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone

# ★Supabase の設定（Secrets から取得）
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY", "")

@st.cache_resource
def get_supabase_client() -> Client:
    """Supabase クライアントを1回だけ作って使い回す"""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def show_history():
    """直近1週間の履歴を Supabase から取り出して表示する"""
    supabase = get_supabase_client()
    if supabase is None:
        st.error("Supabase の設定がされていないため、履歴を表示できません。")
        st.info("streamlit の Secrets に SUPABASE_URL と SUPABASE_ANON_KEY を追加してください。")
        return

    # 7日前の日時（UTC）を計算して、それ以降のデータだけを取得
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    seven_days_ago_iso = seven_days_ago.isoformat()

    try:
        res = (
            supabase
            .table("history")
            .select("*")
            .gte("created_at", seven_days_ago_iso)
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data
    except Exception as e:
        st.error(f"履歴の取得に失敗しました: {e}")
        return

    st.subheader("直近1週間の履歴")

    if not rows:
        st.info("直近1週間の履歴はまだありません。")
        return

    # 1件ずつ、折りたたみ形式で表示
    for row in rows:
        title = f"{row.get('created_at', '')} / {row.get('place_name', '')} {row.get('race_num', '')}R"
        with st.expander(title):
            st.write(f"**日付**: {row.get('created_at', '')}")
            st.write(
                f"**開催**: {row.get('year', '')}年 "
                f"{row.get('kai', '')}回 "
                f"{row.get('place_name', '')} "
                f"{row.get('day', '')}日目"
            )
            st.write(f"**レース**: {row.get('race_num', '')}R（ID: {row.get('race_id', '')}）")
            st.write("---")
            st.write("**AI予想結果**")
            st.write(row.get("output_text", ""))


# 画面のタイトル
st.title("🐎 競馬AI分析アプリ")

# ★予想モード or 履歴モードを選ぶ
mode = st.sidebar.radio("メニュー", ["予想する", "直近1週間の履歴を見る"])

if mode == "予想する":
    # --- サイドバーで設定 ---
    st.sidebar.header("開催設定")

    # 入力フォーム
    year = st.sidebar.text_input("年 (YEAR)", "2025")

    # 01〜06までのリストを作成
    kai_options = [f"{i:02}" for i in range(1, 7)]
    kai = st.sidebar.selectbox("回 (KAI)", kai_options, index=3)  # デフォルト04

    # 01〜12までのリストを作成
    day_options = [f"{i:02}" for i in range(1, 13)]
    day = st.sidebar.selectbox("日目 (DAY)", day_options, index=6)  # デフォルト07

    # 場所コードの選択肢
    places = {
        "00": "京都", "01": "阪神", "02": "中京", "03": "小倉",
        "04": "東京", "05": "中山", "06": "福島", "07": "新潟",
        "08": "札幌", "09": "函館"
    }
    place_name = st.sidebar.selectbox("競馬場 (PLACE)", list(places.values()), index=4)  # デフォルト東京
    place_code = [k for k, v in places.items() if v == place_name][0]

    # ★どのレースを分析するか選ぶ（チェックボックス）
    st.sidebar.header("分析するレースを選択")
    selected_races = []
    for i in range(1, 13):
        # デフォルトで 1R だけ ON
        if st.sidebar.checkbox(f"{i}R", value=(i == 1)):
            selected_races.append(i)

    # --- メイン画面 ---
    st.write(f"### 設定: {year}年 {kai}回 {place_name} {day}日目")
    st.write("サイドバーでレースを選んでから、ボタンを押すと分析を開始します。")

    # ボタンが押されたら実行
    if st.button("分析スタート 🚀"):
        if not selected_races:
            st.warning("少なくとも1つのレースを選んでください。")
        else:
            with st.spinner("分析中...これには数分かかります..."):
                try:
                    # 1. 設定値をbotに渡す
                    keiba_bot.set_race_params(year, kai, place_code, day)
                    
                    # 2. 選択されたレースだけ実行する
                    keiba_bot.run_all_races(target_races=selected_races)
                    
                    st.success(
                        f"{', '.join(f'{r}R' for r in selected_races)} の分析が完了しました！"
                    )
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

elif mode == "直近1週間の履歴を見る":
    show_history()
