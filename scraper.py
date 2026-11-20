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

TOKEN = os.getenv("TELEGRAM_TOKEN", "6116556985:AAHme10EwOumFSKDkGFzq2WIk-86iNX4BIQ")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "507290424")

URL = "https://scanbet.io/pinnacle/drops/football"

# Порог изменения тотала (4 -> 3.5 = разница 0.5)
THRESHOLD = 1.25
CHECK_INTERVAL = 600

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

            if (compOddEl && currOddEl && compOddEl.innerText.trim() !== '-' && currOddEl.innerText.trim() !== '-') {
                result.push({
                    time: timeEl.innerText.trim(),
                    event: teamsEl.innerText.trim() + "\\n" + (leagueEl ? leagueEl.innerText.trim() : ""),
                    total: compOddEl.innerText.trim() + " " + currOddEl.innerText.trim()
                });
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
# УМНАЯ ЗАГРУЗКА ВСЕХ МАТЧЕЙ (БЕСКОНЕЧНЫЙ СКРОЛЛ)
# =====================================

def load_all_matches():
    print("\n🔄 ЗАГРУЗКА ВСЕХ МАТЧЕЙ (Бесконечный скролл)")
    
    # Ждем появления хотя бы одной строки
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr.drops-table__row"))
    )

    previous_count = 0
    no_change_count = 0

    # Цикл работает, пока количество матчей не перестанет расти 4 раза подряд
    while no_change_count < 4:
        save_rows(get_visible_rows())
        current_count = len(all_matches)
        print(f"📊 Текущее количество матчей: {current_count}")

        if current_count == previous_count:
            no_change_count += 1
        else:
            no_change_count = 0 # Если матчи добавились, сбрасываем счетчик
        previous_count = current_count

        # ТРИГГЕР ЗАГРУЗКИ: Находим самую последнюю строку в таблице и скроллим к ней
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr.drops-table__row")
            if rows:
                last_row = rows[-1]
                # Прокручиваем страницу так, чтобы последняя строка оказалась в центре экрана
                driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", last_row)
            else:
                # Если строк нет, скроллим всю страницу в самый низ
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception as e:
            print("Ошибка при скролле:", e)
            # Резервный вариант скролла
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        # Ждем, пока сайт подгрузит новые данные (3 секунды)
        time.sleep(3)

    print(f"✅ Загрузка завершена. Итоговое количество матчей: {len(all_matches)}")


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
    
    print("🍪 Проверка баннера с куки...")
    time.sleep(3)
    try:
        buttons = driver.find_elements(By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept') or contains(translate(text(), 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ', 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'), 'принять') or contains(translate(text(), 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ', 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'), 'соглас')]")
        if buttons:
            driver.execute_script("arguments[0].click();", buttons[0])
            print("✅ Баннер куки закрыт.")
            time.sleep(2)
        else:
            print("Баннер не найден, продолжаем.")
    except Exception as e:
        print(f"Ошибка при закрытии баннера (пропускаем): {e}")

    print("⏳ Ожидание появления таблицы (до 60 секунд)...")
    WebDriverWait(driver, 60).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "table.drops-table"))
    )

    print("✅ Таблица найдена")

    # Запускаем бесконечный скролл
    load_all_matches()

    if SINGLE_RUN:
        print(f"📊 Всего матчей собрано: {len(all_matches)}")
        process_matches()
        print("✅ Одиночный облачный проход успешно завершен!")
    else:
        send(
            "🚀 PINNACLE SCANNER ЗАПУЩЕН (HEADLESS)!\n\n"
            "✅ ScanBet подключен\n"
            f"📊 Собрано записей: {len(all_matches)}\n"
            f"📈 Порог: {THRESHOLD}\n"
            "🔔 Мониторинг активен!"
        )

        while True:
            try:
                load_all_matches()
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
    
    print("\n📸 СОХРАНЕНИЕ ДИАГНОСТИКИ...")
    try:
        driver.save_screenshot("error_screenshot.png")
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"🌐 Текущий URL: {driver.current_url}")
        print(f"📄 Заголовок страницы: {driver.title}")
    except Exception as diag_e:
        print("Не удалось сохранить диагностику:", diag_e)

finally:
    driver.quit()
    session.close()
