import time
import json
import re
import math
import requests
import streamlit as st
import streamlit.components.v1 as components
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ==================================================
# 【設定エリア】secretsから読み込み
# ==================================================
KEIBA_ID = st.secrets.get("KEIBA_ID", "")
KEIBA_PASS = st.secrets.get("KEIBA_PASS", "")
DIFY_API_KEY = st.secrets.get("DIFY_API_KEY", "")

# デフォルト設定
YEAR = "2026"
KAI = "01"
PLACE = "06" # 中山
DAY = "05"

BASE_URL = "https://s.keibabook.co.jp"

# Keibabookの場所コード
KB_PLACE_NAMES = {
    "00": "京都", "01": "阪神", "02": "中京", "03": "小倉", "04": "東京",
    "05": "中山", "06": "福島", "07": "新潟", "08": "札幌", "09": "函館",
}

# Keibabook -> Netkeiba 場所コード変換マップ
# KB: 00京都, 01阪神, 02中京, 03小倉, 04東京, 05中山, 06福島, 07新潟, 08札幌, 09函館
# NK: 01札幌, 02函館, 03福島, 04新潟, 05東京, 06中山, 07中京, 08京都, 09阪神, 10小倉
KB_TO_NK_PLACE = {
    "00": "08", "01": "09", "02": "07", "03": "10", "04": "05",
    "05": "06", "06": "03", "07": "04", "08": "01", "09": "02"
}

def set_race_params(year, kai, place, day):
    global YEAR, KAI, PLACE, DAY
    YEAR = str(year)
    KAI = str(kai).zfill(2)
    PLACE = str(place).zfill(2)
    DAY = str(day).zfill(2)

def get_current_params():
    return YEAR, KAI, PLACE, DAY

# ==================================================
# ワンクリックコピー
# ==================================================
def render_copy_button(text: str, label: str, dom_id: str):
    safe_text = json.dumps(text)
    html = f"""
    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <button id="{dom_id}" style="
        padding:8px 12px;
        border-radius:10px;
        border:1px solid #ddd;
        background:#fff;
        cursor:pointer;
        font-size:14px;
      ">{label}</button>
      <span id="{dom_id}-msg" style="font-size:12px; color:#666;"></span>
    </div>
    <script>
      (function() {{
        const btn = document.getElementById("{dom_id}");
        const msg = document.getElementById("{dom_id}-msg");
        if (!btn) return;
        btn.addEventListener("click", async () => {{
          try {{
            await navigator.clipboard.writeText({safe_text});
            msg.textContent = "コピーしました";
            setTimeout(() => msg.textContent = "", 1200);
          }} catch (e) {{
            msg.textContent = "コピーに失敗";
            setTimeout(() => msg.textContent = "", 2200);
          }}
        }});
      }})();
    </script>
    """
    components.html(html, height=54)


# ==================================================
# Selenium
# ==================================================
def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,2200")
    # User-Agent設定（Netkeiba対策）
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver

def login_keibabook(driver: webdriver.Chrome) -> None:
    if not KEIBA_ID or not KEIBA_PASS:
        raise RuntimeError("KEIBA_ID / KEIBA_PASS が未設定")
    driver.get(f"{BASE_URL}/login/login")
    WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.NAME, "login_id"))).send_keys(KEIBA_ID)
    WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))).send_keys(KEIBA_PASS)
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit'], .btn-login"))).click()
    time.sleep(1.2)

# ==================================================
# Keibabook Parser
# ==================================================
def parse_race_info(html: str):
    soup = BeautifulSoup(html, "html.parser")
    racetitle = soup.find("div", class_="racetitle")
    if not racetitle:
        return {"date_meet": "", "race_name": "", "cond1": "", "course_line": ""}
    racemei = racetitle.find("div", class_="racemei")
    date_meet, race_name = "", ""
    if racemei:
        ps = racemei.find_all("p")
        if len(ps) >= 1: date_meet = ps[0].get_text(strip=True)
        if len(ps) >= 2: race_name = ps[1].get_text(strip=True)
    racetitle_sub = racetitle.find("div", class_="racetitle_sub")
    cond1, course_line = "", ""
    if racetitle_sub:
        sub_ps = racetitle_sub.find_all("p")
        if len(sub_ps) >= 1: cond1 = sub_ps[0].get_text(strip=True)
        if len(sub_ps) >= 2: course_line = sub_ps[1].get_text(" ", strip=True)
    return {"date_meet": date_meet, "race_name": race_name, "cond1": cond1, "course_line": course_line}

def parse_danwa_comments(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="danwa")
    if not table or not table.tbody: return {}
    danwa_dict, current_key = {}, None
    for row in table.tbody.find_all("tr"):
        uma_td = row.find("td", class_="umaban")
        bamei_td = row.find("td", class_="bamei")
        if uma_td:
            text = re.sub(r"\D", "", uma_td.get_text(strip=True))
            if text: current_key = text; continue
        if bamei_td and not current_key:
            text = bamei_td.get_text(strip=True)
            if text: current_key = text; continue
        danwa_td = row.find("td", class_="danwa")
        if danwa_td and current_key:
            danwa_dict[current_key] = danwa_td.get_text(strip=True)
            current_key = None
    return danwa_dict

def parse_zenkoso_interview(html: str):
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.find("h2", string=lambda s: s and "前走" in s)
    if not h2: return {}
    table = h2.find_next("table", class_="syoin")
    if not table or not table.tbody: return {}
    rows = table.tbody.find_all("tr")
    result_dict, i = {}, 0
    while i < len(rows):
        row = rows[i]
        if "spacer" in (row.get("class") or []): i += 1; continue
        uma_td = row.find("td", class_="umaban")
        bamei_td = row.find("td", class_="bamei")
        if not (uma_td and bamei_td): i += 1; continue
        umaban = re.sub(r"\D", "", uma_td.get_text(strip=True))
        name = bamei_td.get_text(strip=True)
        prev_comment = ""
        detail = rows[i + 1] if i + 1 < len(rows) else None
        if detail:
            syoin_td = detail.find("td", class_="syoin")
            if syoin_td:
                direct = syoin_td.find_all("p", recursive=False)
                if direct:
                    txt = direct[0].get_text(strip=True)
                    if txt != "－": prev_comment = txt
        if umaban: result_dict[umaban] = {"name": name, "prev_comment": prev_comment}
        i += 2
    return result_dict

def parse_cyokyo(html: str):
    soup = BeautifulSoup(html, "html.parser")
    cyokyo_dict = {}
    section = None
    h2 = soup.find("h2", string=lambda s: s and ("調教" in s or "中間" in s))
    if h2:
        midasi = h2.find_parent("div", class_="midasi")
        if midasi: section = midasi.find_next_sibling("div", class_="section")
    if section is None: section = soup
    tables = section.find_all("table", class_="cyokyo")
    for tbl in tables:
        tbody = tbl.find("tbody")
        if not tbody: continue
        rows = tbody.find_all("tr", recursive=False)
        if len(rows) < 1: continue
        header = rows[0]
        uma_td = header.find("td", class_="umaban")
        name_td = header.find("td", class_="kbamei")
        umaban = re.sub(r"\D", "", uma_td.get_text(strip=True)) if uma_td else ""
        bamei_hint = name_td.get_text(" ", strip=True) if name_td else ""
        tanpyo_td = header.find("td", class_="tanpyo")
        tanpyo = tanpyo_td.get_text(strip=True) if tanpyo_td else ""
        detail_row = rows[1] if len(rows) >= 2 else None
        detail_text = detail_row.get_text(" ", strip=True) if detail_row else ""
        payload = {"tanpyo": tanpyo, "detail": detail_text, "bamei_hint": bamei_hint}
        if umaban: cyokyo_dict[umaban] = payload
        elif bamei_hint: cyokyo_dict[bamei_hint] = payload
    return cyokyo_dict

def parse_syutuba(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_=lambda c: c and "syutuba" in c)
    if not table or not table.tbody: return {}
    result = {}
    for tr in table.tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if not tds: continue
        umaban = re.sub(r"\D", "", tds[0].get_text(strip=True))
        if not umaban: continue
        bamei = ""
        kbamei_p = tr.find("p", class_="kbamei")
        if kbamei_p: bamei = kbamei_p.get_text(" ", strip=True)
        kisyu = ""
        kisyu_p = tr.find("p", class_="kisyu")
        if kisyu_p: kisyu = kisyu_p.get_text(strip=True)
        result[umaban] = {"umaban": umaban, "bamei": bamei, "kisyu": kisyu}
    return result

# ==================================================
# Netkeiba Scraper & 近走指数
# ==================================================
def fetch_netkeiba_data(driver, nk_race_id):
    """Netkeibaの出馬表(過去走)ページから近走データを取得"""
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={nk_race_id}&rf=shutuba_submenu"
    driver.get(url)
    time.sleep(1.0)
    
    soup = BeautifulSoup(driver.page_source, "html.parser")
    data_dict = {} # key: 馬名 (Netkeibaは馬番が変わる可能性があるため馬名マッチング推奨だが、今回は暫定で馬名)
    
    # 馬リストの取得
    rows = soup.select("tr.HorseList")
    for row in rows:
        # 馬名取得
        name_el = row.select_one(".HorseName a")
        if not name_el: continue
        horse_name = name_el.get_text(strip=True)
        
        # 過去走データの取得 (最大5走分)
        past_runs_html = row.select("td.Past")
        past_runs_data = []
        
        for run_td in past_runs_html:
            # 開催日、レース名、着順、通過順などを取得
            data01 = run_td.select_one(".Data01")
            data02 = run_td.select_one(".Data02")
            data05 = run_td.select_one(".Data05") # 通過順はここにあることが多い
            
            if not (data01 and data02): continue
            
            # 日付・場所
            date_text = data01.get_text(" ", strip=True)
            # レース情報（頭数、枠、人気など）
            race_meta = data02.get_text(" ", strip=True)
            
            # 通過順と着順の抽出
            passing_str = ""
            rank_str = ""
            
            # Data05から通過順を探す (例: 10-10-7)
            if data05:
                passing_raw = data05.get_text(strip=True)
                # 7-11-13-13 のような形式を抽出
                match_pass = re.search(r'(\d+(?:-\d+)+)', passing_raw)
                if match_pass:
                    passing_str = match_pass.group(1)
            
            # 着順はData01の中にあることが多いが、構造が複雑なためData01の最初の数字やクラスを確認
            # Netkeibaのこのページは着順が明示的なクラス(Rank)で書かれている
            rank_el = run_td.select_one(".Rank")
            if rank_el:
                rank_str = rank_el.get_text(strip=True)
            
            if passing_str and rank_str:
                # 整形: [2025.12.20 ... (7-11-13-13→6着)]
                # 詳細なテキストは簡易化して結合
                full_text = f"[{date_text} {race_meta} ({passing_str}→{rank_str}着)]"
                past_runs_data.append({
                    "full_text": full_text,
                    "passing": passing_str,
                    "rank": rank_str
                })
                
        data_dict[horse_name] = past_runs_data
        
    return data_dict

def calculate_kinsou_index(past_runs_data):
    """
    近走指数を計算する
    ①近3走のどれかで「道中順位が4つ以上悪化」かつ「最終着順が最悪位置より2つ以上巻き返し」 -> +8
    ②近3走のどれかで「道中順位が2つ以上悪化」かつ「最終着順が最悪位置より2つ以上巻き返し」 -> +5
    ③近3走のうち50%以上で「4コーナーの順位が4番手以内」 -> +2
    MAX 10点
    """
    # 近3走に絞る
    recent_3 = past_runs_data[:3]
    if not recent_3:
        return 0.0
    
    base_score = 0
    corner4_ok_count = 0
    valid_runs = 0
    
    for run in recent_3:
        try:
            p_str = run["passing"]
            r_str = run["rank"]
            
            # 通過順リスト化 [7, 11, 13, 13]
            passes = [int(x) for x in p_str.split("-")]
            finish = int(re.sub(r"\D", "", r_str))
            
            valid_runs += 1
            
            # Rule 3 Check (4コーナー <= 4)
            # 配列の最後が4コーナーと仮定
            if passes[-1] <= 4:
                corner4_ok_count += 1
            
            # Rule 1 & 2 Check
            # 「道中順位が悪化」: 始点(または最小値)と最悪値(最大値)の差と定義
            # ユーザー例: 7-11-13-13 (7->13で6悪化)
            start_pos = passes[0]
            worst_pos = max(passes)
            worsened = worst_pos - start_pos
            
            # 「巻き返し」: 最悪値 - 着順
            recovery = worst_pos - finish
            
            # 判定 (点数の高い方を優先)
            if worsened >= 4 and recovery >= 2:
                base_score = max(base_score, 8)
            elif worsened >= 2 and recovery >= 2:
                base_score = max(base_score, 5)
                
        except Exception:
            continue
            
    # Rule 3 Bonus
    bonus = 0
    if valid_runs > 0 and (corner4_ok_count / valid_runs) >= 0.5:
        bonus = 2
        
    total = base_score + bonus
    return min(float(total), 10.0)

# ==================================================
# Keibabook Fetch functions
# ==================================================
def fetch_danwa_dict(driver, race_id):
    driver.get(f"{BASE_URL}/cyuou/danwa/0/{race_id}")
    time.sleep(0.8)
    html = driver.page_source
    return html, parse_race_info(html), parse_danwa_comments(html)

def fetch_zenkoso_dict(driver, race_id):
    driver.get(f"{BASE_URL}/cyuou/syoin/{race_id}")
    time.sleep(0.8)
    return parse_zenkoso_interview(driver.page_source)

def fetch_cyokyo_dict(driver, race_id):
    driver.get(f"{BASE_URL}/cyuou/cyokyo/0/{race_id}")
    time.sleep(0.5)
    return parse_cyokyo(driver.page_source)

def fetch_syutuba_dict(driver, race_id):
    driver.get(f"{BASE_URL}/cyuou/syutuba/{race_id}")
    time.sleep(0.5)
    return parse_syutuba(driver.page_source)

# ==================================================
# Dify Streaming
# ==================================================
def stream_dify_workflow(full_text: str):
    if not DIFY_API_KEY:
        yield "⚠️ エラー: DIFY_API_KEY が未設定"
        return
    payload = {"inputs": {"text": full_text}, "response_mode": "streaming", "user": "keiba-bot-user"}
    headers = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
    try:
        res = requests.post("https://api.dify.ai/v1/workflows/run", headers=headers, json=payload, stream=True, timeout=300)
        if res.status_code != 200:
            yield f"⚠️ エラー: {res.status_code}\n{res.text}"
            return
        for line in res.iter_lines():
            if not line: continue
            decoded = line.decode("utf-8", errors="ignore")
            if not decoded.startswith("data:"): continue
            json_str = decoded.replace("data: ", "")
            try:
                data = json.loads(json_str)
            except: continue
            if data.get("event") == "workflow_finished":
                outputs = data.get("data", {}).get("outputs", {})
                txt = "".join([v for v in outputs.values() if isinstance(v, str)])
                if txt: yield txt
            chunk = data.get("answer", "")
            if chunk: yield chunk
    except Exception as e:
        yield f"⚠️ Request Error: {str(e)}"

# ==================================================
# メイン処理
# ==================================================
def run_all_races(target_races=None):
    race_numbers = list(range(1, 13)) if target_races is None else sorted({int(r) for r in target_races})
    base_id = f"{YEAR}{KAI}{PLACE}{DAY}"
    place_name = KB_PLACE_NAMES.get(PLACE, "不明")
    
    # Netkeiba IDの構築
    # KB: YYYY(4) KAI(2) PLACE(2) DAY(2) RR(2)
    # NK: YYYY(4) PLACE(2) KAI(2) DAY(2) RR(2)
    nk_place = KB_TO_NK_PLACE.get(PLACE, "06") # Default 中山
    nk_base_id = f"{YEAR}{nk_place}{KAI}{DAY}"
    
    combined_blocks = []
    driver = build_driver()

    try:
        st.info("🔑 ログイン中...")
        login_keibabook(driver)
        st.success("✅ ログイン完了")

        for r in race_numbers:
            race_num = f"{r:02}"
            race_id = base_id + race_num
            nk_race_id = nk_base_id + race_num
            
            st.markdown(f"### {place_name} {r}R")
            status_area = st.empty()
            result_area = st.empty()
            full_answer = ""

            try:
                status_area.info(f"📡 {place_name}{r}R データ収集中 (KB & Netkeiba)...")
                
                # 1. Keibabook Data
                _html, race_info, danwa_dict = fetch_danwa_dict(driver, race_id)
                zenkoso_dict = fetch_zenkoso_dict(driver, race_id)
                cyokyo_dict = fetch_cyokyo_dict(driver, race_id)
                syutuba_dict = fetch_syutuba_dict(driver, race_id)
                
                # 2. Netkeiba Data (近走)
                nk_data = fetch_netkeiba_data(driver, nk_race_id)

                merged = []
                umaban_list = sorted(syutuba_dict.keys(), key=lambda x: int(x)) if syutuba_dict else []

                for umaban in umaban_list:
                    sb = syutuba_dict.get(umaban, {})
                    bamei = (sb.get("bamei") or "").strip()
                    kisyu = sb.get("kisyu", "不明")
                    
                    # 厩舎
                    d_cmt = danwa_dict.get(umaban) or danwa_dict.get(bamei) or "（情報なし）"
                    
                    # Netkeiba 近走データ & 指数計算
                    nk_horse_data = nk_data.get(bamei, [])
                    kinsou_score = calculate_kinsou_index(nk_horse_data)
                    
                    # 近走文字列の作成
                    kinsou_text_list = [d["full_text"] for d in nk_horse_data]
                    kinsou_block_str = " / ".join(kinsou_text_list) if kinsou_text_list else "（情報なし）"

                    # 前走（Keibabookのインタビュー）
                    z_data = zenkoso_dict.get(umaban) or zenkoso_dict.get(bamei) or {}
                    z_comment = z_data.get("prev_comment", "（無し）")

                    # 調教
                    c = cyokyo_dict.get(umaban) or cyokyo_dict.get(bamei) or {}
                    c_str = f"短評:{c.get('tanpyo','')} / 詳細:{c.get('detail','')}"

                    # フォーマット構築
                    # スピード指数などは現状計算元がないためプレースホルダーまたはDify側推論に任せる前提で枠のみ作成
                    # 近走指数のみPythonで計算した値を埋め込む
                    text = (
                        f"▼{syutuba_dict.get(umaban,{}).get('waku','?')}枠{umaban}番 {bamei} (騎手:{kisyu})\n"
                        f"【データ】スピード指数:-- (偏差値:--) バイアス:-- 近走指数:{kinsou_score:.1f}/10 F:--\n"
                        f"【厩舎】{d_cmt}\n"
                        f"【前走談話】{z_comment}\n"
                        f"【調教】{c_str}\n"
                        f"【近走】{kinsou_block_str}\n"
                    )
                    merged.append(text)

                # Output Generation
                header_txt = "\n".join([v for v in race_info.values() if v])
                full_text = (
                    "■レース情報\n" + header_txt + "\n\n"
                    f"以下は{place_name}{r}Rの全頭データ。\n"
                    "■出走馬詳細データ\n" + "\n".join(merged)
                )

                status_area.info("🤖 AI分析中...")
                for chunk in stream_dify_workflow(full_text):
                    if chunk:
                        full_answer += chunk
                        result_area.markdown(full_answer + "▌")
                
                result_area.markdown(full_answer)
                if full_answer:
                    status_area.success("✅ 完了")
                    save_history(YEAR, KAI, PLACE, place_name, DAY, race_num, race_id, full_answer)
                    combined_blocks.append(f"【{place_name} {r}R】\n{full_answer.strip()}\n")
                    
                    # Copy Button
                    dom_id = f"copy_{race_id}_{int(time.time())}"
                    render_copy_button(full_answer.strip(), f"📋 {r}R コピー", dom_id)

            except Exception as e:
                st.error(f"Error {r}R: {e}")

        # Summary
        if combined_blocks:
            final_txt = "\n".join(combined_blocks)
            st.subheader("📌 全レースまとめ")
            render_copy_button(final_txt, "📋 全文コピー", "copy_all_final")
            st.download_button("⬇️ TXT保存", final_txt, file_name=f"KEIBA_{place_name}_ALL.txt")

    finally:
        driver.quit()

# ==================================================
# UI Entry Point
# ==================================================
st.title("🏇 AI競馬予想 (KB×Netkeiba 近走指数版)")

with st.sidebar:
    st.header("開催設定")
    y = st.text_input("年", YEAR)
    k = st.text_input("回", KAI)
    p = st.selectbox("場所", list(KB_PLACE_NAMES.keys()), index=5, format_func=lambda x: KB_PLACE_NAMES[x])
    d = st.text_input("日", DAY)
    
    if st.button("設定反映"):
        set_race_params(y, k, p, d)
        st.success(f"設定: {y}年 {k}回 {KB_PLACE_NAMES[p]} {d}日目")

    st.markdown("---")
    st.markdown("### 対象レース実行")
    if st.button("全レース (1-12R)"):
        run_all_races()
    
    st.markdown("---")
    r_single = st.number_input("単一レース実行", 1, 12, 11)
    if st.button(f"{r_single}R のみ実行"):
        run_all_races([r_single])
