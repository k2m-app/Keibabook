import io
import sys
import streamlit as st

# keiba_bot.py から関数をインポート
from keiba_bot import run_all_races, set_race_params

PLACE_OPTIONS = [
    ("00", "京都"),
    ("01", "阪神"),
    ("02", "中京"),
    ("03", "小倉"),
    ("04", "東京"),
    ("05", "中山"),
    ("06", "福島"),
    ("07", "新潟"),
    ("08", "札幌"),
    ("09", "函館"),
]

def main():
    st.title("🏇 競馬ブック 全レース攻略アプリ（ローカル版）")

    st.markdown(
        "PCでSeleniumを動かして、ここから開催情報を指定して実行します。"
        "<br>実行ログとAIの回答は画面下に表示されます。",
        unsafe_allow_html=True,
    )

    # 入力フォーム
    year = st.text_input("年 (YYYY)", "2025")
    kai = st.text_input("回 (2桁)", "04")

    place = st.selectbox(
        "場所コード",
        options=PLACE_OPTIONS,
        format_func=lambda x: f"{x[0]}: {x[1]}",
    )
    place_code = place[0]  # ("00", "京都") → "00"

    day = st.text_input("日目 (2桁)", "07")

    if st.button("この開催の全レースを分析する"):
        # 標準出力をキャプチャして、print を画面に出す
        buffer = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buffer

        try:
            # まず開催情報をセットしてから実行
            set_race_params(year, kai, place_code, day)
            run_all_races()
        except Exception as e:
            print(f"[アプリ内エラー] {e}")
        finally:
            sys.stdout = old_stdout

        log_text = buffer.getvalue()
        st.text_area("実行ログ / AI分析結果", log_text, height=600)

if __name__ == "__main__":
    main()
