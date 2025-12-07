import time
import requests
import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# ★追加：HTMLパース用
from bs4 import BeautifulSoup

# ★追加：Supabase 用
from supabase import create_client, Client

# ==================================================
# 【設定エリア】
# ==================================================

# 1. ログイン情報（Secretsから取得）
KEIBA_ID = st.secrets.get("KEIBA_ID", "")
KEIBA_PASS = st.secrets.get("KEIBA_PASS", "")

# 2. Dify APIキー（Secretsから取得）
DIFY_API_KEY = st.secrets.get("DIFY_API_KEY", "")

# 3. Supabase の URL と anon key（Secrets から取得）
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY", "")


@st.cache_resource
def get_supabase_client() -> Client:
    """Supabase クライアントを1回だけ作って使い回す"""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        # app.py 側で None を見てエラーメッセージを出す前提
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def save_history(year, kai, place_code, place_name, day, race_num_str, race_id, ai_answer):
    """1レース分のAI出力を Supabase の history テーブルに保存する"""
    supabase = get_supabase_client()
    if supabase is None:
        # Supabase 未設定の場合は何もせずスキップ
        print("⚠ Supabase 未設定のため履歴保存をスキップしました。")
        return

    data = {
        "year": str(year),
        "kai": str(kai),
        "place_code": str(place_code),
        "place_name": place_name,
        "day": str(day),
        "race_num": race_num_str,
        "race_id": race_id,
        "output_text": ai_answer,
    }

    try:
        supabase.table("history").insert(data).execute()
        print("💾 履歴を保存しました。")
    except Exception as e:
        print(f"⚠ 履歴の保存に失敗しました: {e}")


# 3. 開催情報（デフォルト値）
YEAR = "2025"
KAI = "04"
PLACE = "00"
DAY = "07"


# ================================
# 開催情報を外からセットする用の関数
# ================================
def set_race_params(year, kai, place, day):
    global YEAR, KAI, PLACE, DAY
    YEAR = year
    KAI = kai
    PLACE = place
    DAY = day


# ==================================================
# 前走インタビュー用パーサー
# ==================================================
def parse_zenkoso_interview(html: str):
    """
    前走インタビューページのHTMLから
    1頭1レコードのリストを返す。

    戻り値例:
    [
      {
        "waku": "1",
        "umaban": "1",
        "name": "エイユーファイヤー",
        "prev_date_course": "2025/09/27 阪神6Ｒ",
        "prev_class": "３歳上１勝クラス",
        "prev_finish": "4着",
        "prev_comment": "エイユーファイヤー（４着）中井裕騎手 ..."
      },
      ...
    ]
    """
    soup = BeautifulSoup(html, "html.parser")

    # 「前走のインタビュー」のテーブルを特定
    h2 = soup.find("h2", string=lambda s: s and "前走のインタビュー" in s)
    if not h2:
        return []

    midasi_div = h2.find_parent("div", class_="midasi")
    table = midasi_div.find_next("table", class_="syoin")
    if not table or not table.tbody:
        return []

    rows = table.tbody.find_all("tr")
    result = []

    i = 0
    while i < len(rows):
        row = rows[i]

        # spacer 行はスキップ
        if "spacer" in (row.get("class") or []):
            i += 1
            continue

        # 枠・馬番・馬名行を判定
        waku_td = row.find("td", class_="waku")
        umaban_td = row.find("td", class_="umaban")
        bamei_td = row.find("td", class_="bamei")
        if not (waku_td and umaban_td and bamei_td):
            i += 1
            continue

        waku = waku_td.get_text(strip=True)
        umaban = umaban_td.get_text(strip=True)
        name = bamei_td.get_text(strip=True)

        # 次の行が syoin 詳細のはず
        detail_row = rows[i + 1] if i + 1 < len(rows) else None
        prev_date_course = ""
        prev_class = ""
        prev_finish = ""
        prev_comment = ""

        if detail_row:
            syoin_td = detail_row.find("td", class_="syoin")
            if syoin_td:
                # 前走の日付＋コース
                syoindata = syoin_td.find("div", class_="syoindata")
                if syoindata:
                    ps = syoindata.find_all("p")
                    if len(ps) >= 1:
                        prev_date_course = ps[0].get_text(strip=True)
                    if len(ps) >= 2:
                        spans = ps[1].find_all("span")
                        if len(spans) >= 1:
                            prev_class = spans[0].get_text(strip=True)
                        if len(spans) >= 2:
                            prev_finish = spans[1].get_text(strip=True)

                # コメント（syoin_td直下の<p>だけ拾う）
                direct_ps = syoin_td.find_all("p", recursive=False)
                if direct_ps:
                    comment_text = direct_ps[0].get_text(strip=True)
                    if comment_text != "－":  # 「－」はコメントなし
                        prev_comment = comment_text.lstrip("　 ").rstrip()

        result.append(
            {
                "waku": waku,
                "umaban": umaban,
                "name": name,
                "prev_date_course": prev_date_course,
                "prev_class": prev_class,
                "prev_finish": prev_finish,
                "prev_comment": prev_comment,
            }
        )

        # 1セット分進める：
        #  [0] 馬情報行
        #  [1] syoin 詳細行
        #  [2] spacer 行（あれば）
        i += 2
        if i < len(rows) and "spacer" in (rows[i].get("class") or []):
            i += 1

    return result


def format_zenkoso_text(zenkoso_list):
    """parse_zenkoso_interview の結果を、LLM に渡しやすいテキストに整形"""
    if not zenkoso_list:
        return "（前走インタビュー情報は取得できませんでした）"

    lines = []
    for h in zenkoso_list:
        head = f"[{h['waku']}枠{h['umaban']}番 {h['name']}]"
        race_info = " / ".join(
            x
            for x in [
                h.get("prev_date_course") or "",
                h.get("prev_class") or "",
                h.get("prev_finish") or "",
            ]
            if x
        )
        comment = h.get("prev_comment") or "コメントなし"
        line = f"{head}\n  前走: {race_info}\n  コメント: {comment}"
        lines.append(line)

    return "\n\n".join(lines)


# ================================
# メイン処理
# ================================
def run_all_races():
    base_race_id = f"{YEAR}{KAI}{PLACE}{DAY}"
    place_names = {
        "00": "京都",
        "01": "阪神",
        "02": "中京",
        "03": "小倉",
        "04": "東京",
        "05": "中山",
        "06": "福島",
        "07": "新潟",
        "08": "札幌",
        "09": "函館",
    }
    place_name = place_names.get(PLACE, "不明な競馬場")

    print(f"🚀 {YEAR}年{KAI}回 {place_name} {DAY}日目の全レース攻略を開始します！")

    # ▼▼ クラウド用設定（ヘッドレスモード） ▼▼
    options = Options()
    options.add_argument("--headless")  # 画面を表示しない
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # ドライバー起動
    driver = webdriver.Chrome(options=options)

    try:
        # --- ログイン部分 ---
        print("🌍 競馬ブックにログイン画面へ移動中...")
        driver.get("https://s.keibabook.co.jp/login/login")

        # 1. ID入力
        id_box = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.NAME, "login_id"))
        )
        id_box.clear()
        id_box.send_keys(KEIBA_ID)
        time.sleep(1)

        # 2. パスワード入力
        pass_box = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
        )
        pass_box.clear()
        pass_box.send_keys(KEIBA_PASS)
        time.sleep(1)

        # 3. ログインボタン
        try:
            login_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "btn-login"))
            )
            login_btn.click()
        except Exception:
            submit_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit']"))
            )
            submit_btn.click()

        print("✨ ログイン処理完了（画面遷移を待ちます）")
        time.sleep(3)

        # --- 1Rから12Rまでループ処理 ---
        for i in range(1, 13):
            race_num_str = f"{i:02}"
            current_race_id = base_race_id + race_num_str

            print("\n" + "=" * 40)
            print(f"🐎 {place_name} {i}R (ID:{current_race_id}) の情報を収集中...")

            try:
                # URL作成
                url_danwa = f"https://s.keibabook.co.jp/cyuou/danwa/0/{current_race_id}"
                url_interview = f"https://s.keibabook.co.jp/cyuou/syoin/{current_race_id}"

                # -------------------------------------------------------
                # 1. 厩舎の話 ＋ レース情報
                # -------------------------------------------------------
                driver.get(url_danwa)
                time.sleep(1)

                if "login" in driver.current_url:
                    print("⚠️ ログインが外れている可能性があります！（厩舎の話ページ）")
                    continue

                # レースタイトル部分を取得
                race_title_block = WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.racetitle"))
                )
                race_title_text = race_title_block.text.strip()

                # 厩舎の話テーブル
                danwa_table = driver.find_element(By.CSS_SELECTOR, "table.default.danwa")
                danwa_table_text = danwa_table.text.strip()

                # -------------------------------------------------------
                # 2. 前走インタビュー（HTMLパースで全頭取得）
                # -------------------------------------------------------
                driver.get(url_interview)
                time.sleep(1)

                if "login" in driver.current_url:
                    print("⚠️ ログインが外れている可能性があります！（前走インタビュー）")
                    continue

                html_interview = driver.page_source
                zenkoso_list = parse_zenkoso_interview(html_interview)
                zenkoso_text = format_zenkoso_text(zenkoso_list)

                # -------------------------------------------------------
                # 2.5 LLM に渡す入力テキストを組み立て
                # -------------------------------------------------------
                full_text = (
                    f"【{place_name} {i}Rのデータ】\n"
                    "■レース情報\n"
                    f"{race_title_text}\n\n"
                    "■厩舎の話（枠番・馬番・馬名・コメント）\n"
                    f"{danwa_table_text}\n\n"
                    "■前走インタビュー（全頭分）\n"
                    f"{zenkoso_text}\n"
                )

                # -------------------------------------------------------
                # 3. Difyに分析させる
                # -------------------------------------------------------
                print(f"🧠 {place_name} {i}Rを分析中...")

                url = "https://api.dify.ai/v1/workflows/run"
                headers = {
                    "Authorization": f"Bearer {DIFY_API_KEY}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "inputs": {"text": full_text},
                    "response_mode": "blocking",
                    "user": "keiba-bot-user",
                }

                response = requests.post(url, headers=headers, json=payload)

                if response.status_code == 200:
                    result = response.json()
                    outputs = result.get("data", {}).get("outputs") or result.get("data") or {}
                    ai_answer = outputs.get("answer")

                    if ai_answer:
                        print(f"🎯 {place_name} {i}R 分析完了:")
                        print("-" * 20)
                        print(ai_answer)

                        # Streamlit画面にも表示
                        st.write(f"### {place_name} {i}R")
                        st.write(ai_answer)
                        st.write("---")

                        # ★ここで履歴を Supabase に保存
                        save_history(
                            YEAR,            # 例: "2025"
                            KAI,             # 例: "04"
                            PLACE,           # 例: "00"
                            place_name,      # 例: "京都"
                            DAY,             # 例: "07"
                            race_num_str,    # 例: "01"
                            current_race_id, # 例: "202504000701"
                            ai_answer,       # 予想結果テキスト
                        )

                    else:
                        print("⚠️ 分析はできたけど、返事が空っぽでした...")
                else:
                    print(f"❌ {i}Rのエラー: Dify通信失敗 (コード: {response.status_code})")

            except Exception as e:
                print(f"❌ {i}R処理中にエラー: {e}")

    finally:
        print("\n🧹 ブラウザを閉じます")
        driver.quit()


if __name__ == "__main__":
    run_all_races()
