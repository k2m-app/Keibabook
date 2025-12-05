import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==================================================
# 【設定エリア】
# ==================================================
# ================================
# 開催情報を外からセットする用の関数
# ================================
def set_race_params(year, kai, place, day):
    global YEAR, KAI, PLACE, DAY
    YEAR = year
    KAI = kai
    PLACE = place
    DAY = day

import streamlit as st  # 先頭の方に書く

# Secretsから読み込むように書き換える
login_id = st.secrets["KEIBA_ID"]
password = st.secrets["KEIBA_PASS"]

# 2. Dify APIキー（Secretsから読み込むように変更）
# 万が一 Secrets に設定がない場合は空文字にする安全策
DIFY_API_KEY = st.secrets.get("DIFY_API_KEY", "")

# 3. 開催情報の入力
YEAR  = "2025"
KAI   = "04"
PLACE = "00"
DAY   = "07"

# ▼▼ 場所コード早見表 ▼▼
# 00: 京都   01: 阪神   02: 中京   03: 小倉
# 04: 東京   05: 中山   06: 福島   07: 新潟
# 08: 札幌   09: 函館
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲


def run_all_races():
    base_race_id = f"{YEAR}{KAI}{PLACE}{DAY}"
    place_names = {
        "00": "京都", "01": "阪神", "02": "中京", "03": "小倉",
        "04": "東京", "05": "中山", "06": "福島", "07": "新潟",
        "08": "札幌", "09": "函館"
    }
    place_name = place_names.get(PLACE, "不明な競馬場")

   print(f"🚀 {YEAR}年{KAI}回 {place_name} {DAY}日目の全レース攻略を開始します！")

    # ▼▼ クラウド用設定（ヘッドレスモード）に変更 ▼▼
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument('--headless')  # 画面を表示しないモード
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
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
                # 1. 厩舎の話（修正箇所：ピンポイント抽出）
                # -------------------------------------------------------
                driver.get(url_danwa)
                time.sleep(1)

                if "login" in driver.current_url:
                    print("⚠️ ログインが外れている可能性があります！（厩舎の話ページ）")
                    continue

                # ★ここを変更しました：body全体ではなく、td.danwa の中身だけを取る
                danwa_elements = driver.find_elements(By.CSS_SELECTOR, "td.danwa")
                
                danwa_list = []
                for elem in danwa_elements:
                    # 空白を除去してリストに追加
                    text = elem.text.strip()
                    if text:
                        danwa_list.append(text)
                
                # リストを改行区切りで結合
                text_danwa = "\n".join(danwa_list)

                # -------------------------------------------------------
                # 2. 前走インタビュー（必要ならここも同様に修正推奨）
                # -------------------------------------------------------
                driver.get(url_interview)
                time.sleep(1)

                if "login" in driver.current_url:
                    continue

                # とりあえず現状維持（body全体取得）
                text_interview = driver.find_element(By.TAG_NAME, "body").text

                # データ合体
                full_text = (
                    f"【{place_name} {i}Rのデータ】\n"
                    "■厩舎の話\n" + text_danwa + "\n\n"
                    "■前走インタビュー（抜粋）\n" + text_interview[:1000] 
                )

                # -------------------------------------------------------
                # 3. Difyに分析させる
                # -------------------------------------------------------
                print(f"🧠 {place_name} {i}Rを分析中...")
                
                # ★注意: full_textが48文字を超える場合、Dify側で変数の設定変更が必要です
                
                url = "https://api.dify.ai/v1/workflows/run"
                headers = {
                    "Authorization": f"Bearer {DIFY_API_KEY}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "inputs": {"text": full_text},
                    "response_mode": "blocking",
                    "user": "keiba-bot-user"
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
                    else:
                        print("⚠️ 分析はできたけど、返事が空っぽでした...")
                        print(f"返ってきた中身: {result}")
                else:
                    print(f"❌ {i}Rのエラー: Dify通信失敗 (コード: {response.status_code})")
                    # エラーメッセージを詳しく表示
                    print(f"🔍 エラー詳細: {response.text}")
                    if "48 characters" in response.text:
                        print("👉 【重要】Difyの設定画面で、変数'text'のタイプを「短文」から「段落」に変更してください。")

            except Exception as e:
                print(f"❌ {i}R処理中にエラー: {e}")

    finally:
        print("\n🧹 ブラウザを閉じます")
        driver.quit()

if __name__ == "__main__":

    run_all_races()
