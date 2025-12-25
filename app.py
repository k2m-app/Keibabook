import streamlit as st
import keiba_bot

st.set_page_config(page_title="KeibaBook AI", layout="wide")

PLACE_NAMES = {
    "00": "京都", "01": "阪神", "02": "中京", "03": "小倉", "04": "東京",
    "05": "中山", "06": "福島", "07": "新潟", "08": "札幌", "09": "函館",
}

# -----------------------------
# State 初期化
# -----------------------------
if "selected_races" not in st.session_state:
    st.session_state.selected_races = set()

if "auto_params" not in st.session_state:
    st.session_state.auto_params = None  # (year,kai,place,day)

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.title("設定")

st.sidebar.caption("1) 自動で直近開催を取得 → 2) レース選択 → 3) 実行")

if st.sidebar.button("📌 直近の開催を自動取得"):
    with st.spinner("Keibabookへログインして直近開催を検出中..."):
        params = keiba_bot.auto_detect_meet_params()
    if params:
        st.session_state.auto_params = params
        year, kai, place, day = params
        keiba_bot.set_race_params(year, kai, place, day)
        st.sidebar.success(f"自動取得: {year}-{kai}-{PLACE_NAMES.get(place,'?')}-{day}日目")
    else:
        st.sidebar.error("直近開催を検出できませんでした（ページ構造変更/導線なし等）。")

# 現在値（自動取得後はそれが入る）
cur_year, cur_kai, cur_place, cur_day = keiba_bot.get_current_params()

st.sidebar.subheader("開催パラメータ（手動修正OK）")
year = st.sidebar.text_input("年 (YYYY)", value=cur_year)
kai = st.sidebar.text_input("回 (2桁)", value=cur_kai)
place = st.sidebar.selectbox(
    "競馬場",
    options=list(PLACE_NAMES.keys()),
    index=list(PLACE_NAMES.keys()).index(cur_place) if cur_place in PLACE_NAMES else 0,
    format_func=lambda x: f"{x} : {PLACE_NAMES.get(x,'?')}",
)
day = st.sidebar.text_input("日 (2桁)", value=cur_day)

if st.sidebar.button("✅ この開催に設定"):
    keiba_bot.set_race_params(year, kai, place, day)
    st.sidebar.success("開催パラメータを反映しました。")

# -----------------------------
# レース選択 UI
# -----------------------------
st.title("KeibaBook AI（全レース/指定レース 実行）")

colA, colB, colC = st.columns([1, 1, 2])

def set_all_races():
    st.session_state.selected_races = set(range(1, 13))

def clear_all_races():
    st.session_state.selected_races = set()

with colA:
    if st.button("✅ 全レース選択"):
        set_all_races()

with colB:
    if st.button("🧹 全解除"):
        clear_all_races()

with colC:
    st.caption("チェックボックスは状態保持されます（全レース選択も確実に入る設計）。")

# チェックボックス 1~12
st.subheader("レース選択（1〜12R）")

grid = st.columns(6)
for i in range(1, 13):
    col = grid[(i - 1) % 6]
    key = f"race_{i}"

    # 既存stateから初期値
    initial = (i in st.session_state.selected_races)

    val = col.checkbox(f"{i}R", value=initial, key=key)
    if val:
        st.session_state.selected_races.add(i)
    else:
        st.session_state.selected_races.discard(i)

st.divider()

# -----------------------------
# 実行
# -----------------------------
run_mode = st.radio(
    "実行モード",
    options=["選択レースだけ実行", "全レース実行（1〜12）"],
    index=0,
    horizontal=True,
)

if st.button("🚀 実行開始", type="primary"):
    y, k, p, d = keiba_bot.get_current_params()
    place_name = PLACE_NAMES.get(p, "不明")
    st.info(f"実行対象：{y}年 {k}回 {place_name} {d}日目")

    if run_mode == "全レース実行（1〜12）":
        keiba_bot.run_all_races(target_races=None)
    else:
        if not st.session_state.selected_races:
            st.warning("レースが未選択です。少なくとも1つチェックしてください。")
        else:
            keiba_bot.run_all_races(target_races=st.session_state.selected_races)
