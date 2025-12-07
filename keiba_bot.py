import time
import requests
import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
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

# 4. 開催情報（デフォルト）
YEAR = "2025"
KAI = "04"
PLACE = "02"
DAY = "02"

def set_race_params(year, kai, place, day):
    """app.py から開催情報を受け取って上書き"""
    global YEAR, KAI, PLACE, DAY
    YEAR = str(year)
    KAI = str(kai).zfill(2)
    PLACE = str(place).zfill(2)
    DAY = str(day).zfill(2)


# ==================================================
# Supabase
# ==================================================
@st.cache_resource
def get_supabase_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def save_history(year, kai, place_code, place_name, day, race_num_str, race_id, ai_answer):
    supabase = get_supabase_client()
    if supabase is None:
        print("⚠ Supabase 未設定のため履歴保存スキップ")
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
        print("💾 履歴保存成功")
    except Exception as e:
        print(f"⚠ 履歴保存失敗: {e}")


# ==================================================
# HTMLパース関数
# ==================================================
def parse_zenkoso_interview(html: str):
    soup = BeautifulSoup(html, "html.parser")
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
        if "spacer" in (row.get("class") or []):
            i += 1
            continue

        waku_td = row.find("td", class_="waku")
        umaban_td = row.find("td", class_="umaban")
        bamei_td = row.find("td", class_="bamei")

        if not (waku_td and umaban_td and bamei_td):
            i += 1
            continue

        waku = waku_td.get_text(strip=True)
        umaban = umaban_td.get_text(strip=True)
        name = bamei_td.get_text(strip=True)

        prev_date_course = ""
        prev_class = ""
        prev_finish = ""
        prev_comment = ""

        detail_row = rows[i + 1] if i + 1 < len(rows) else None
        if detail_row:
            syoin_td = detail_row.find("td", class_="syoin")
            if syoin_td:
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

                direct_ps = syoin_td.find_all("p", recursive=False)
                if direct_ps:
                    txt = direct_ps[0].get_text(strip=True)
                    if txt != "－":
                        prev_comment = txt

        result.append({
            "waku": waku,
            "umaban": umaban,
            "name": name,
            "prev_date_course": prev_date_course,
            "prev_class": prev_class,
            "prev_finish": prev_finish,
            "prev_comment": prev_comment,
        })

        i += 2
        if i < len(rows) and "spacer" in (rows[i].get("class") or []):
            i += 1

    return result


def parse_danwa_comments(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="danwa")
    if not table:
        return {}

    danwa_dict = {}
    rows = table.tbody.find_all("tr")
    current_umaban = None

    for row in rows:
        umaban_td = row.find("td", class_="umaban")
        if umaban_td:
            current_umaban = umaban_td.get_text(strip=True)
            continue

        danwa_td = row.find("td", class_="danwa")
        if danwa_td and current_umaban:
            danwa_dict[current_umaban] = danwa_td.get_text(strip=True)
            current_umaban = None

    return danwa_dict


# ==================================================
# メイン処理（★ここが今回の修正版）
# ==================================================
def run_all_races(target_races=None):
    """
    target_races = [3, 5, 7] のように渡すと、そのレースだけ実行。
    None（未指定）の場合は 1〜12R すべて実行。
    """

    # レース番号の決定
    if target_races is None:
        race_numbers = list(range(1, 13))
    else:
        race_numbers = sorted({int(r) for r in target_races})

    base_race_id = f"{YEAR}{KAI}{PLACE}{DAY}"

    place_names = {
        "00": "京都", "01": "阪神", "02": "中京", "03": "小倉",
        "04": "東京", "05": "中山", "06": "福島", "07": "新潟",
        "08": "札幌", "09": "函館",
    }
    place_name = place_names.get(PLACE, "不明")

    print(f"🔥 実行レース：{race_numbers}")

    # Selenium 設定
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    try:
        # ログイン
        driver.get("https://s.keibabook.co.jp/login/login")

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.NAME, "login_id"))
        ).send_keys(KEIBA_ID)

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
        ).send_keys(KEIBA_PASS)

        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "btn-login"))
            ).click()
        except:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit']"))
            ).click()

        time.sleep(2)

        # ★ターゲットレースのみ実行
        for i in race_numbers:
            race_num_str = f"{i:02}"
            current_race_id = base_race_id + race_num_str

            print(f"\n=== {i}R 開始 ===")

            # 1. 厩舎コメントページ
            url_danwa = f"https://s.keibabook.co.jp/cyuou/danwa/0/{current_race_id}"
            driver.get(url_danwa)
            time.sleep(1)

            if "login" in driver.current_url:
                print("⚠ ログイン切れ → このレースをスキップ")
                continue

            try:
                title_block = WebDriverWait(driver, 5).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.racetitle"))
                )
                race_title = title_block.text.strip()
            except:
                race_title = f"{place_name} {i}R"

            html_danwa = driver.page_source
            danwa_data = parse_danwa_comments(html_danwa)

            # 2. 前走インタビュー
            url_interview = f"https://s.keibabook.co.jp/cyuou/syoin/{current_race_id}"
            driver.get(url_interview)
            time.sleep(1)

            html_interview = driver.page_source
            zenkoso_list = parse_zenkoso_interview(html_interview)

            # 3. マージ
            merged_lines = []

            if not zenkoso_list:
                merged_lines.append("（データなし）")
            else:
                for horse in zenkoso_list:
                    umaban = horse["umaban"]
                    name = horse["name"]
                    danwa = danwa_data.get(umaban, "（厩舎コメントなし）")

                    if horse["prev_date_course"]:
                        prev_info = f"{horse['prev_date_course']} ({horse['prev_class']}) {horse['prev_finish']}"
                    else:
                        prev_info = "（前走情報なし）"

                    prev_comment = horse["prev_comment"] or "（前走談話なし）"

                    block = (
                        f"▼[枠{horse['waku']} 馬番{umaban}] {name}\n"
                        f"  【厩舎の話】 {danwa}\n"
                        f"  【前走情報】 {prev_info}\n"
                        f"  【前走談話】 {prev_comment}\n"
                    )
                    merged_lines.append(block)

            full_text = (
                f"あなたはプロの競馬予想AIです。以下の{place_name}{i}Rの全頭データを分析し、"
                f"推奨馬とその根拠、展開予想を行ってください。\n\n"
                f"■レース情報\n{race_title}\n\n"
                f"■出走馬詳細データ\n" +
                "\n".join(merged_lines)
            )

            # 4. Dify API 呼び出し
            payload = {
                "inputs": {"text": full_text},
                "response_mode": "blocking",
                "user": "keiba-bot-user",
            }

            headers = {
                "Authorization": f"Bearer {DIFY_API_KEY}",
                "Content-Type": "application/json",
            }

            res = requests.post("https://api.dify.ai/v1/workflows/run",
                                headers=headers, json=payload)

            if res.status_code == 200:
                data = res.json()
                ai_answer = (
                    data.get("data", {})
                        .get("outputs", {})
                        .get("answer", "")
                )

                st.markdown(f"### {place_name} {i}R")
                st.write(ai_answer)
                st.write("---")

                save_history(YEAR, KAI, PLACE, place_name, DAY,
                             race_num_str, current_race_id, ai_answer)
            else:
                print(f"❌ Dify エラー: {res.status_code} {res.text}")

    finally:
        print("\n🧹 ブラウザ終了")
        driver.quit()
