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

# 4. 開催情報（デフォルト値）
# 必要に応じて set_race_params で書き換えてください
YEAR = "2025"
KAI = "04"
PLACE = "02" # 02:中京
DAY = "02"   # 2日目 (例として変更)


# ==================================================
# データベース関連関数 (Supabase)
# ==================================================
@st.cache_resource
def get_supabase_client() -> Client:
    """Supabase クライアントを1回だけ作って使い回す"""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def save_history(year, kai, place_code, place_name, day, race_num_str, race_id, ai_answer):
    """1レース分のAI出力を Supabase の history テーブルに保存する"""
    supabase = get_supabase_client()
    if supabase is None:
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


# ==================================================
# スクレイピング・パース関連関数
# ==================================================

def parse_zenkoso_interview(html: str):
    """
    前走インタビューページのHTMLからリストを生成する
    """
    soup = BeautifulSoup(html, "html.parser")
    # タイトル周辺からテーブルを探す
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

        # 次の行が詳細情報
        detail_row = rows[i + 1] if i + 1 < len(rows) else None
        prev_date_course = ""
        prev_class = ""
        prev_finish = ""
        prev_comment = ""

        if detail_row:
            syoin_td = detail_row.find("td", class_="syoin")
            if syoin_td:
                # 前走の日付＋コースなど
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

                # コメント
                direct_ps = syoin_td.find_all("p", recursive=False)
                if direct_ps:
                    comment_text = direct_ps[0].get_text(strip=True)
                    if comment_text != "－":
                        prev_comment = comment_text.lstrip("　 ").rstrip()

        result.append({
            "waku": waku,
            "umaban": umaban,
            "name": name,
            "prev_date_course": prev_date_course,
            "prev_class": prev_class,
            "prev_finish": prev_finish,
            "prev_comment": prev_comment,
        })
        
        # 次の馬へ進める（馬情報の行 + 詳細行 + spacer行があるかも）
        i += 2
        if i < len(rows) and "spacer" in (rows[i].get("class") or []):
            i += 1

    return result


def parse_danwa_comments(html: str):
    """
    【新規追加】厩舎の話ページから馬ごとのコメントを辞書形式で抽出する
    Key: 馬番(str), Value: コメント(str)
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="danwa")
    if not table:
        return {}

    danwa_dict = {}
    rows = table.tbody.find_all("tr")
    
    current_umaban = None
    
    for row in rows:
        # 1. 馬番・馬名の行を探す
        umaban_td = row.find("td", class_="umaban")
        if umaban_td:
            current_umaban = umaban_td.get_text(strip=True)
            continue
            
        # 2. コメントの行を探す（馬番行の直後に来る）
        danwa_td = row.find("td", class_="danwa")
        if danwa_td and current_umaban:
            comment = danwa_td.get_text(strip=True)
            danwa_dict[current_umaban] = comment
            current_umaban = None # 次のためにリセット

    return danwa_dict


# ==================================================
# メイン処理
# ==================================================
def run_all_races():
    base_race_id = f"{YEAR}{KAI}{PLACE}{DAY}"
    place_names = {
        "00": "京都", "01": "阪神", "02": "中京", "03": "小倉",
        "04": "東京", "05": "中山", "06": "福島", "07": "新潟",
        "08": "札幌", "09": "函館",
    }
    place_name = place_names.get(PLACE, "不明な競馬場")

    print(f"🚀 {YEAR}年{KAI}回 {place_name} {DAY}日目の全レース攻略を開始します！")

    # ▼▼ クラウド用設定（ヘッドレスモード） ▼▼
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    try:
        # --- ログイン処理 ---
        print("🌍 競馬ブックにログイン画面へ移動中...")
        driver.get("https://s.keibabook.co.jp/login/login")

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.NAME, "login_id"))
        ).send_keys(KEIBA_ID)
        time.sleep(0.5)

        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
        ).send_keys(KEIBA_PASS)
        time.sleep(0.5)

        try:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "btn-login"))
            ).click()
        except:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit']"))
            ).click()

        print("✨ ログイン処理完了")
        time.sleep(3)

        # --- 1Rから12Rまでループ処理 ---
        for i in range(1, 13):
            race_num_str = f"{i:02}"
            current_race_id = base_race_id + race_num_str

            print("\n" + "=" * 40)
            print(f"🐎 {place_name} {i}R (ID:{current_race_id}) の情報を収集中...")

            try:
                url_danwa = f"https://s.keibabook.co.jp/cyuou/danwa/0/{current_race_id}"
                url_interview = f"https://s.keibabook.co.jp/cyuou/syoin/{current_race_id}"

                # -------------------------------------------------------
                # 1. 厩舎の話ページ取得・パース
                # -------------------------------------------------------
                driver.get(url_danwa)
                time.sleep(1)

                if "login" in driver.current_url:
                    print("⚠️ ログインが外れている可能性があります！スキップします。")
                    continue

                # レース名取得
                try:
                    race_title_block = WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div.racetitle"))
                    )
                    race_title_text = race_title_block.text.strip()
                except:
                    race_title_text = f"{place_name} {i}R"

                # HTMLから厩舎コメントを辞書化
                html_danwa = driver.page_source
                danwa_data = parse_danwa_comments(html_danwa)

                # -------------------------------------------------------
                # 2. 前走インタビューページ取得・パース
                # -------------------------------------------------------
                driver.get(url_interview)
                time.sleep(1)
                
                html_interview = driver.page_source
                zenkoso_list = parse_zenkoso_interview(html_interview)

                # -------------------------------------------------------
                # 3. データを「馬ごと」にマージして構造化テキスト作成
                # -------------------------------------------------------
                merged_lines = []
                
                if not zenkoso_list:
                    # 前走情報が取れなかった場合（新馬戦など）のガード
                    merged_lines.append("（出走馬データの取得に失敗したか、データが存在しません）")
                else:
                    for horse in zenkoso_list:
                        umaban = horse['umaban']
                        name = horse['name']
                        
                        # 厩舎コメントを辞書から引く（なければ「なし」）
                        danwa_comment = danwa_data.get(umaban, "（厩舎コメントなし）")
                        
                        # 前走情報の整形
                        if horse['prev_date_course']:
                            prev_info = f"{horse['prev_date_course']} ({horse['prev_class']}) {horse['prev_finish']}"
                        else:
                            prev_info = "（前走情報なし）"
                            
                        prev_comment = horse['prev_comment'] or "（前走コメントなし）"

                        # 1頭分のブロックを作成
                        block = (
                            f"▼[枠{horse['waku']} 馬番{umaban}] {name}\n"
                            f"  【厩舎の話】 {danwa_comment}\n"
                            f"  【前走情報】 {prev_info}\n"
                            f"  【前走談話】 {prev_comment}\n"
                        )
                        merged_lines.append(block)

                # 最終的なプロンプトテキスト
                full_text = (
                    f"あなたはプロの競馬予想AIです。以下の{place_name}{i}Rの全頭データを分析し、"
                    f"推奨馬とその根拠、展開予想を行ってください。\n\n"
                    f"■レース情報\n{race_title_text}\n\n"
                    f"■出走馬詳細データ（全頭分）\n"
                    + "\n".join(merged_lines)
                )

                # -------------------------------------------------------
                # 4. Difyに分析させる
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
                        print(f"🎯 {place_name} {i}R 分析完了（保存します）")
                        
                        # Streamlit画面表示
                        st.markdown(f"### {place_name} {i}R")
                        st.write(ai_answer)
                        st.write("---")

                        # Supabaseへ保存
                        save_history(
                            YEAR, KAI, PLACE, place_name, DAY,
                            race_num_str, current_race_id, ai_answer
                        )
                    else:
                        print("⚠️ 分析結果が空でした。")
                else:
                    print(f"❌ Dify通信エラー: {response.status_code} - {response.text}")

            except Exception as e:
                print(f"❌ {i}R処理中に予期せぬエラー: {e}")

    finally:
        print("\n🧹 ブラウザを閉じます")
        driver.quit()


if __name__ == "__main__":
    # Streamlitで起動する場合、ボタンなどで発火させると管理しやすいですが
    # ここではスクリプト実行時に即走る構成にしています
    run_all_races()
