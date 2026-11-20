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
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# =====================================
# НАСТРОЙКИ
# =====================================

TOKEN = os.getenv("TELEGRAM_TOKEN", "6116556985:AAHme10EwOumFSKDkGFzq2WIk-86iNX4BIQ")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "507290424")

# Убрали параметры из URL, так как сайт их все равно срезает
URL = "https://scanbet.io/pinnacle/drops/football"

THRESHOLD = 1.25
CHECK_INTERVAL = 600
MAX_SHOW_MORE_CLICKS = 100

SINGLE_RUN = os.getenv("SINGLE_RUN", "true").lower() == "true"
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
            print("⚠️ Не удалось прочитать sent_keys.json:", e)
    return set()


def save_sent_keys(sent_set):
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent_set)[-2000:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ Не удалось сохранить sent_keys.json:", e)


sent = load_sent_keys()
all_matches = {}


# =====================================
# TELEGRAM
# =====================================

session = requests.Session()


def send(msg):
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
            print("✅ Telegram отправлен!")
            return True

        print("❌ Telegram error:", result)
        return False

    except Exception as e:
        print("❌ Telegram error:", e)
        return False


# =====================================
# CHROME (HEADLESS РЕЖИМ)
# =====================================

chrome_path = os.getenv("CHROME_PATH")
driver_path = os.getenv("CHROMEDRIVER_PATH")

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

if driver_path:
    service = Service(executable_path=driver_path)
else:
    service = Service()

driver = webdriver.Chrome(service=service, options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")


# =====================================
# ПОЛУЧЕНИЕ ВИДИМЫХ СТРОК
# =====================================

def get_visible_rows():
    script = """
    const table = document.querySelector('table.drops-table');
    if (!table) return [];

    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const result = [];
    let currentEvent = null;

    rows.forEach(row => {
        if (row.classList.contains('drops-table__event-header-row')) {
            const timeEl = row.querySelector('.drops-table__header-event-time');
            const teamsEl = row.querySelector('.drops-table__header-teams-link');
            const leagueEl = row.querySelector('.drops-table__event-header-second-row');

            if (timeEl && teamsEl) {
                currentEvent = {
                    time: timeEl.innerText.trim(),
                    event: teamsEl.innerText.trim() + "\\n" + (leagueEl ? leagueEl.innerText.replace(/\\s+/g, ' ').trim() : "")
                };
            }
        }
        else if (row.classList.contains('drops-table__row')) {
            const totalCell = row.querySelector('td.mat-column-T');
            
            if (totalCell && currentEvent) {
                const compOdd = totalCell.querySelector('.drops-table__comparison-odd');
                const currOdd = totalCell.querySelector('.drops-table__current-odd');

                if (compOdd && currOdd) {
                    result.push({
                        time: currentEvent.time,
                        event: currentEvent.event,
                        total: compOdd.innerText.trim() + " " + currOdd.innerText.trim()
                    });
                }
            }
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
# SHOW MORE
# =====================================

def show_all_rows():
    print("\n🔄 ЗАГРУЗКА SHOW MORE")
    clicks = 0

    while True:
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, "button.show-more-btn")
            if not buttons:
                print("✅ Show More закончился")
                break

            button = buttons[0]
            if not button.is_displayed() or not button.is_enabled():
                print("⚠️ Show More недоступен")
                break

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
            before = get_visible_rows()
            save_rows(before)

            driver.execute_script("arguments[0].click();", button)
            clicks += 1
            print(f"🖱 Show More №{clicks}")

            time.sleep(2)

            after = get_visible_rows()
            save_rows(after)
            print(f"📊 Видимых строк: {len(after)} | Всего уникальных собрано: {len(all_matches)}")

            if clicks >= MAX_SHOW_MORE_CLICKS:
                print("⚠️ Защитный лимит нажатий")
                break
        except Exception as e:
            print("SHOW MORE ERROR:", e)
            break

    save_rows(get_visible_rows())
    print("\n✅ ЗАГРУЗКА ЗАВЕРШЕНА")
    print("🖱 Нажатий:", clicks)
    print("📊 Собрано записей:", len(all_matches))


# =====================================
# ПРОКРУТКА ТАБЛИЦЫ
# =====================================

def collect_all_rows():
    print("\n🔍 СОБИРАЕМ ВСЕ СТРОКИ")
    try:
        container = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.drops-table-wrapper"))
        )
    except Exception as e:
        print("⚠️ Контейнер таблицы не найден, собираем видимые строки")
        save_rows(get_visible_rows())
        return

    previous_count = -1
    stable = 0

    while stable < 3:
        save_rows(get_visible_rows())
        current_count = len(all_matches)

        if current_count == previous_count:
            stable += 1
        else:
            stable = 0
        previous_count = current_count

        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
        time.sleep(1)

    save_rows(get_visible_rows())
    print(f"✅ Собрано уникальных записей: {len(all_matches)}")


# =====================================
# ПАРСИНГ ТОТАЛА
# =====================================

def parse_total(value):
    numbers = re.findall(r'[-+]?\d+(?:[.,]\d+)?', value)
    if len(numbers) < 2:
        return None
    return (float(numbers[0].replace(",", ".")), float(numbers[1].replace(",", ".")))


# =====================================
# ОБРАБОТКА СИГНАЛОВ
# =====================================

def process_matches():
    signals = 0

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

            print(f"🎯 {match}: {old_t} → {new_t} ({diff})")

            if send(msg):
                sent.add(key)
                signals += 1

        except Exception as e:
            print("ROW ERROR:", e)

    save_sent_keys(sent)
    print(f"🔔 Новых сигналов: {signals}")


# =====================================
# ЗАПУСК
# =====================================

try:
    print("🚀 ЗАПУСК СКАНЕРА (HEADLESS РЕЖИМ)...")
    print("🌐 Opening site...")

    driver.get(URL)
    
    # Пытаемся закрыть баннер с куки (если он есть)
    print("🍪 Проверка баннера с куки...")
    time.sleep(3) # Даем время баннеру прогрузиться
    try:
        # Ищем кнопки с типичными текстами согласия
        buttons = driver.find_elements(By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept') or contains(translate(text(), 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ', 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'), 'принять') or contains(translate(text(), 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ', 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'), 'соглас')]")
        if buttons:
            driver.execute_script("arguments[0].click();", buttons[0])
            print("✅ Баннер куки закрыт.")
            time.sleep(2)
        else:
            print("Баннер не найден, продолжаем.")
    except Exception as e:
        print(f"Ошибка при закрытии баннера (пропускаем): {e}")

    # Увеличили время ожидания до 60 секунд
    print("⏳ Ожидание появления таблицы (до 60 секунд)...")
    WebDriverWait(driver, 60).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "table.drops-table"))
    )

    WebDriverWait(driver, 20).until(
        lambda d: len(get_visible_rows()) > 0
    )

    print("✅ Таблица найдена")

    show_all_rows()
    collect_all_rows()

    if SINGLE_RUN:
        print(f"📊 Всего матчей собрано: {len(all_matches)}")
        process_matches()
        print("✅ Одиночный облачный проход успешно завершен!")
    else:
        send(
            "🚀 PINNACLE SCANNER ЗАПУЩЕН (HEADLESS)!\n\n"
            "✅ ScanBet подключен\n"
            "✅ Show More обработан\n"
            f"📊 Собрано записей: {len(all_matches)}\n"
            f"📈 Порог: {THRESHOLD}\n"
            f"⏱ Проверка: {CHECK_INTERVAL} сек.\n"
            "🔔 Мониторинг активен!"
        )

        while True:
            try:
                collect_all_rows()
                print(f"\n📊 Всего матчей в памяти: {len(all_matches)}")
                process_matches()
            except Exception as e:
                print("❌ LOOP ERROR:", e)

            time.sleep(CHECK_INTERVAL)

except KeyboardInterrupt:
    print("\n🛑 Сканер остановлен")

except Exception as e:
    print("❌ CRITICAL ERROR:", repr(e))
    traceback.print_exc()
    
    # --- СБОР ДИАГНОСТИКИ ПРИ ОШИБКЕ ---
    print("\n📸 СОХРАНЕНИЕ ДИАГНОСТИКИ...")
    try:
        driver.save_screenshot("error_screenshot.png")
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"🌐 Текущий URL: {driver.current_url}")
        print(f"📄 Заголовок страницы: {driver.title}")
    except Exception as diag_e:
        print("Не удалось сохранить диагностику:", diag_e)
    # -----------------------------------

finally:
    driver.quit()
    session.close()
