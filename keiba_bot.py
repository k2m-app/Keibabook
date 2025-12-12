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
from typing import Dict, List, Optional

# ==================================================
# 設定エリア
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

BASE_URL = "https://s.keibabook.co.jp"


def set_race_params(year, kai, place, day):
    """main.py から開催情報を差し替える用"""
    global YEAR, KAI, PLACE, DAY
    YEAR = str(year)
    KAI = str(kai).zfill(2)
    PLACE = str(place).zfill(2)
    DAY = str(day).zfill(2)


# ==================================================
# Supabase
# ==================================================
@st.cache_resource
def get_supabase_client() -> Optional[Client]:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def save_history(
    year: str,
    kai: str,
    place_code: str,
    place_name: str,
    day: str,
    race_num_str: str,
    race_id: str,
    ai_answer: str,
) -> None:
    """
    history テーブルに 1 レース分の予想を保存する。
    失敗してもアプリ全体は止めない。
    """
    supabase = get_supabase_client()
    if supabase is None:
        return  # Supabase 未設定なら何もしない

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
        # シンプルに insert だけする
        supabase.table("history").insert(data).execute()
    except Exception as e:
        # 画面には出さず、ログだけ残す
        print("Supabase insert error:", e)
        pass



# ==================================================
# Dify 呼び出し（ステータスに関わらず、中身を優先）
# ==================================================
def call_dify(full_text: str) -> Optional[Dict]:
    """
    Dify Workflow を叩いて JSON を返す。
    HTTPステータスはログに出すだけで、
    とにかく JSON が取れたらそれを返す。
    """
    payload = {
        "inputs": {"text": full_text},
        "response_mode": "blocking",
        "user": "keiba-bot-user",
    }
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error: Optional[Exception] = None

    for attempt in range(2):  # 最大2回トライ
        try:
            res = requests.post(
                "https://api.dify.ai/v1/workflows/run",
                headers=headers,
                json=payload,
                timeout=600,
            )
            print("Dify status:", res.status_code)  # ログ用（画面には出ない）

            try:
                result = res.json()
                return result
            except Exception as e:
                print("Dify JSON decode error:", e)
                last_error = e
                if attempt == 0:
                    time.sleep(3)
                    continue
        except Exception as e:
            print("Dify request error:", e)
            last_error = e
            if attempt == 0:
                time.sleep(3)
                continue

    print("Dify call failed finally:", last_error)
    return None


# ==================================================
# HTML パース（レース情報）
# ==================================================
def parse_race_info(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    racetitle = soup.find("div", class_="racetitle")
    if not racetitle:
        return {"date_meet": "", "race_name": "", "cond1": "", "course_line": ""}

    racemei = racetitle.find("div", class_="racemei")
    date_meet, race_name = "", ""
    if racemei:
        ps = racemei.find_all("p")
        if len(ps) >= 1:
            date_meet = ps[0].get_text(strip=True)
        if len(ps) >= 2:
            race_name = ps[1].get_text(strip=True)

    racetitle_sub = racetitle.find("div", class_="racetitle_sub")
    cond1, course_line = "", ""
    if racetitle_sub:
        sub_ps = racetitle_sub.find_all("p")
        if len(sub_ps) >= 1:
            cond1 = sub_ps[0].get_text(strip=True)
        if len(sub_ps) >= 2:
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
def parse_zenkoso_interview(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.find("h2", string=lambda s: s and "前走のインタビュー" in s)
    if not h2:
        return []

    midasi = h2.find_parent("div", class_="midasi")
    table = midasi.find_next("table", class_="syoin") if midasi else None
    if not table or not table.tbody:
        return []

    rows = table.tbody.find_all("tr")
    result: List[Dict[str, str]] = []
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

        result.append(
            {
                "waku": waku,
                "umaban": umaban,
                "name": name,
                "prev_date_course": prev_date,
                "prev_class": prev_class,
                "prev_finish": prev_finish,
                "prev_comment": prev_comment,
            }
        )
        i += 2

    return result


# ==================================================
# HTML パース（厩舎の話）
# ==================================================
def parse_danwa_comments(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="danwa")
    if not table or not table.tbody:
        return {}

    danwa_dict: Dict[str, str] = {}
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
# HTML パース（調教）
# ==================================================
def parse_cyokyo(html: str) -> Dict[str, str]:
    """調教ページのHTMLから {馬番: 調教テキスト} の dict を返す"""
    soup = BeautifulSoup(html, "html.parser")
    cyokyo_dict: Dict[str, str] = {}

    section = None
    h2 = soup.find("h2", string=lambda s: s and "調教" in s)
    if h2:
        midasi_div = h2.find_parent("div", class_="midasi")
        if midasi_div:
            section = midasi_div.find_next_sibling("div", class_="section")
    if section is None:
        section = soup

    tables = section.find_all("table", class_="cyokyo")

    for tbl in tables:
        tbody = tbl.find("tbody")
        if not tbody:
            continue

        rows = tbody.find_all("tr", recursive=False)
        if not rows:
            continue

        header = rows[0]
        uma_td = header.find("td", class_="umaban")
        name_td = header.find("td", class_="kbamei")

        if not uma_td or not name_td:
            continue

        umaban = uma_td.get_text(strip=True)
        bamei = name_td.get_text(" ", strip=True)

        tanpyo_td = header.find("td", class_="tanpyo")
        tanpyo = tanpyo_td.get_text(strip=True) if tanpyo_td else ""

        detail_row = rows[1] if len(rows) >= 2 else None
        detail_text = detail_row.get_text(" ", strip=True) if detail_row else ""

        final_text = (
            f"【馬名】{bamei}（馬番{umaban}） "
            f"【短評】{tanpyo} "
            f"【調教詳細】{detail_text}"
        )
        cyokyo_dict[umaban] = final_text

    return cyokyo_dict


def fetch_cyokyo_dict(driver: webdriver.Chrome, race_id: str) -> Dict[str, str]:
    url = f"{BASE_URL}/cyuou/cyokyo/0/{race_id}"
    driver.get(url)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.cyokyo"))
        )
    except Exception:
        return {}

    return parse_cyokyo(driver.page_source)

def shrink_horse_blocks(
    blocks,
    per_horse_limit=450,   # 1頭あたり最大文字数（18頭でも安全）
    total_limit=13000      # 全体の最大文字数（Dify が安定して処理可能）
):
    """
    blocks: 馬ごとのテキストリスト（merged）
    各馬の文章を短くしつつ、全体の文字数も安全範囲に収める
    """
    shrunk = []

    # まず各馬を適切な長さに切る
    for b in blocks:
        if len(b) > per_horse_limit:
            b = b[:per_horse_limit] + "\n（※この馬のコメントは長いため一部省略）\n"
        shrunk.append(b)

    # 一旦結合
    combined = "\n".join(shrunk)

    # 全体が大きすぎる場合さらにカット
    if len(combined) > total_limit:
        combined = combined[:total_limit] + "\n（※データ量の都合で一部省略しています）\n"

    return combined

# ==================================================
# メイン処理
# ==================================================
def run_all_races(target_races=None):
    """
    target_races: [10, 11, 12] のような int リスト。
    None の場合は 1〜12R すべて実行。
    """
    race_numbers = (
        list(range(1, 13))
        if target_races is None
        else sorted({int(r) for r in target_races})
    )

    base_id = f"{YEAR}{KAI}{PLACE}{DAY}"
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
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, "input[type='password']")
            )
        ).send_keys(KEIBA_PASS)

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[type='submit'], .btn-login")
            )
        ).click()

        time.sleep(2)

        # 各レース処理
        for r in race_numbers:
            race_num = f"{r:02}"
            race_id = base_id + race_num

            try:
                # 1) 厩舎コメント & レース情報
                url_danwa = f"https://s.keibabook.co.jp/cyuou/danwa/0/{race_id}"
                driver.get(url_danwa)
                time.sleep(1)

                html_danwa = driver.page_source
                race_info = parse_race_info(html_danwa)
                danwa_dict = parse_danwa_comments(html_danwa)

                # 2) 前走インタビュー
                url_inter = f"https://s.keibabook.co.jp/cyuou/syoin/{race_id}"
                driver.get(url_inter)
                time.sleep(1)
                zenkoso = parse_zenkoso_interview(driver.page_source)

                # 3) 調教
                cyokyo_dict = fetch_cyokyo_dict(driver, race_id)

     # 4) 馬ごとにマージ（1頭ずつテキスト化）
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

# 4.5) テキスト圧縮（メインレース対策 / 18頭前提）
merged_text = shrink_horse_blocks(
    merged,
    per_horse_limit=450,   # ← 18頭でも約8100文字
    total_limit=13000      # ← 全体で安全範囲
)

# 5) レース情報を整形
race_header_lines = []
if race_info["date_meet"]:
    race_header_lines.append(race_info["date_meet"])
if race_info["race_name"]:
    race_header_lines.append(race_info["race_name"])
if race_info["cond1"]:
    race_header_lines.append(race_info["cond1"])
if race_info["course_line"]:
    race_header_lines.append(race_info["course_line"])

race_header = "\n".join(race_header_lines)

# 6) 最終テキストとして結合（ここは長くならない）
full_text = (
    "■レース情報\n"
    f"{race_header}\n\n"
    f"以下は{place_name}{r}Rの全頭データである。\n"
    "各馬について【厩舎の話】【前走情報・前走談話】【調教】を基に分析せよ。\n\n"
    "■出走馬詳細データ\n"
    + merged_text
)


                # 6) Dify Workflow 呼び出し
                result = call_dify(full_text)
                if result is None:
                    st.error(f"{place_name} {r}R: Dify API エラー")
                    continue

                data = result.get("data", {})
                outputs = data.get("outputs", {})
                ans = ""

                if isinstance(outputs, dict):
                    ans = outputs.get("answer", "")
                elif isinstance(outputs, list):
                    for o in outputs:
                        if o.get("output") == "answer" and o.get("type") == "text":
                            ans = o.get("value", "")
                            break

                if not ans:
                    st.error(f"{place_name} {r}R: 予想結果を取得できませんでした。")
                    continue

                # 7) 画面表示
                st.markdown(f"### {place_name} {r}R")
                st.write(ans)
                st.write("---")

                # 8) Supabase に履歴保存（失敗してもスルー）
                save_history(
                    YEAR,
                    KAI,
                    PLACE,
                    place_name,
                    DAY,
                    race_num,
                    race_id,
                    ans,
                )

            except Exception:
                # 詳細は出さず、このレースだけスキップ
                st.error(f"{place_name} {r}R の処理中にエラーが発生しました。")

    finally:
        driver.quit()


