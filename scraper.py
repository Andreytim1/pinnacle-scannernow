import os
import json
import time
import re
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =====================================
# НАСТРОЙКИ
# =====================================

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

URL = "https://scanbet.io/pinnacle/drops/football"

THRESHOLD = 1.25 
CHECK_INTERVAL = 600 # 10 минут в секундах

SINGLE_RUN = os.getenv("SINGLE_RUN", "false").lower() == "true"
SENT_FILE = "sent_keys.json"


# =====================================
# СОХРАНЕНИЕ ИСТОРИИ СИГНАЛОВ
# =====================================

def load_sent_keys():
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception as e:
            print("⚠️ Не удалось прочитать sent_keys.json:", e, flush=True)
    return set()


def save_sent_keys(sent_set):
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent_set)[-2000:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ Не удалось сохранить sent_keys.json:", e, flush=True)


sent = load_sent_keys()
all_matches = {}


# =====================================
# TELEGRAM
# =====================================

session = requests.Session()


def send(msg):
    if not TOKEN or not CHAT_ID:
        print("❌ ОШИБКА: TELEGRAM_TOKEN или TELEGRAM_CHAT_ID не заданы!", flush=True)
        return False
        
    try:
        response = session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=15
        )
        result = response.json()
        
        if result.get("ok"):
            print("✅ Telegram отправлен!", flush=True)
            return True

        print("❌ Telegram error:", result.get("description", "Неизвестная ошибка"), flush=True)
        return False

    except Exception as e:
        print("❌ Ошибка сети при отправке в Telegram:", e, flush=True)
        return False


# =====================================
# CHROME (HEADLESS РЕЖИМ)
# =====================================

chrome_path = os.getenv("CHROME_PATH")

options = webdriver.ChromeOptions()

if chrome_path:
    options.binary_location = chrome_path

options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-setuid-sandbox")
options.add_argument(
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

print("⏳ Инициализация браузера...", flush=True)
driver = webdriver.Chrome(service=Service(), options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
print("✅ Браузер успешно инициализирован.", flush=True)


# =====================================
# ПОЛУЧЕНИЕ ВИДИМЫХ СТРОК
# =====================================

def get_visible_rows():
    script = """
    const table = document.querySelector('table.drops-table');
    if (!table) return [];

    const rows = Array.from(table.querySelectorAll('tbody tr.drops-table__row'));
    const result = [];

    rows.forEach(row => {
        const timeEl = row.querySelector('.drops-table__event-time');
        const teamsEl = row.querySelector('.drops-table__event .drops-table__teams-link');
        const leagueEl = row.querySelector('.drops-table__event .drops-table__league');
        const totalCell = row.querySelector('td.mat-column-T');

        if (timeEl && teamsEl && totalCell) {
            const compOddEl = totalCell.querySelector('.drops-table__comparison-odd');
            const currOddEl = totalCell.querySelector('.drops-table__current-odd');

            const compOddText = compOddEl ? compOddEl.innerText.trim() : "";
            const currOddText = currOddEl ? currOddEl.innerText.trim() : "";

            result.push({
                time: timeEl.innerText.trim(),
                event: teamsEl.innerText.trim() + "\\n" + (leagueEl ? leagueEl.innerText.trim() : ""),
                total: compOddText + " " + currOddText
            });
        }
    });
    return result;
    """
    return driver.execute_script(script)


# =====================================
# СОХРАНЕНИЕ СТРОК
# =====================================

def save_rows(rows):
    for row in rows:
        key = row["time"] + "|" + row["event"]
        all_matches[key] = row


# =====================================
# ЗАГРУЗКА ВСЕХ МАТЧЕЙ
# =====================================

def load_all_matches():
    print("\n🔄 ЗАГРУЗКА ВСЕХ МАТЧЕЙ...", flush=True)
    
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr.drops-table__row"))
    )

    previous_count = 0
    no_change_count = 0

    while no_change_count < 6:
        save_rows(get_visible_rows())
        current_count = len(all_matches)
        print(f"📊 Текущее количество матчей: {current_count}", flush=True)

        if current_count == previous_count:
            no_change_count += 1
        else:
            no_change_count = 0
        previous_count = current_count

        buttons = driver.find_elements(By.CSS_SELECTOR, "button.show-more-btn")
        visible_buttons = [b for b in buttons if b.is_displayed() and b.is_enabled()]

        if visible_buttons:
            print(f"🖱 Нажимаем 'Show More'...", flush=True)
            for btn in visible_buttons:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                except Exception:
                    pass
        else:
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr.drops-table__row")
                if rows:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", rows[-1])
            except:
                pass
            time.sleep(3)

    print(f"✅ Загрузка завершена. Итого: {len(all_matches)} матчей.", flush=True)


# =====================================
# ПАРСИНГ ТОТАЛА
# =====================================

def parse_total(value):
    if '-' in value:
        return None
    numbers = re.findall(r'[-+]?\d+(?:[.,]\d+)?', value)
    if len(numbers) < 2:
        return None
    return (float(numbers[0].replace(",", ".")), float(numbers[1].replace(",", ".")))


# =====================================
# ОБРАБОТКА СИГНАЛОВ
# =====================================

def process_matches():
    signals = 0
    print(f"\n🔍 ПРОВЕРКА СИГНАЛОВ (Порог: {THRESHOLD})", flush=True)

    for row in list(all_matches.values()):
        try:
            parsed = parse_total(row["total"])
            if parsed is None:
                continue

            old_t, new_t = parsed
            diff = round(abs(old_t - new_t), 2)

            if diff < THRESHOLD:
                continue

            event_lines = [x.strip() for x in row["event"].splitlines() if x.strip()]
            match = event_lines[0] if event_lines else "Unknown"
            league = event_lines[1] if len(event_lines) > 1 else ""

            key = f"{row['time']}|{match}|{old_t}|{new_t}"
            if key in sent:
                continue

            msg = (
                "🚨 PINNACLE TOTAL MOVE\n\n"
                f"🕒 {row['time']}\n"
                f"🏆 {league}\n"
                f"⚽ {match}\n"
                f"📊 T: {old_t} → {new_t}\n"
                f"📈 Move: {diff}"
            )

            if send(msg):
                sent.add(key)
                signals += 1

        except Exception as e:
            print("ROW ERROR:", e, flush=True)

    save_sent_keys(sent)
    print(f"🔔 ИТОГО Новых сигналов отправлено: {signals}", flush=True)


# =====================================
# ЗАПУСК
# =====================================

try:
    print("🚀 ЗАПУСК СКАНЕРА (HEADLESS РЕЖИМ)...", flush=True)
    
    # Засекаем время старта
    start_time = time.time()
    # Максимальное время работы: 5 часов 30 минут (в секундах)
    MAX_RUNTIME = 5.5 * 60 * 60 

    if SINGLE_RUN:
        print("📨 Тест связи с Telegram...", flush=True)
        send("🤖 Сканер запущен (одиночный проход).")
        
        driver.get(URL)
        time.sleep(3)
        WebDriverWait(driver, 60).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "table.drops-table")))
        load_all_matches()
        process_matches()
        print("✅ Одиночный проход завершен!", flush=True)
    else:
        print("📨 Тест связи с Telegram...", flush=True)
        send("🤖 Сканер запущен (режим 24/7). Следующие 5.5 часов буду присылать сигналы.")
        
        # Бесконечный цикл, который сам себя остановит через 5.5 часов
        while time.time() - start_time < MAX_RUNTIME:
            try:
                all_matches.clear() # Очищаем память перед новым кругом
                print(f"\n⏱ [Цикл] Время работы: {int((time.time() - start_time)/60)} мин.", flush=True)
                
                driver.get(URL) # Перезагружаем страницу
                time.sleep(3)
                
                # Ждем таблицу (если не дождемся, пропустим цикл)
                try:
                    WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "table.drops-table")))
                    load_all_matches()
                    process_matches()
                except Exception as e:
                    print("⚠️ Не удалось загрузить таблицу на этом круге:", e, flush=True)
                
                print(f"⏳ Сплю 10 минут до следующей проверки...", flush=True)
                time.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                print("❌ LOOP ERROR:", e, flush=True)
                time.sleep(60) # Если ошибка, ждем минуту и пробуем снова

        print("🛑 5.5 часов прошло. Завершаем работу, чтобы GitHub не убил процесс.", flush=True)
        send("🤖 Смена завершена (прошло 5.5 часов). Жду следующего запуска от GitHub.")

except KeyboardInterrupt:
    print("\n🛑 Сканер остановлен вручную", flush=True)
except Exception as e:
    print("❌ CRITICAL ERROR:", repr(e), flush=True)
    traceback.print_exc()
finally:
    driver.quit()
    session.close()
