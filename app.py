import streamlit as st
import keiba_bot  # keiba_bot.py を読み込む

# Supabase と日付用
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone


# 画面のタイトル
st.title("🐎 競馬AI分析アプリ")

# --- サイドバーで設定 ---
st.sidebar.header("開催設定")

# 入力フォーム
year = st.sidebar.text_input("年 (YEAR)", "2025")

# ▼▼ ここを変更しました（自動でリストを作る記述） ▼▼
# 01〜06までのリストを作成
kai_options = [f"{i:02}" for i in range(1, 7)] 
kai = st.sidebar.selectbox("回 (KAI)", kai_options, index=3) # デフォルトはリストの4番目(04)

# 01〜12までのリストを作成
day_options = [f"{i:02}" for i in range(1, 13)]
day = st.sidebar.selectbox("日目 (DAY)", day_options, index=6) # デフォルトはリストの7番目(07)
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

# 場所コードの選択肢
places = {
    "00": "京都", "01": "阪神", "02": "中京", "03": "小倉",
    "04": "東京", "05": "中山", "06": "福島", "07": "新潟",
    "08": "札幌", "09": "函館"
}
# ユーザーには日本語で選ばせて、裏でコード(04など)に変換
place_name = st.sidebar.selectbox("競馬場 (PLACE)", list(places.values()), index=4) # デフォルト東京
place_code = [k for k, v in places.items() if v == place_name][0]

# --- メイン画面 ---
st.write(f"### 設定: {year}年 {kai}回 {place_name} {day}日目")
st.write("ボタンを押すと、競馬ブックにログインして分析を開始します。")

# ボタンが押されたら実行
if st.button("分析スタート 🚀"):
    with st.spinner("分析中...これには数分かかります..."):
        try:
            # 1. 設定値をbotに渡す
            keiba_bot.set_race_params(year, kai, place_code, day)
            
            # 2. 実行する
            keiba_bot.run_all_races()
            
            st.success("全てのレースの分析が完了しました！")
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")

