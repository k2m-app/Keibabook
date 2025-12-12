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

KEIBA_ID = st.secrets.get("KEIBA_ID", "")
KEIBA_PASS = st.secrets.get("KEIBA_PASS", "")
DIFY_API_KEY = st.secrets.get("DIFY_API_KEY", "")

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY", "")

YEAR = "2025"
KAI = "04"
PLACE = "02"
DAY = "02"


def set_race_params(year, kai, place, day):
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
        print("⚠ Supabase 未設定 → 保存しません")
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
        print("⚠ 履歴保存失敗:", e)


# ==================================================
# HTML パース（レース情報：距離・コース・馬場など）
# ==================================================
def parse_race_info(html: str):
    """
    厩舎の話ページの HTML からレース情報を抜き出す。
    例：
      2025年12月7日 5回中京2日目
      1R ２歳未勝利
      [指定],(混)
      1800m (ダート・左) 晴・良 平　　穏
    """
    soup = BeautifulSoup(html, "html.parser")
    racetitle = soup.find("div", class_="racetitle")
    if not racetitle:
        return {
            "date_meet": "",
            "race_name": "",
            "cond1": "",
            "course_line": "",
        }

    # 上段（開催日＋レース名）
    racemei = racetitle.find("div", class_="racemei")
    date_meet = ""
    race_name = ""
    if racemei:
        ps = racemei.find_all("p")
        if len(ps) >= 1:
            date_meet = ps[0].get_text(strip=True)
        if len(ps) >= 2:
            race_name = ps[1].get_text(strip=True)

    # 下段（[指定],(混) ／ 距離・コース・天候・馬場など）
    racetitle_sub = racetitle.find("div", class_="racetitle_sub")
    cond1 = ""
    course_line = ""
    if racetitle_sub:
        sub_ps = racetitle_sub.find_all("p")
        if len(sub_ps) >= 1:
            cond1 = sub_ps[0].get_text(strip=True)  # [指定],(混) など
        if len(sub_ps) >= 2:
            # "1800m (ダート・左) 晴・良 平　　穏" の行
            course_line = sub_ps[1].get_text(" ", strip=True)

    return {
        "date_meet": date_meet,
        "race_name": race_name,
        "cond1": cond1,
        "course_line": course_line,
    }


# ==================================================
# HTML パース（前走インタビュー）
# ==================================================
def parse_zenkoso_interview(html: str):
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.find("h2", string=lambda s: s and "前走のインタビュー" in s)
    if not h2:
        return []

    midasi = h2.find_parent("div", class_="midasi")
    table = midasi.find_next("table", class_="syoin")
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
        uma_td = row.find("td", class_="umaban")
        bamei_td = row.find("td", class_="bamei")
        if not (waku_td and uma_td and bamei_td):
            i += 1
            continue

        waku = waku_td.get_text(strip=True)
        umaban = uma_td.get_text(strip=True)
        name = bamei_td.get_text(strip=True)

        prev_date = ""
        prev_class = ""
        prev_finish = ""
        prev_comment = ""

        detail = rows[i + 1] if i + 1 < len(rows) else None
        if detail:
            syoin_td = detail.find("td", class_="syoin")
            if syoin_td:
                sdata = syoin_td.find("div", class_="syoindata")
                if sdata:
                    ps = sdata.find_all("p")
                    if ps:
                        prev_date = ps[0].get_text(strip=True)
                    if len(ps) >= 2:
                        spans = ps[1].find_all("span")
                        if len(spans) >= 1:
                            prev_class = spans[0].get_text(strip=True)
                        if len(spans) >= 2:
                            prev_finish = spans[1].get_text(strip=True)

                direct = syoin_td.find_all("p", recursive=False)
                if direct:
                    txt = direct[0].get_text(strip=True)
                    if txt != "－":
                        prev_comment = txt

        result.append({
            "waku": waku,
            "umaban": umaban,
            "name": name,
            "prev_date_course": prev_date,
            "prev_class": prev_class,
            "prev_finish": prev_finish,
            "prev_comment": prev_comment,
        })

        i += 2

    return result


# ==================================================
# HTML パース（厩舎の話）
# ==================================================
def parse_danwa_comments(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="danwa")
    if not table:
        return {}

    danwa_dict = {}
    current = None

    for row in table.tbody.find_all("tr"):
        uma_td = row.find("td", class_="umaban")
        if uma_td:
            current = uma_td.get_text(strip=True)
            continue

        danwa_td = row.find("td", class_="danwa")
        if danwa_td and current:
            danwa_dict[current] = danwa_td.get_text(strip=True)
            current = None

    return danwa_dict


# ==================================================
# ★ 調教ページ パース（完全版）
# ==================================================
def parse_cyokyo(html: str):
    """
    調教ページのHTMLから
    { "馬番": "整形済みテキスト" } のdictを返す
    """
    soup = BeautifulSoup(html, "html.parser")
    cyokyo_dict = {}

    # ① 「調教」セクションを特定
    section = None
    h2 = soup.find("h2", string=lambda s: s and "調教" in s)
    if h2:
        midasi_div = h2.find_parent("div", class_="midasi")
        if midasi_div:
            section = midasi_div.find_next_sibling("div", class_="section")

    if section is None:
        # 念のためフォールバック
        section = soup

    # ② section 内の table.cyokyo をすべて列挙
    tables = section.find_all("table", class_="cyokyo")
    print("★DEBUG table.cyokyo 個数:", len(tables))

    for tbl in tables:
        tbody = tbl.find("tbody")
        if not tbody:
            continue

        rows = tbody.find_all("tr", recursive=False)
        if not rows:
            continue

        # 1行目 = ヘッダ（枠番・馬番・馬名・短評・矢印）
        header = rows[0]
        uma_td = header.find("td", class_="umaban")
        name_td = header.find("td", class_="kbamei")

        # 馬番・馬名が取れないテーブルはスキップ
        if not uma_td or not name_td:
            continue

        umaban = uma_td.get_text(strip=True)
        bamei = name_td.get_text(" ", strip=True)

        tanpyo_td = header.find("td", class_="tanpyo")
        tanpyo = tanpyo_td.get_text(strip=True) if tanpyo_td else ""

        # 2行目 = 調教詳細（dl + table.cyokyodata 等）
        detail_row = rows[1] if len(rows) >= 2 else None
        detail_text = ""
        if detail_row:
            # 行内のテキストをすべて空白区切りで連結
            detail_text = detail_row.get_text(" ", strip=True)

        # 好きな形に整形
        final_text = f"【馬名】{bamei}（馬番{umaban}） 【短評】{tanpyo} 【調教詳細】{detail_text}"
        cyokyo_dict[umaban] = final_text

    print("★DEBUG 調教 dict keys:", list(cyokyo_dict.keys()))
    return cyokyo_dict


# ==================================================
# 調教取得関数
# ==================================================
BASE_URL = "https://s.keibabook.co.jp"


def fetch_cyokyo_dict(driver, race_id: str):
    url = f"{BASE_URL}/cyuou/cyokyo/0/{race_id}"
    print("★DEBUG 調教ページ URL:", url)
    driver.get(url)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.cyokyo"))
        )
    except Exception as e:
        print("❌ WebDriverWaitで table.cyokyo が見つからず:", e)
        print("current_url:", driver.current_url)
        src_head = driver.page_source[:2000]
        print("page_source 冒頭(2000文字):\n", src_head)
        return {}

    html = driver.page_source
    cy = parse_cyokyo(html)

    print("★DEBUG 調教:", cy)
    return cy


# ==================================================
# メイン処理
# ==================================================
def run_all_races(target_races=None):

    race_numbers = (
        list(range(1, 13))
        if target_races is None
        else sorted({int(r) for r in target_races})
    )

    base_id = f"{YEAR}{KAI}{PLACE}{DAY}"
    place_names = {
        "00": "京都", "01": "阪神", "02": "中京", "03": "小倉",
        "04": "東京", "05": "中山", "06": "福島", "07": "新潟",
        "08": "札幌", "09": "函館",
    }
    place_name = place_names.get(PLACE, "不明")

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

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit'], .btn-login"))
        ).click()

        time.sleep(2)

        # 各R処理
        for r in race_numbers:
            race_num = f"{r:02}"
            race_id = base_id + race_num

            print(f"\n=== {place_name} {r}R ({race_id}) ===")

            # 厩舎コメント（＋ここでレース情報も取る）
            url_danwa = f"https://s.keibabook.co.jp/cyuou/danwa/0/{race_id}"
            print("★DEBUG 厩舎コメント URL:", url_danwa)
            driver.get(url_danwa)
            time.sleep(1)

            html_danwa = driver.page_source
            race_info = parse_race_info(html_danwa)
            danwa_dict = parse_danwa_comments(html_danwa)
            print("★DEBUG 厩舎コメント dict keys:", list(danwa_dict.keys()))
            print("★DEBUG レース情報:", race_info)

            # 前走インタビュー
            url_inter = f"https://s.keibabook.co.jp/cyuou/syoin/{race_id}"
            print("★DEBUG 前走インタビュー URL:", url_inter)
            driver.get(url_inter)
            time.sleep(1)
            zenkoso = parse_zenkoso_interview(driver.page_source)
            print("★DEBUG 前走インタビュー頭数:", len(zenkoso))

            # 調教
            cyokyo_dict = fetch_cyokyo_dict(driver, race_id)

            # 馬ごとにマージ
            merged = []
            for h in zenkoso:
                uma = h["umaban"]
                text = (
                    f"▼[枠{h['waku']} 馬番{uma}] {h['name']}\n"
                    f"  【厩舎の話】 {danwa_dict.get(uma, '（厩舎コメントなし）')}\n"
                    f"  【前走情報】 {h['prev_date_course']} ({h['prev_class']}) {h['prev_finish']}\n"
                    f"  【前走談話】 {h['prev_comment'] or '（前走談話なし）'}\n"
                    f"  【調教】 {cyokyo_dict.get(uma, '（調教情報なし）')}\n"
                )
                merged.append(text)

            # レース情報テキスト整形
            race_header_lines = []
            if race_info["date_meet"]:
                race_header_lines.append(race_info["date_meet"])
            if race_info["race_name"]:
                race_header_lines.append(race_info["race_name"])
            if race_info["cond1"]:
                race_header_lines.append(race_info["cond1"])
            if race_info["course_line"]:
                # ここに「1800m (ダート・左) 晴・良 平　　穏」が入る
                race_header_lines.append(race_info["course_line"])

            race_header = "\n".join(race_header_lines)

            full_text = (
                f"■レース情報\n"
                f"{race_header}\n\n"
                f"以下は{place_name}{r}Rの全頭データである。"
                f"各馬について【厩舎の話】【前走情報・前走談話】【調教】を基に分析せよ。\n\n"
                f"■出走馬詳細データ\n" +
                "\n".join(merged)
            )

            payload = {
                "inputs": {"text": full_text},
                "response_mode": "blocking",
                "user": "keiba-bot-user",
            }

            headers = {
                "Authorization": f"Bearer {DIFY_API_KEY}",
                "Content-Type": "application/json",
            }

            res = requests.post(
                "https://api.dify.ai/v1/workflows/run",
                headers=headers,
                json=payload
            )

            if res.status_code == 200:
                ans = res.json().get("data", {}).get("outputs", {}).get("answer", "")
                st.markdown(f"### {place_name} {r}R")
                st.write(ans)
                st.write("---")

                save_history(YEAR, KAI, PLACE, place_name, DAY,
                             race_num, race_id, ans)

            else:
                print("❌ Dify エラー:", res.status_code, res.text)

    finally:
        print("\n🧹 ブラウザ終了")
        driver.quit()
