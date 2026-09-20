import asyncio
import os
import re
import random
import string
import sqlite3
from datetime import datetime
import requests
from PIL import Image
import pytesseract
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Telethon ХОМӮШ аст (проблемаи session)
TELETHON_ENABLED = False
try:
    from telethon import TelegramClient, events
    from telethon.network import ConnectionTcpObfuscated
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

# --- ТАНЗИМОТИ АСОСӢ (ҲАМАРО БО АРЗИШҲОИ ХУД ИВАЗ КУНЕД) ---
TOKEN = os.getenv("BOT_TOKEN", "8668882369:AAFSKxhaevHXWdGVNlz31cD5oBKQK44mKJc")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "8727925331"))

# ТОКЕНИ АСЛИИ API-И FIRELOOT
FIRELOOT_KEY = os.getenv("FIRELOOT_KEY", "fl_live_Er5dlM-JzL7sMIwW4k25IGpchsA6r3toqw21ysS9tho")
FIRELOOT_BASE = "https://partner.firelootshop.com/api/v1"

WHATSAPP_PHONE = "992933313738"
WHATSAPP_APIKEY = "5444428"
DC_CARD = "9762000001085389"
ALIF_ACCOUNT = "933313738"

CHANNEL_USERNAME = "@ffalmaz_shop_tj"

# --- Telethon (Userbot) барои хондани Zachislenie аз DC Next Bot ---
API_ID = int(os.getenv("TG_API_ID", "33314650"))
API_HASH = os.getenv("TG_API_HASH", "69c7be45f3960832adef665de2733c55")
DC_BOT_USERNAME = os.getenv("DC_BOT_USERNAME", "dc_next_bot")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "Almaz_dc_session")

user_data = {}
pending_orders = {}
known_users = set()
bot_app = None

# --- БАЗАИ МАЪЛУМОТ ---
conn = sqlite3.connect("receipts.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS used_receipts (tx_id TEXT PRIMARY KEY)")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS partners (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        discount INTEGER DEFAULT 0,
        balance REAL DEFAULT 0.0,
        added_at TEXT
    )
""")
# Агар ҷадвал қаблан буд, сутуни balance-ро илова мекунем
try:
    cursor.execute("ALTER TABLE partners ADD COLUMN balance REAL DEFAULT 0.0")
    conn.commit()
except sqlite3.OperationalError:
    pass  # аллакай вуҷуд дорад
conn.commit()

# Нархҳои фикседаи шарик (бе %)
PARTNER_PRICES = {
    # Free Fire Алмазҳо
    "pkg_1": 8.40,      # 110 Алмаз
    "pkg_2": 25.00,     # 341 Алмаз
    "pkg_3": 42.50,     # 572 Алмаз
    "pkg_4": 86.00,     # 1166 Алмаз
    "pkg_5": 170.00,    # 2398 Алмаз
    "pkg_6": 414.00,    # 6160 Алмаз
    # Ваучерҳо
    "pkg_7": 16.20,     # Weekly
    "pkg_8": 59.00,     # Monthly
    "pkg_13": 4.50,     # Weekly Lite
    # PUBG UC
    "pubg_60": 9.60,
    "pubg_325": 47.80,
    "pubg_660": 92.00,
    "pubg_1800": 235.00,
    "pubg_3850": 440.00,
    "pubg_8100": 865.00,
    "pubg_16200": 1670.00,
    "pubg_24300": 2650.00,
    "pubg_32400": 3650.00,
    "pubg_40500": 4450.00,
}


def is_tx_used(tx_id: str) -> bool:
    cursor.execute("SELECT tx_id FROM used_receipts WHERE tx_id = ?", (tx_id,))
    return cursor.fetchone() is not None


def save_tx(tx_id: str):
    try:
        cursor.execute("INSERT INTO used_receipts (tx_id) VALUES (?)", (tx_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass


def is_partner(user_id: int) -> bool:
    cursor.execute("SELECT user_id FROM partners WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


def get_partner_balance(user_id: int) -> float:
    cursor.execute("SELECT balance FROM partners WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def add_partner_balance(user_id: int, amount: float) -> bool:
    try:
        cursor.execute(
            "UPDATE partners SET balance = COALESCE(balance, 0) + ? WHERE user_id = ?",
            (amount, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False


def deduct_partner_balance(user_id: int, amount: float) -> bool:
    """Балансро кам мекунад. Агар кофӣ набошад — False."""
    bal = get_partner_balance(user_id)
    if bal < amount:
        return False
    try:
        cursor.execute(
            "UPDATE partners SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
            (amount, user_id, amount)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False


def set_partner_balance(user_id: int, amount: float) -> bool:
    """Балансро ба маблағи дақиқ мегузорад (масалан 0)."""
    try:
        cursor.execute(
            "UPDATE partners SET balance = ? WHERE user_id = ?",
            (amount, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False


def add_partner(user_id: int, username: str = "", discount: int = 0) -> bool:
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO partners (user_id, username, discount, balance, added_at) VALUES (?, ?, ?, COALESCE((SELECT balance FROM partners WHERE user_id = ?), 0), ?)",
            (user_id, username.lstrip("@"), discount, user_id, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        return True
    except Exception:
        return False


def remove_partner(user_id: int) -> bool:
    cursor.execute("DELETE FROM partners WHERE user_id = ?", (user_id,))
    conn.commit()
    return cursor.rowcount > 0


def list_partners() -> list:
    cursor.execute("SELECT user_id, username, discount, balance, added_at FROM partners ORDER BY added_at DESC")
    return cursor.fetchall()


def get_price_for_user(pkg_key: str, base_price: float, user_id: int) -> float:
    """Нархи ниҳоӣ барои шарик (нархи фиксед) ё нархи оддӣ"""
    if is_partner(user_id) and pkg_key in PARTNER_PRICES:
        return PARTNER_PRICES[pkg_key]
    return base_price


# ===================== ПАКЕТҲО =====================
PACKAGES = {
    # ===== Free Fire (CIS) — Алмазҳо =====
    "pkg_1": {"name": "💎 110 Алмаз", "price": 9.00, "sku": "diamonds_110", "game": "ff"},
    "pkg_2": {"name": "💎 341 Алмаз", "price": 28.00, "sku": "diamonds_341", "game": "ff"},
    "pkg_3": {"name": "💎 572 Алмаз", "price": 45.00, "sku": "diamonds_572", "game": "ff"},
    "pkg_4": {"name": "💎 1166 Алмаз", "price": 89.90, "sku": "diamonds_1166", "game": "ff"},
    "pkg_5": {"name": "💎 2398 Алмаз", "price": 177.00, "sku": "diamonds_2398", "game": "ff"},
    "pkg_6": {"name": "💎 6160 Алмаз", "price": 429.00, "sku": "diamonds_6160", "game": "ff"},

    # ===== Free Fire (CIS) — Ваучерҳо =====
    "pkg_7": {"name": "🎟 Ваучери Ҳафтаина (Weekly)", "price": 16.80, "sku": "voucher_week", "game": "ff"},
    "pkg_8": {"name": "🎟 Ваучери Моҳона (Monthly)", "price": 64.80, "sku": "voucher_month", "game": "ff"},
    "pkg_13": {"name": "🔹 Ваучери Лайт (Weekly Lite)", "price": 6.00, "sku": "voucher_week_lite_2", "game": "ff"},

    # ===== Free Fire Indonesia — Алмазҳо =====
    "ff_50":    {"name": "💎 50 Алмаз",     "price": 5.50,   "sku": "id_diamonds_50",    "game": "ff"},
    "ff_100":   {"name": "💎 100 Алмаз",    "price": 10.50,  "sku": "id_diamonds_100",   "game": "ff"},
    "ff_140":   {"name": "💎 140 Алмаз",    "price": 14.00,  "sku": "id_diamonds_140",   "game": "ff"},
    "ff_210":   {"name": "💎 210 Алмаз",    "price": 19.00,  "sku": "id_diamonds_210",   "game": "ff"},
    "ff_280":   {"name": "💎 280 Алмаз",    "price": 24.00,  "sku": "id_diamonds_280",   "game": "ff"},
    "ff_355":   {"name": "💎 355 Алмаз",    "price": 30.00,  "sku": "id_diamonds_355",   "game": "ff"},
    "ff_500":   {"name": "💎 500 Алмаз",    "price": 45.00,  "sku": "id_diamonds_500",   "game": "ff"},
    "ff_720":   {"name": "💎 720 Алмаз",    "price": 60.00,  "sku": "id_diamonds_720",   "game": "ff"},
    "ff_1000":  {"name": "💎 1000 Алмаз",   "price": 85.00,  "sku": "id_diamonds_1000",  "game": "ff"},
    "ff_1450":  {"name": "💎 1450 Алмаз",   "price": 114.00, "sku": "id_diamonds_1450",  "game": "ff"},
    "ff_2180":  {"name": "💎 2180 Алмаз",   "price": 175.00, "sku": "id_diamonds_2180",  "game": "ff"},
    "ff_3640":  {"name": "💎 3640 Алмаз",   "price": 290.00, "sku": "id_diamonds_3640",  "game": "ff"},
    "ff_7290":  {"name": "💎 7290 Алмаз",   "price": 600.00, "sku": "id_diamonds_7290",  "game": "ff"},

    # ===== Free Fire Indonesia — Membership =====
    "ff_week":  {"name": "🎟 Ҳафтаина (Weekly)",  "price": 19.50, "sku": "id_membership_weekly",  "game": "ff"},
    "ff_month": {"name": "🎟 Моҳона (Monthly)",  "price": 69.80, "sku": "id_membership_monthly", "game": "ff"},

    # ===== PUBG UC =====
    "pubg_60":   {"name": "🎮 60 UC",              "price": 10.00,  "sku": "pubg_uc_60",    "game": "pubg"},
    "pubg_325":  {"name": "🎮 300 + 25 UC",        "price": 48.95,  "sku": "pubg_uc_325",   "game": "pubg"},
    "pubg_660":  {"name": "🎮 600 + 60 UC",        "price": 93.70,  "sku": "pubg_uc_660",   "game": "pubg"},
    "pubg_1800": {"name": "🎮 1,500 + 300 UC",     "price": 241.00, "sku": "pubg_uc_1800",  "game": "pubg"},
    "pubg_3850": {"name": "🎮 3,000 + 850 UC",     "price": 452.00, "sku": "pubg_uc_3850",  "game": "pubg"},
    "pubg_8100": {"name": "🎮 6,000 + 2,100 UC",   "price": 900.00, "sku": "pubg_uc_8100",  "game": "pubg"},
    "pubg_16200":{"name": "🎮 12,000 + 4,200 UC",  "price": 1800.00,"sku": "pubg_uc_16200", "game": "pubg"},
    "pubg_24300":{"name": "🎮 18,000 + 6,300 UC",  "price": 2700.00,"sku": "pubg_uc_24300", "game": "pubg"},
    "pubg_32400":{"name": "🎮 24,000 + 8,400 UC",  "price": 3700.00,"sku": "pubg_uc_32400", "game": "pubg"},
    "pubg_40500":{"name": "🎮 30,000 + 10,500 UC", "price": 4500.00,"sku": "pubg_uc_40500", "game": "pubg"},

    # ===== Telegram Stars =====
    "stars_50":   {"name": "⭐ 50 Stars",   "price": 9.80,  "sku": "stars_50",   "game": "stars", "stars": 50},
    "stars_100":  {"name": "⭐ 100 Stars",  "price": 19.25, "sku": "stars_100",  "game": "stars", "stars": 100},
    "stars_500":  {"name": "⭐ 500 Stars",  "price": 90.00, "sku": "stars_500",  "game": "stars", "stars": 500},
    "stars_1000": {"name": "⭐ 1000 Stars", "price": 175.00,"sku": "stars_1000", "game": "stars", "stars": 1000},
    "stars_2500": {"name": "⭐ 2500 Stars", "price": 425.00,"sku": "stars_2500", "game": "stars", "stars": 2500},
}

VALIDATE_ERROR_MESSAGES = {
    "invalid_uid": "ID-и плеер нодуруст аст",
    "invalid_request": "Дархост нодуруст аст (маълумот намерасад)",
    "unauthorized": "Калиди API нодуруст аст",
    "region_unsupported": "Региони аккаунт дастгирӣ намешавад",
    "product_not_found": "Ин SKU дар FireLoot пайдо нашуд",
    "rate_limited": "Дархостҳо хеле зиёданд, лутфан баъдтар кӯшиш кунед",
    "service_unavailable": "Сервиси FireLoot вақтинча дастнорас аст",
}

ORDER_ERROR_MESSAGES = {
    "invalid_uid": "ID-и плеер нодуруст аст.",
    "invalid_request": "Дархост нодуруст аст (маълумот намерасад).",
    "unauthorized": "Калиди API нодуруст аст.",
    "insufficient_balance": "Баланси FireLoot Partner кофӣ нест!",
    "product_not_found": "SKU дар FireLoot пайдо нашуд ё заморозка аст.",
    "order_not_found": "Фармоиш пайдо нашуд.",
    "duplicate_order": "Ин external_id аллакай истифода шудааст.",
    "region_unsupported": "Региони аккаунт дастгирӣ намешавад.",
    "rate_limited": "Дархостҳо хеле зиёданд, лутфан баъдтар кӯшиш кунед.",
    "service_unavailable": "Сервиси FireLoot вақтинча дастнорас аст.",
}


def get_player_nickname(player_id: str, sku: str) -> tuple[bool, str]:
    """Универсалӣ: ҳам Free Fire ва ҳам PUBG"""
    url = f"{FIRELOOT_BASE}/validate"
    headers = {
        "Authorization": f"Bearer {FIRELOOT_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "sku": sku,
        "uid": str(player_id),
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=20)
        data = res.json() if res.content else {}

        if res.status_code == 200:
            if data.get("valid") is True and data.get("player_name"):
                return True, data["player_name"]
            else:
                code = data.get("code", "")
                return False, VALIDATE_ERROR_MESSAGES.get(code, code or "Никнейм автоматикӣ пайдо нашуд")
        else:
            return False, f"Сервер ҷавоб надод ({res.status_code})"
    except Exception:
        return False, "Вақти тафтиш гузашт"


def send_fireloot_order(player_id: str, sku: str, external_id: str) -> dict:
    url = f"{FIRELOOT_BASE}/order"
    headers = {
        "Authorization": f"Bearer {FIRELOOT_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "external_id": str(external_id),
        "sku": str(sku),
        "uid": str(player_id),
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=35)
        data = res.json() if res.content else {}

        if res.status_code in (200, 201):
            return {"success": True, "data": data}
        else:
            err_code = (
                data.get("code")
                or (data.get("error", {}).get("code") if isinstance(data.get("error"), dict) else None)
            )
            err_msg = (
                data.get("message")
                or (data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else None)
                or res.text
            )
            readable_err = ORDER_ERROR_MESSAGES.get(err_code, f"{err_code or res.status_code}: {err_msg}")
            return {"success": False, "error": readable_err, "code": err_code}
    except Exception as e:
        return {"success": False, "error": f"Хатогии шабака: {e}"}


def get_order_status(fireloot_order_id: str, by_external: bool = False) -> dict:
    if by_external:
        url = f"{FIRELOOT_BASE}/order/{fireloot_order_id}?by=external"
    else:
        url = f"{FIRELOOT_BASE}/order/{fireloot_order_id}"
    headers = {"Authorization": f"Bearer {FIRELOOT_KEY}"}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        data = res.json() if res.content else {}
        if res.status_code == 200:
            return {"success": True, "data": data}
        else:
            return {"success": False, "error": f"HTTP {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_fireloot_balance() -> dict:
    url = f"{FIRELOOT_BASE}/balance"
    headers = {"Authorization": f"Bearer {FIRELOOT_KEY}"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json() if res.content else {}
        if res.status_code == 200:
            return {
                "success": True,
                "balance": data.get("balance"),
                "currency": data.get("currency", "USD"),
                "stars_balance": data.get("stars_balance"),
                "telegram_active": data.get("telegram_active"),
            }
        else:
            return {"success": False, "error": f"HTTP {res.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_telegram_user(username: str, stars: int) -> tuple[bool, str, str]:
    """Тафтиши username барои Telegram Stars. Баргашт: (valid, name_or_error, clean_username)"""
    url = f"{FIRELOOT_BASE}/telegram/check"
    headers = {
        "Authorization": f"Bearer {FIRELOOT_KEY}",
        "Content-Type": "application/json",
    }
    username = username.lstrip("@").strip()
    payload = {
        "username": username,
        "stars": int(stars),
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=20)
        data = res.json() if res.content else {}
        if res.status_code == 200 and data.get("valid") is True:
            name = data.get("name") or username
            return True, name, username
        else:
            code = data.get("code", "")
            msg = {
                "not_found": "Username пайдо нашуд",
                "invalid_username": "Username нодуруст аст",
            }.get(code, code or "Username пайдо нашуд")
            return False, msg, username
    except Exception:
        return False, "Вақти тафтиш гузашт", username


def send_telegram_stars_order(username: str, stars: int, external_id: str) -> dict:
    """Фиристодани Telegram Stars тавассути FireLoot"""
    url = f"{FIRELOOT_BASE}/telegram/order"
    headers = {
        "Authorization": f"Bearer {FIRELOOT_KEY}",
        "Content-Type": "application/json",
    }
    username = username.lstrip("@").strip()
    payload = {
        "username": username,
        "stars": int(stars),
        "external_id": str(external_id),
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=35)
        data = res.json() if res.content else {}
        if res.status_code in (200, 201):
            return {"success": True, "data": data}
        else:
            err_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
            err_code = err_obj.get("code") or data.get("code")
            err_msg = err_obj.get("message") or data.get("message") or res.text
            readable = {
                "insufficient_stars_balance": "Баланси звёздный (Stars) кофӣ нест! Аз панел пур кунед.",
                "invalid_username": "Username нодуруст аст",
                "not_found": "Username пайдо нашуд",
                "invalid_quantity": "Миқдори Stars нодуруст аст",
            }.get(err_code, f"{err_code or res.status_code}: {err_msg}")
            return {"success": False, "error": readable, "code": err_code}
    except Exception as e:
        return {"success": False, "error": f"Хатогии шабака: {e}"}


def fetch_fireloot_products() -> dict:
    url = f"{FIRELOOT_BASE}/products"
    headers = {"Authorization": f"Bearer {FIRELOOT_KEY}"}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            items = res.json() if res.content else []
            return {item["sku"]: item for item in items if "sku" in item}
        else:
            print(f"⚠️ GET /products хатогӣ дод: HTTP {res.status_code} — {res.text}")
            return {}
    except Exception as e:
        print(f"⚠️ GET /products дастнорас: {e}")
        return {}


def validate_packages_against_fireloot():
    live_products = fetch_fireloot_products()
    if not live_products:
        print("⚠️ Натавонистам каталоги FireLoot-ро тафтиш кунам (токен/шабака). "
              "SKU-ҳои PACKAGES тафтиш нашуданд!")
        return

    print(f"✅ FireLoot каталог гирифта шуд: {len(live_products)} маҳсулот дастрас аст.")
    missing = []
    for pkg_id, pkg in PACKAGES.items():
        if pkg.get("game") == "stars":
            continue  # Stars алоҳида тавассути /telegram/products кор мекунад
        sku = pkg["sku"]
        if sku not in live_products:
            missing.append((pkg_id, pkg["name"], sku))

    if missing:
        print("❌ ИН SKU-ҲО ДАР КАТАЛОГИ ВОҚЕИИ FIRELOOT НЕСТАНД:")
        for pkg_id, name, sku in missing:
            print(f"   • {pkg_id} ({name}) → sku='{sku}'")
    else:
        print("✅ Ҳамаи SKU-ҳои PACKAGES (ба ғайр аз Stars) бо каталоги FireLoot мувофиқанд.")


async def wait_for_order_completion(fireloot_order_id: str, max_wait: int = 90, interval: int = 4) -> dict:
    elapsed = 0
    last = {"success": False, "error": "timeout"}
    while elapsed < max_wait:
        result = await asyncio.to_thread(get_order_status, fireloot_order_id)
        if result["success"]:
            last = result
            status = result["data"].get("status")
            if status in ("completed", "failed", "refunded"):
                return result
        await asyncio.sleep(interval)
        elapsed += interval
    return last


def fmt_price(price: float) -> str:
    return f"{int(price)}" if price == int(price) else f"{price:.2f}"


async def safe_edit(query, text: str, **kwargs):
    """Хатогии 'Message is not modified'-ро нодида мегирад"""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME, user_id=user_id
        )
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def subscribe_keyboard():
    channel_url = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Обуна шудан", url=channel_url)],
            [
                InlineKeyboardButton(
                    "✅ Обуна шудам — санҷед", callback_data="check_sub"
                )
            ],
        ]
    )


async def send_subscribe_prompt(update: Update):
    text = (
        "🔒 *Барои истифодаи бот аввал ба канали мо обуна шавед.*\n\n"
        "Пас аз обуна шудан, тугмаи «✅ Обуна шудам» -ро зер кунед."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=subscribe_keyboard()
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=subscribe_keyboard()
        )


def gen_order_id():
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    rnd = "".join(random.choices(string.digits, k=4))
    return f"{ts}{rnd}"


def dc_pay_url(amount: float, order_id: str) -> str:
    return f"http://pay.dc.tj/?A={DC_CARD}&s={amount:.2f}&c={order_id}&f1=133&FIELD2=&FIELD3="


def alif_url(amount: float) -> str:
    return f"https://alifmobi.page.link/providers?id=124&amount={amount:.2f}&account={ALIF_ACCOUNT}"


def send_whatsapp(message: str):
    try:
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={requests.utils.quote(message)}&apikey={WHATSAPP_APIKEY}"
        requests.get(url, timeout=5)
    except Exception:
        pass


# ===================== КЛАВИАТУРАҲО =====================
def main_menu_keyboard(user_id: int = 0):
    buttons = [
        [InlineKeyboardButton("🔥 Free Fire", callback_data="cat_ff")],
        [InlineKeyboardButton("🇮🇩 Free Fire Indonesia", callback_data="cat_ff_id")],
        [InlineKeyboardButton("🎮 PUBG UC", callback_data="cat_pubg")],
        [InlineKeyboardButton("⭐ Telegram Stars", callback_data="cat_stars")],
    ]
    if is_partner(user_id):
        bal = get_partner_balance(user_id)
        buttons.append([InlineKeyboardButton(
            f"💰 Баланс: {fmt_price(bal)} с. | Пур кардан", callback_data="partner_balance"
        )])
    buttons.append([InlineKeyboardButton("📞 Тамос бо админ", callback_data="contact")])
    return InlineKeyboardMarkup(buttons)


def freefire_menu_keyboard():
    """Менюи Free Fire (CIS)"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💎 Алмазҳо", callback_data="cat_almaz")],
            [InlineKeyboardButton("🎟 Ваучерҳо", callback_data="cat_vaucher")],
            [InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")],
        ]
    )


def freefire_id_menu_keyboard():
    """Менюи Free Fire Indonesia"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💎 Алмазҳо", callback_data="cat_almaz_id")],
            [InlineKeyboardButton("🎟 Membership", callback_data="cat_member_id")],
            [InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")],
        ]
    )


def almaz_keyboard(user_id: int = 0):
    buttons = []
    for key in ["pkg_1", "pkg_2", "pkg_3", "pkg_4", "pkg_5", "pkg_6"]:
        pkg = PACKAGES[key]
        price = get_price_for_user(key, pkg["price"], user_id)
        buttons.append([InlineKeyboardButton(
            f"{pkg['name']} — {fmt_price(price)} сомонӣ", callback_data=key
        )])
    buttons.append([InlineKeyboardButton("« Баргашт", callback_data="cat_ff")])
    return InlineKeyboardMarkup(buttons)


def vaucher_keyboard(user_id: int = 0):
    buttons = []
    for key in ["pkg_7", "pkg_8", "pkg_13"]:
        pkg = PACKAGES[key]
        price = get_price_for_user(key, pkg["price"], user_id)
        buttons.append([InlineKeyboardButton(
            f"{pkg['name']} — {fmt_price(price)} сомонӣ", callback_data=key
        )])
    buttons.append([InlineKeyboardButton("« Баргашт", callback_data="cat_ff")])
    return InlineKeyboardMarkup(buttons)


def almaz_id_keyboard(user_id: int = 0):
    """Алмазҳои Free Fire Indonesia — бе тахфифи шарик"""
    buttons = []
    for key in [
        "ff_50", "ff_100", "ff_140", "ff_210", "ff_280", "ff_355",
        "ff_500", "ff_720", "ff_1000", "ff_1450", "ff_2180", "ff_3640", "ff_7290",
    ]:
        pkg = PACKAGES[key]
        price = pkg["price"]  # Indonesia барои шарик тахфиф надорад
        buttons.append([InlineKeyboardButton(
            f"{pkg['name']} — {fmt_price(price)} сомонӣ", callback_data=key
        )])
    buttons.append([InlineKeyboardButton("« Баргашт", callback_data="cat_ff_id")])
    return InlineKeyboardMarkup(buttons)


def member_id_keyboard(user_id: int = 0):
    """Membership Free Fire Indonesia — бе тахфифи шарик"""
    buttons = []
    for key in ["ff_week", "ff_month"]:
        pkg = PACKAGES[key]
        price = pkg["price"]
        buttons.append([InlineKeyboardButton(
            f"{pkg['name']} — {fmt_price(price)} сомонӣ", callback_data=key
        )])
    buttons.append([InlineKeyboardButton("« Баргашт", callback_data="cat_ff_id")])
    return InlineKeyboardMarkup(buttons)


def pubg_keyboard(user_id: int = 0):
    buttons = []
    for key in ["pubg_60", "pubg_325", "pubg_660", "pubg_1800", "pubg_3850",
                "pubg_8100", "pubg_16200", "pubg_24300", "pubg_32400", "pubg_40500"]:
        pkg = PACKAGES[key]
        price = get_price_for_user(key, pkg["price"], user_id)
        buttons.append([InlineKeyboardButton(
            f"{pkg['name']} — {fmt_price(price)} сомонӣ", callback_data=key
        )])
    buttons.append([InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def stars_keyboard(user_id: int = 0):
    buttons = []
    for key in ["stars_50", "stars_100", "stars_500", "stars_1000", "stars_2500"]:
        pkg = PACKAGES[key]
        # Stars барои шарикон тахфиф надорад
        price = pkg["price"]
        buttons.append([InlineKeyboardButton(
            f"{pkg['name']} — {fmt_price(price)} сомонӣ", callback_data=key
        )])
    buttons.append([InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def payment_keyboard(order_id: str, amount: float, user_id: int = 0, pkg_key: str = ""):
    buttons = [
        [InlineKeyboardButton("🏦 DC Pay", url=dc_pay_url(amount, order_id)),
         InlineKeyboardButton("📱 Alif Mobi", url=alif_url(amount))],
        [InlineKeyboardButton("✅ Ман пардохт кардам", callback_data="paid")],
    ]
    # Агар шарик бошад ва баланс кофӣ бошад — тугмаи пардохт аз баланс
    if is_partner(user_id) and pkg_key in PARTNER_PRICES:
        bal = get_partner_balance(user_id)
        if bal >= amount:
            buttons.insert(0, [InlineKeyboardButton(
                f"💰 Пардохт аз баланс ({fmt_price(bal)} с.)", callback_data="pay_balance"
            )])
    buttons.append([InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)


def admin_confirm_keyboard(customer_id: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Тасдиқ кардан", callback_data=f"confirm_{customer_id}"),
                InlineKeyboardButton("❌ Рад кардан", callback_data=f"reject_{customer_id}"),
            ]
        ]
    )


def admin_topup_keyboard(customer_id: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Баланс пур кардан", callback_data=f"topup_ok_{customer_id}"),
                InlineKeyboardButton("❌ Рад кардан", callback_data=f"topup_no_{customer_id}"),
            ]
        ]
    )


# ===================== HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    known_users.add(user_id)
    user_data[user_id] = {}
    await update.message.reply_text(
        "Салом! 👋\n\nБа боти *ALMAZ TJ ⚡* хуш омадед.\nКатегорияро интихоб кунед:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user_id),
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    known_users.add(user_id)
    user = query.from_user
    data = query.data

    if user_id not in user_data:
        user_data[user_id] = {}

    # ===== ТАСДИҚИ АДМИН =====
    if data.startswith("confirm_"):
        if user_id != ADMIN_TELEGRAM_ID:
            return
        customer_id = int(data.split("_")[1])
        order_info = pending_orders.get(customer_id)

        if not order_info:
            await query.message.reply_text("❌ Маълумоти ин заказ пайдо нашуд!")
            return

        # Агар ин пуркунии баланс бошад — ин ҷо кор намекунад (topup_ok_ истифода баред)
        if order_info.get("type") == "topup" or order_info.get("game") == "topup":
            await query.message.reply_text(
                "⚠️ Ин пуркунии баланс аст. Тугмаи «✅ Баланс пур кардан»-ро истифода баред."
            )
            return

        player_id = order_info.get("ff_id")
        sku = order_info.get("sku", "diamonds_110")
        nickname = order_info.get("nickname", "—")
        pkg_name = order_info.get("package", "—")
        price = order_info.get("price", 0)
        order_id = order_info.get("order_id", gen_order_id())
        stars_amount = order_info.get("stars_amount")
        game = order_info.get("game", "ff")
        date_str = datetime.now().strftime("%d.%m.%Y • %H:%M")

        status_msg = await query.message.reply_text("⏳ Дар ҳоли фиристодани донат тавассути FireLoot API...")

        # ===== Telegram Stars =====
        if game == "stars" or (sku and str(sku).startswith("stars_")):
            if not stars_amount:
                stars_amount = PACKAGES.get(
                    next((k for k, v in PACKAGES.items() if v.get("sku") == sku), ""), {}
                ).get("stars", 50)
            api_res = await asyncio.to_thread(
                send_telegram_stars_order, player_id, stars_amount, order_id
            )
            if not api_res["success"]:
                err = api_res.get("error", "номаълум")
                extra = ""
                if api_res.get("code") == "insufficient_stars_balance":
                    bal = await asyncio.to_thread(get_fireloot_balance)
                    if bal.get("success"):
                        extra = f"\n\n⭐ Stars balance: `{bal.get('stars_balance')}`"
                await status_msg.edit_text(
                    f"❌ *Хатогӣ дар FireLoot Telegram Stars!*\n\n"
                    f"📌 *Сабаб:* `{err}`{extra}\n\n"
                    f"Звёздный баланс-ро дар панел пур кунед.\n"
                    f"Фармони /balance -ро истифода баред.",
                    parse_mode="Markdown",
                )
                return

            fl_order_id = api_res.get("data", {}).get("order_id") or api_res.get("data", {}).get("id") or "—"
            receipt_text = (
                f"🧾 *ЧЕКИ ПАРДОХТ — ALMAZ TJ*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *Статус:* МУВАФФАҚ\n"
                f"🔢 *Фармоиш №:* `#{order_id}` (FL: `{fl_order_id}`)\n"
                f"👤 *Username:* `@{player_id}`\n"
                f"👤 *Ном:* {nickname}\n"
                f"📦 *Пакет:* {pkg_name}\n"
                f"⭐ *Миқдор:* {stars_amount} Stars\n"
                f"💰 *Маблағ:* {fmt_price(price)} сомонӣ\n"
                f"📅 *Сана:* {date_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎉 *Stars ба аккаунти шумо гузашт!*\n\n"
                f"Ташаккур барои харид! ❤️\n"
                f"Барои закази нав /start -ро пахш кунед."
            )
            try:
                await context.bot.send_message(
                    chat_id=customer_id, text=receipt_text, parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error sending stars receipt: {e}")

            await status_msg.edit_text(
                f"✅ *Заказ иҷро шуд!* {stars_amount} Stars ба `@{player_id}` гузашт.\n`FireLoot ID: {fl_order_id}`",
                parse_mode="Markdown",
            )
            pending_orders.pop(customer_id, None)
            return

        # ===== Free Fire / PUBG =====
        api_res = await asyncio.to_thread(send_fireloot_order, player_id, sku, order_id)

        if not api_res["success"]:
            err = api_res.get("error", "номаълум")
            extra = ""
            if api_res.get("code") == "insufficient_balance":
                bal = await asyncio.to_thread(get_fireloot_balance)
                if bal.get("success"):
                    extra = f"\n\n💰 Баланси ҳозира: `{bal.get('balance')}` USD"
            await status_msg.edit_text(
                f"❌ *Хатогӣ дар FireLoot API!*\nДонат гузаронида нашуд.\n\n"
                f"📌 *Сабаб:* `{err}`{extra}\n\n"
                f"Баланси FireLoot Partner ва SKU-ро тафтиш кунед.\n"
                f"Фармони /balance -ро истифода баред.",
                parse_mode="Markdown",
            )
            return

        fl_order_id = api_res["data"].get("order_id", "—")

        await status_msg.edit_text(
            f"⏳ Фармоиш ба FireLoot фиристода шуд, интизори иҷрои ниҳоӣ...\n`FireLoot ID: {fl_order_id}`",
            parse_mode="Markdown",
        )

        final = await wait_for_order_completion(fl_order_id)

        if not final.get("success") or final.get("data", {}).get("status") not in ("completed", "failed", "refunded"):
            fallback = await asyncio.to_thread(get_order_status, order_id, True)
            if fallback.get("success"):
                final = fallback

        final_data = final.get("data", {}) if final.get("success") else {}
        final_status = final_data.get("status")

        if final_status == "completed":
            receipt_text = (
                f"🧾 *ЧЕКИ ПАРДОХТ — ALMAZ TJ*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *Статус:* МУВАФФАҚ\n"
                f"🔢 *Фармоиш №:* `#{order_id}` (FL: `{fl_order_id}`)\n"
                f"🎮 *ID Аккаунт:* `{player_id}`\n"
                f"👤 *Никнейм:* {nickname}\n"
                f"📦 *Пакет:* {pkg_name}\n"
                f"💰 *Маблағ:* {fmt_price(price)} сомонӣ\n"
                f"📅 *Сана:* {date_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎉 *Хариди шумо муваффақона иҷро шуд!*\n\n"
                f"Ташаккур барои харид! ❤️\n"
                f"Барои закази нав /start -ро пахш кунед."
            )
            try:
                await context.bot.send_message(
                    chat_id=customer_id, text=receipt_text, parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error sending text receipt: {e}")

            await status_msg.edit_text(
                f"✅ *Заказ иҷро шуд!* Донат ба аккаунти мизоҷ гузашт.\n`FireLoot ID: {fl_order_id}`",
                parse_mode="Markdown",
            )
            pending_orders.pop(customer_id, None)

        elif final_status == "refunded":
            try:
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=(
                        "⚠️ *Мутаассифона, донат иҷро нашуд.*\n"
                        "Маблағи шумо ба баланси мо баргардонида шуд.\n"
                        "Лутфан бо админ тамос гиред:\n`+992933313738`"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            await status_msg.edit_text(
                f"⚠️ Заказ ба ҳолати *refunded* гузашт.\n`FireLoot ID: {fl_order_id}`",
                parse_mode="Markdown",
            )
            pending_orders.pop(customer_id, None)

        elif final_status == "failed":
            try:
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=(
                        "❌ *Мутаассифона, донат иҷро нашуд.*\n"
                        "Лутфан бо админ тамос гиред:\n`+992933313738`"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            await status_msg.edit_text(
                f"❌ Заказ ба ҳолати *failed* гузашт.\n`FireLoot ID: {fl_order_id}`",
                parse_mode="Markdown",
            )
            pending_orders.pop(customer_id, None)

        else:
            await status_msg.edit_text(
                f"⚠️ *Фармоиш фиристода шуд, аммо статуси ниҳоӣ ҳанӯз муайян нашуд.*\n"
                f"`FireLoot ID: {fl_order_id}`\n\n"
                f"Лутфан вазъро дар панели FireLoot Partner санҷед.",
                parse_mode="Markdown",
            )
        return

    if data.startswith("reject_"):
        if user_id != ADMIN_TELEGRAM_ID:
            return
        customer_id = int(data.split("_")[1])
        try:
            await context.bot.send_message(
                chat_id=customer_id,
                text=(
                    "❌ *Чеки шумо тасдиқ нашуд.*\n\n"
                    "Эҳтимол чек нодуруст ё сохта аст.\n"
                    "Лутфан бо админ тамос гиред:\n"
                    "`+992933313738`\n"
                    "https://wa.me/992933313738"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Мизоҷ огоҳ шуд — чек рад шуд!")
        pending_orders.pop(customer_id, None)
        return

    # ===== МЕНЮ =====
    if data == "menu":
        user_data[user_id] = {}
        await query.edit_message_text(
            "Салом! 👋\n\nБа боти *ALMAZ TJ ⚡* хуш омадед.\nКатегорияро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(user_id),
        )

    elif data == "cat_ff":
        await query.edit_message_text(
            "🔥 *Free Fire*\n\nКатегорияро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=freefire_menu_keyboard(),
        )

    elif data == "cat_ff_id":
        await query.edit_message_text(
            "🇮🇩 *Free Fire Indonesia*\n\nКатегорияро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=freefire_id_menu_keyboard(),
        )

    elif data == "cat_almaz_id":
        await query.edit_message_text(
            "💎 *Алмазҳо — Free Fire Indonesia*\n\nМаҳсулотро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=almaz_id_keyboard(user_id),
        )

    elif data == "cat_member_id":
        await query.edit_message_text(
            "🎟 *Membership — Free Fire Indonesia*\n\nМаҳсулотро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=member_id_keyboard(user_id),
        )

    elif data == "cat_almaz":
        partner_note = ""
        if is_partner(user_id):
            bal = get_partner_balance(user_id)
            partner_note = f"\n🤝 *Шумо шарик ҳастед*\n💰 Баланс: *{fmt_price(bal)} сомонӣ*"
        await query.edit_message_text(
            f"💎 *Алмазҳо — Free Fire*{partner_note}\n\nМаҳсулотро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=almaz_keyboard(user_id),
        )

    elif data == "cat_vaucher":
        partner_note = ""
        if is_partner(user_id):
            bal = get_partner_balance(user_id)
            partner_note = f"\n🤝 *Шумо шарик ҳастед*\n💰 Баланс: *{fmt_price(bal)} сомонӣ*"
        await query.edit_message_text(
            f"🎟 *Ваучерҳо — Free Fire*{partner_note}\n\nМаҳсулотро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=vaucher_keyboard(user_id),
        )

    elif data == "cat_pubg":
        partner_note = ""
        if is_partner(user_id):
            bal = get_partner_balance(user_id)
            partner_note = f"\n🤝 *Шумо шарик ҳастед*\n💰 Баланс: *{fmt_price(bal)} сомонӣ*"
        await query.edit_message_text(
            f"🎮 *PUBG Mobile UC*{partner_note}\n\nПакетро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=pubg_keyboard(user_id),
        )

    elif data == "cat_stars":
        await query.edit_message_text(
            "⭐ *Telegram Stars*\n\nПакетро интихоб кунед:",
            parse_mode="Markdown",
            reply_markup=stars_keyboard(user_id),
        )

    elif data == "contact":
        await query.edit_message_text(
            "📞 *Тамос бо админ*\n\n`+992933313738`\n\nhttps://wa.me/992933313738",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")]]),
        )

    elif data in PACKAGES:
        pkg = PACKAGES[data]
        final_price = get_price_for_user(data, pkg["price"], user_id)
        user_data[user_id]["pkg_key"] = data
        user_data[user_id]["package"] = pkg["name"]
        user_data[user_id]["price"] = final_price
        user_data[user_id]["sku"] = pkg.get("sku")
        user_data[user_id]["game"] = pkg.get("game", "ff")
        user_data[user_id]["step"] = "get_id"
        if pkg.get("game") == "stars":
            user_data[user_id]["stars_amount"] = pkg.get("stars", 50)

        partner_text = ""
        if is_partner(user_id) and data in PARTNER_PRICES:
            bal = get_partner_balance(user_id)
            partner_text = f"\n🤝 Нархи шарик | 💰 Баланс: {fmt_price(bal)} сомонӣ"

        if pkg.get("game") == "stars":
            await query.edit_message_text(
                f"✅ Интихоб шуд: *{pkg['name']}*\n"
                f"💰 Нарх: *{fmt_price(final_price)} сомонӣ*{partner_text}\n\n"
                f"📝 *Кадами 1:* Username-и Telegram-ро нависед\n"
                f"Мисол: `@username` ё `username`",
                parse_mode="Markdown",
            )
        else:
            game_name = "PUBG Mobile" if pkg.get("game") == "pubg" else "Free Fire"
            await query.edit_message_text(
                f"✅ Интихоб шуд: *{pkg['name']}*\n"
                f"💰 Нарх: *{fmt_price(final_price)} сомонӣ*{partner_text}\n\n"
                f"📝 *Кадами 1:* ID-и {game_name}-ро нависед\n"
                f"Мисол: `5XXXXXXXXX` ё `10774369881`",
                parse_mode="Markdown",
            )

    # ===== БАЛАНСИ ШАРИК =====
    elif data == "partner_balance":
        if not is_partner(user_id):
            await query.answer("❌ Шумо шарик нестед!", show_alert=True)
            return
        bal = get_partner_balance(user_id)
        await query.edit_message_text(
            f"💰 *Баланси шумо:* `{fmt_price(bal)}` сомонӣ\n\n"
            f"Барои пур кардани баланс маблағро интихоб кунед ё худ нависед.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("50 с.", callback_data="topup_50"),
                 InlineKeyboardButton("100 с.", callback_data="topup_100"),
                 InlineKeyboardButton("200 с.", callback_data="topup_200")],
                [InlineKeyboardButton("500 с.", callback_data="topup_500"),
                 InlineKeyboardButton("1000 с.", callback_data="topup_1000")],
                [InlineKeyboardButton("✏️ Маблағи дигар", callback_data="topup_custom")],
                [InlineKeyboardButton("« Баргашт ба меню", callback_data="menu")],
            ]),
        )

    elif data == "topup_paid":
        if not is_partner(user_id):
            return
        amount = user_data[user_id].get("topup_amount", 0)
        order_id = user_data[user_id].get("order_id", "—")
        username = f"@{user.username}" if user.username else user.first_name
        pending_orders[user_id] = {
            "type": "topup",
            "topup_amount": amount,
            "order_id": order_id,
            "package": f"Пуркунии баланс {fmt_price(amount)} с.",
            "price": amount,
            "ff_id": "—",
            "nickname": "—",
            "sku": "",
            "game": "topup",
        }
        msg = (
            f"💰 ПУРКУНИИ БАЛАНСИ ШАРИК!\n\n"
            f"🧾 Заказ: {order_id}\n"
            f"💵 Маблағ: {fmt_price(amount)} сомонӣ\n"
            f"👤 Аз: {username}\n"
            f"🆔 ID TG: {user_id}"
        )
        await asyncio.to_thread(send_whatsapp, msg)
        try:
            await context.bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=msg,
                reply_markup=admin_topup_keyboard(user_id),
            )
        except Exception:
            pass
        user_data[user_id]["step"] = "wait_topup_cheque"
        await query.edit_message_text(
            "✅ Хуб аст!\n\nАкнун акси чекро фиристед.\nПас аз тасдиқи админ баланс пур мешавад.",
            parse_mode="Markdown",
        )

    elif data.startswith("topup_ok_"):
        if user_id != ADMIN_TELEGRAM_ID:
            return
        customer_id = int(data.split("_")[2])
        order_info = pending_orders.get(customer_id)
        if not order_info or order_info.get("type") != "topup":
            await query.message.reply_text("❌ Маълумоти пуркунӣ пайдо нашуд!")
            return
        amount = float(order_info.get("topup_amount", 0))
        if add_partner_balance(customer_id, amount):
            new_bal = get_partner_balance(customer_id)
            try:
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=(
                        f"✅ *Баланс пур шуд!*\n\n"
                        f"➕ Илова шуд: *{fmt_price(amount)}* сомонӣ\n"
                        f"💰 Баланси нав: *{fmt_price(new_bal)}* сомонӣ\n\n"
                        f"Акнун метавонед аз баланс харид кунед."
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            await query.message.reply_text(
                f"✅ Баланси шарик пур шуд.\nID: `{customer_id}` | +{fmt_price(amount)} → {fmt_price(new_bal)}",
                parse_mode="Markdown",
            )
            pending_orders.pop(customer_id, None)
            if customer_id in user_data:
                user_data[customer_id]["step"] = None
        else:
            await query.message.reply_text("❌ Хатогӣ ҳангоми пур кардани баланс.")

    elif data.startswith("topup_no_"):
        if user_id != ADMIN_TELEGRAM_ID:
            return
        customer_id = int(data.split("_")[2])
        try:
            await context.bot.send_message(
                chat_id=customer_id,
                text="❌ Чеки пуркунии баланс тасдиқ нашуд.\nЛутфан бо админ тамос гиред.",
            )
        except Exception:
            pass
        await query.message.reply_text("❌ Пуркунӣ рад шуд.")
        pending_orders.pop(customer_id, None)
        if customer_id in user_data:
            user_data[customer_id]["step"] = None

    # ===== Маблағи дигар (custom) =====
    elif data == "topup_custom":
        if not is_partner(user_id):
            await query.answer("❌ Шумо шарик нестед!", show_alert=True)
            return
        user_data[user_id]["step"] = "topup_amount"
        await query.edit_message_text(
            "✏️ Маблағи пуркуниро нависед (танҳо рақам):\nМисол: `150` ё `250.50`",
            parse_mode="Markdown",
        )

    # ===== Интихоби маблағи пуркунӣ (topup_50, topup_100, ...) =====
    elif data.startswith("topup_") and not data.startswith("topup_ok_") and not data.startswith("topup_no_") and data != "topup_paid":
        if not is_partner(user_id):
            await query.answer("❌ Шумо шарик нестед!", show_alert=True)
            return
        try:
            amount = float(data.replace("topup_", ""))
        except ValueError:
            await query.answer("Хатогӣ", show_alert=True)
            return
        order_id = gen_order_id()
        user_data[user_id]["topup_amount"] = amount
        user_data[user_id]["order_id"] = order_id
        user_data[user_id]["step"] = "wait_topup_cheque"
        await query.edit_message_text(
            f"💰 *Пуркунии баланс:* `{fmt_price(amount)}` сомонӣ\n"
            f"🧾 Заказ: `{order_id}`\n\n"
            f"Тугмаи *DC Pay* ё *Alif Mobi*-ро зер кунед.\n"
            f"Пас аз пардохт «✅ Ман пардохт кардам»-ро зер кунед ва акси чекро фиристед.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏦 DC Pay", url=dc_pay_url(amount, order_id)),
                 InlineKeyboardButton("📱 Alif Mobi", url=alif_url(amount))],
                [InlineKeyboardButton("✅ Ман пардохт кардам", callback_data="topup_paid")],
                [InlineKeyboardButton("« Баргашт", callback_data="partner_balance")],
            ]),
        )

    # ===== ПАРДОХТ АЗ БАЛАНС (авто) =====
    elif data == "pay_balance":
        if not is_partner(user_id):
            await query.answer("❌ Шумо шарик нестед!", show_alert=True)
            return
        price = float(user_data[user_id].get("price", 0))
        pkg_key = user_data[user_id].get("pkg_key", "")
        if pkg_key not in PARTNER_PRICES:
            await query.answer("❌ Ин пакет барои баланс дастнорас аст.", show_alert=True)
            return
        bal = get_partner_balance(user_id)
        if bal < price:
            await query.answer(f"❌ Баланс кофӣ нест! ({fmt_price(bal)} < {fmt_price(price)})", show_alert=True)
            return

        player_id = user_data[user_id].get("ff_id")
        sku = user_data[user_id].get("sku")
        nickname = user_data[user_id].get("nickname", "—")
        pkg_name = user_data[user_id].get("package", "—")
        order_id = user_data[user_id].get("order_id") or gen_order_id()
        game = user_data[user_id].get("game", "ff")
        date_str = datetime.now().strftime("%d.%m.%Y • %H:%M")

        # Аввал балансро кам мекунем
        if not deduct_partner_balance(user_id, price):
            await query.answer("❌ Баланс кофӣ нест!", show_alert=True)
            return

        status_msg = await query.edit_message_text(
            "⏳ Пардохт аз баланс... Донат фиристода мешавад...",
            parse_mode="Markdown",
        )

        # Фиристодани донат
        api_res = await asyncio.to_thread(send_fireloot_order, player_id, sku, order_id)
        if not api_res["success"]:
            # Баргардонидани баланс
            add_partner_balance(user_id, price)
            err = api_res.get("error", "номаълум")
            await status_msg.edit_text(
                f"❌ *Хатогӣ!*\nДонат гузаронида нашуд.\nСабаб: `{err}`\n\n"
                f"Баланс ба шумо баргардонида шуд.",
                parse_mode="Markdown",
            )
            return

        fl_order_id = api_res["data"].get("order_id", "—")
        final = await wait_for_order_completion(fl_order_id)
        if not final.get("success") or final.get("data", {}).get("status") not in ("completed", "failed", "refunded"):
            fallback = await asyncio.to_thread(get_order_status, order_id, True)
            if fallback.get("success"):
                final = fallback

        final_status = (final.get("data") or {}).get("status")
        new_bal = get_partner_balance(user_id)

        if final_status == "completed":
            receipt_text = (
                f"🧾 *ЧЕКИ ПАРДОХТ — ALMAZ TJ*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *Статус:* МУВАФФАҚ (аз баланс)\n"
                f"🔢 *Фармоиш №:* `#{order_id}` (FL: `{fl_order_id}`)\n"
                f"🎮 *ID:* `{player_id}`\n"
                f"👤 *Никнейм:* {nickname}\n"
                f"📦 *Пакет:* {pkg_name}\n"
                f"💰 *Маблағ:* {fmt_price(price)} сомонӣ\n"
                f"💰 *Баланси монда:* {fmt_price(new_bal)} сомонӣ\n"
                f"📅 *Сана:* {date_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎉 Хариди шумо муваффақона иҷро шуд!\n"
                f"Барои закази нав /start -ро пахш кунед."
            )
            try:
                await context.bot.send_message(chat_id=user_id, text=receipt_text, parse_mode="Markdown")
            except Exception:
                pass
            await status_msg.edit_text(
                f"✅ *Заказ иҷро шуд!* (аз баланс)\n"
                f"Баланси монда: `{fmt_price(new_bal)}` сомонӣ\n`FireLoot ID: {fl_order_id}`",
                parse_mode="Markdown",
            )
            # Огоҳии админ
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=(
                        f"✅ АВТО-ДОНАТ аз БАЛАНСИ ШАРИК!\n"
                        f"#{order_id} | {pkg_name} | {player_id}\n"
                        f"Маблағ: {fmt_price(price)} | Баланси монда: {fmt_price(new_bal)}"
                    ),
                )
            except Exception:
                pass
        else:
            # Агар failed — балансро баргардон
            add_partner_balance(user_id, price)
            await status_msg.edit_text(
                f"⚠️ Статус: `{final_status or 'номаълум'}`\nБаланс баргардонида шуд.\nЛутфан бо админ тамос гиред.",
                parse_mode="Markdown",
            )
        user_data[user_id] = {}
        return

    elif data == "paid":
        package = user_data[user_id].get("package", "—")
        player_id = user_data[user_id].get("ff_id", "—")
        nickname = user_data[user_id].get("nickname", "—")
        price = user_data[user_id].get("price", 0)
        order_id = user_data[user_id].get("order_id", "—")
        sku = user_data[user_id].get("sku", "diamonds_110")
        stars_amount = user_data[user_id].get("stars_amount")
        username = f"@{user.username}" if user.username else user.first_name

        pending_orders[user_id] = {
            "package": package,
            "ff_id": player_id,
            "nickname": nickname,
            "price": price,
            "order_id": order_id,
            "sku": sku,
            "stars_amount": stars_amount,
            "game": user_data[user_id].get("game", "ff"),
        }

        order_msg = (
            f"🔥 ЗАКАЗИ НАВ — ИНТИЗОРИ ПАРДОХТ (DC / чек)!\n\n"
            f"🧾 Заказ: {order_id}\n"
            f"📦 Пакет: {package}\n"
            f"💰 Сумма: {fmt_price(price)} сомонӣ\n"
            f"🎮 ID/User: {player_id}\n"
            f"👤 Никнейм: {nickname}\n"
            f"👤 Аз: {username}\n"
            f"🆔 ID TG: {user.id}"
        )
        await asyncio.to_thread(send_whatsapp, order_msg)
        try:
            await context.bot.send_message(chat_id=ADMIN_TELEGRAM_ID, text=order_msg)
        except Exception:
            pass

        user_data[user_id]["step"] = "wait_cheque"
        await query.edit_message_text(
            "✅ Хуб аст!\n\n"
            "Акнун пардохт кунед.\n\n"
            "⚡ *Ду роҳ:*\n"
            "1️⃣ Агар пул ба ҳисоби *DC* ояд — бот *худкор* донатро мефиристад\n"
            "2️⃣ Акси чекро ҳамин ҷо фиристед — админ тасдиқ мекунад\n\n"
            "Пас аз пардохт каме интизор шавед.",
            parse_mode="Markdown",
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    known_users.add(user_id)
    text = update.message.text.strip()

    if user_id != ADMIN_TELEGRAM_ID and not await is_subscribed(context, user_id):
        await send_subscribe_prompt(update)
        return

    if user_id not in user_data:
        user_data[user_id] = {}

    # ===== Пуркунии баланс (маблағи худӣ) =====
    if user_data[user_id].get("step") == "topup_amount":
        if not is_partner(user_id):
            user_data[user_id]["step"] = None
            await update.message.reply_text("❌ Шумо шарик нестед.")
            return
        try:
            amount = float(text.replace(",", ".").replace(" ", ""))
            if amount < 10 or amount > 10000:
                await update.message.reply_text("❌ Маблағ бояд аз 10 то 10000 сомонӣ бошад.")
                return
        except ValueError:
            await update.message.reply_text("❌ Танҳо рақам нависед.\nМисол: `150`")
            return
        order_id = gen_order_id()
        user_data[user_id]["topup_amount"] = amount
        user_data[user_id]["order_id"] = order_id
        user_data[user_id]["step"] = "wait_topup_cheque"
        await update.message.reply_text(
            f"💰 *Пуркунии баланс:* `{fmt_price(amount)}` сомонӣ\n"
            f"🧾 Заказ: `{order_id}`\n\n"
            f"Тугмаи *DC Pay* ё *Alif Mobi*-ро зер кунед.\n"
            f"Пас аз пардохт «✅ Ман пардохт кардам»-ро зер кунед ва акси чекро фиристед.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏦 DC Pay", url=dc_pay_url(amount, order_id)),
                 InlineKeyboardButton("📱 Alif Mobi", url=alif_url(amount))],
                [InlineKeyboardButton("✅ Ман пардохт кардам", callback_data="topup_paid")],
                [InlineKeyboardButton("« Баргашт", callback_data="partner_balance")],
            ]),
        )
        return

    if user_data[user_id].get("step") == "get_id":
        game = user_data[user_id].get("game", "ff")
        price = user_data[user_id].get("price", 0)
        order_id = gen_order_id()

        # ===== Telegram Stars: username қабул мекунем =====
        if game == "stars":
            username = text.lstrip("@").strip()
            if not username or len(username) < 3 or " " in username or not re.match(r"^[a-zA-Z0-9_]+$", username):
                await update.message.reply_text(
                    "❌ Username нодуруст аст.\n"
                    "Танҳо ҳарф, рақам ва `_` иҷозат аст.\n"
                    "Мисол: `@username` ё `username`",
                    parse_mode="Markdown",
                )
                return

            stars_amount = user_data[user_id].get("stars_amount", 50)
            loading_msg = await update.message.reply_text("⏳ Дар ҳоли тафтиши username...")

            try:
                is_valid, name_or_err, clean_username = await asyncio.to_thread(
                    check_telegram_user, username, stars_amount
                )
            except Exception:
                is_valid, name_or_err, clean_username = False, "Пайдо нашуд", username

            user_data[user_id]["ff_id"] = clean_username
            user_data[user_id]["nickname"] = name_or_err if is_valid else "Пайдо нашуд (дастӣ тафтиш мешавад)"
            user_data[user_id]["order_id"] = order_id
            user_data[user_id]["step"] = "wait_confirm"

            if is_valid:
                nick_text = f"👤 Ном: *{name_or_err}*\n"
            else:
                nick_text = f"⚠️ *Username автоматикӣ тафтиш нашуд ({name_or_err}), аммо қабул шуд.*\n"

            await loading_msg.edit_text(
                f"✅ *Telegram Username қабул шуд!*\n\n"
                f"👤 Username: `@{clean_username}`\n"
                f"{nick_text}"
                f"🧾 Заказ: `{order_id}`\n"
                f"⭐ Миқдор: *{stars_amount} Stars*\n"
                f"💰 Ба пардохт: *{fmt_price(price)} сомонӣ*\n\n"
                f"Тугмаи *DC Pay* ё *Alif Mobi* -ро зер кунед.\n"
                f"Пас аз пардохт «✅ Ман пардохт кардам» -ро зер кунед ва акси чекро фиристед.",
                parse_mode="Markdown",
                reply_markup=payment_keyboard(order_id, price, user_id, user_data[user_id].get("pkg_key", "")),
            )
            return

        # ===== Free Fire / PUBG: ID қабул мекунем =====
        if not text.isdigit() or len(text) < 8 or len(text) > 15:
            await update.message.reply_text(
                "❌ ID нодуруст аст. Танҳо рақамҳои 8–15 хонагиро нависед.\n"
                "Мисол: `5XXXXXXXXX` (PUBG) ё `10774369881` (Free Fire)",
                parse_mode="Markdown",
            )
            return

        player_id = text
        sku = user_data[user_id].get("sku", "diamonds_110")

        loading_msg = await update.message.reply_text("⏳ Дар ҳоли тафтиши ID...")

        try:
            is_valid, nick_res = await asyncio.to_thread(get_player_nickname, player_id, sku)
        except Exception:
            is_valid, nick_res = False, "Пайдо нашуд"

        user_data[user_id]["ff_id"] = player_id
        user_data[user_id]["nickname"] = nick_res if is_valid else "Пайдо нашуд (дастӣ тафтиш мешавад)"
        user_data[user_id]["order_id"] = order_id
        user_data[user_id]["step"] = "wait_confirm"

        game_label = "PUBG Mobile" if game == "pubg" else "Free Fire"

        if is_valid:
            nick_text = f"👤 Никнейм: *{nick_res}*\n"
        else:
            nick_text = f"⚠️ *Никнейм автоматикӣ пайдо нашуд ({nick_res}), аммо ID қабул шуд.*\n"

        await loading_msg.edit_text(
            f"✅ *{game_label} ID қабул шуд!*\n\n"
            f"🎮 ID: `{player_id}`\n"
            f"{nick_text}"
            f"🧾 Заказ: `{order_id}`\n"
            f"💰 Ба пардохт: *{fmt_price(price)} сомонӣ*\n\n"
            f"Тугмаи *DC Pay* ё *Alif Mobi* -ро зер кунед.\n"
            f"Пас аз пардохт «✅ Ман пардохт кардам» -ро зер кунед ва акси чекро фиристед.",
            parse_mode="Markdown",
            reply_markup=payment_keyboard(order_id, price, user_id, user_data[user_id].get("pkg_key", "")),
        )
    else:
        await update.message.reply_text(
            "Барои оғоз /start -ро пахш кунед.",
            reply_markup=main_menu_keyboard(user_id),
        )


def process_ocr(file_path: str) -> list:
    try:
        extracted_text = pytesseract.image_to_string(Image.open(file_path))
        return re.findall(r'\b\d{8,12}\b', extracted_text)
    except Exception as e:
        print(f"OCR Exception: {e}")
        return []


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    known_users.add(user_id)
    user = update.message.from_user

    # ===== Чеки пуркунии баланс =====
    if user_id in user_data and user_data[user_id].get("step") == "wait_topup_cheque":
        photo_file = await update.message.photo[-1].get_file()
        file_path = f"cheque_topup_{user_id}.jpg"
        await photo_file.download_to_drive(file_path)

        found_ids = await asyncio.to_thread(process_ocr, file_path)
        if found_ids:
            tx_id = found_ids[0]
            if is_tx_used(tx_id):
                await update.message.reply_text(
                    "❌ *Хатогӣ! Ин чек аллакай истифода шудааст.*",
                    parse_mode="Markdown",
                )
                if os.path.exists(file_path):
                    os.remove(file_path)
                return
            save_tx(tx_id)
        if os.path.exists(file_path):
            os.remove(file_path)

        amount = user_data[user_id].get("topup_amount", 0)
        order_id = user_data[user_id].get("order_id", "—")
        username = f"@{user.username}" if user.username else user.first_name

        pending_orders[user_id] = {
            "type": "topup",
            "topup_amount": amount,
            "order_id": order_id,
            "package": f"Пуркунии баланс {fmt_price(amount)} с.",
            "price": amount,
            "ff_id": "—",
            "nickname": "—",
            "sku": "",
            "game": "topup",
        }

        await update.message.reply_text(
            "✅ Чек қабул шуд!\n\nМо чекро месанҷем.\nПас аз тасдиқи админ баланс пур мешавад. ❤️"
        )

        receipt_msg = (
            f"💰 ЧЕКИ ПУРКУНИИ БАЛАНС!\n\n"
            f"🧾 Заказ: #{order_id}\n"
            f"💵 Маблағ: {fmt_price(amount)} сомонӣ\n"
            f"👤 Аз: {username}\n"
            f"🆔 Chat ID: {user_id}"
        )
        await asyncio.to_thread(send_whatsapp, receipt_msg)
        try:
            await context.bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=receipt_msg,
                reply_markup=admin_topup_keyboard(user_id),
            )
            await context.bot.forward_message(
                chat_id=ADMIN_TELEGRAM_ID,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            print(f"Error forwarding topup: {e}")
        return

    if user_id in user_data and user_data[user_id].get("step") == "wait_cheque":
        photo_file = await update.message.photo[-1].get_file()
        file_path = f"cheque_{user_id}.jpg"
        await photo_file.download_to_drive(file_path)

        found_ids = await asyncio.to_thread(process_ocr, file_path)

        if found_ids:
            tx_id = found_ids[0]
            if is_tx_used(tx_id):
                await update.message.reply_text(
                    "❌ *Хатогӣ! Ин чек аллакай дар бот истифода шудааст.*\n\n"
                    "Лутфан чеки аслии пардохти навбатиро фиристед.",
                    parse_mode="Markdown",
                )
                if os.path.exists(file_path):
                    os.remove(file_path)
                return
            save_tx(tx_id)

        if os.path.exists(file_path):
            os.remove(file_path)

        package = user_data[user_id].get("package", "—")
        player_id = user_data[user_id].get("ff_id", "—")
        nickname = user_data[user_id].get("nickname", "—")
        price = user_data[user_id].get("price", 0)
        order_id = user_data[user_id].get("order_id", "—")
        sku = user_data[user_id].get("sku", "diamonds_110")
        stars_amount = user_data[user_id].get("stars_amount")
        username = f"@{user.username}" if user.username else user.first_name

        pending_orders[user_id] = {
            "package": package,
            "ff_id": player_id,
            "nickname": nickname,
            "price": price,
            "order_id": order_id,
            "sku": sku,
            "stars_amount": stars_amount,
            "game": user_data[user_id].get("game", "ff"),
        }

        await update.message.reply_text(
            "✅ Чек қабул шуд!\n\n"
            "Мо ҳозир чекро месанҷем.\n"
            "Пас аз тасдиқи админ донат ба аккаунти шумо гузаронида мешавад. ❤️"
        )

        receipt_msg = (
            f"📸 ЧЕК ОМАД — ТАСДИҚИ ДАСТӢ ЛОЗИМ!\n\n"
            f"🧾 Заказ: #{order_id}\n"
            f"📦 Пакет: {package}\n"
            f"💰 Сумма: {fmt_price(price)} сомонӣ\n"
            f"🎮 ID: {player_id}\n"
            f"👤 Никнейм: {nickname}\n"
            f"👤 Аз: {username}\n"
            f"🆔 Chat ID: {update.message.chat_id}"
        )
        await asyncio.to_thread(send_whatsapp, receipt_msg)

        try:
            await context.bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=receipt_msg,
                reply_markup=admin_confirm_keyboard(user_id),
            )
            await context.bot.forward_message(
                chat_id=ADMIN_TELEGRAM_ID,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            print(f"Error forwarding: {e}")

        user_data[user_id]["step"] = None


async def findsku(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_TELEGRAM_ID:
        return

    query_text = " ".join(context.args).strip().lower()
    if not query_text:
        await update.message.reply_text(
            "Тарзи истифода:\n`/findsku 310`\n`/findsku weekly`\n`/findsku pubg`\n`/findsku uc`",
            parse_mode="Markdown",
        )
        return

    status = await update.message.reply_text("⏳ Дар ҳоли гирифтани каталоги FireLoot...")
    products = await asyncio.to_thread(fetch_fireloot_products)

    if not products:
        await status.edit_text("❌ Натавонистам каталоги FireLoot-ро гирам (токен/шабака).")
        return

    matches = [
        item for sku, item in products.items()
        if query_text in sku.lower() or query_text in str(item.get("name", "")).lower()
    ]

    if not matches:
        await status.edit_text(f"🔍 Ҳеҷ чиз бо «{query_text}» пайдо нашуд.")
        return

    matches = matches[:25]
    lines = [f"🔍 Натиҷаҳо барои «{query_text}» ({len(matches)} нишон дода мешавад):\n"]
    for item in matches:
        lines.append(
            f"• `{item.get('sku')}` — {item.get('name', '—')} "
            f"({item.get('category', '—')}) — ${item.get('price', '—')}"
        )

    await status.edit_text("\n".join(lines), parse_mode="Markdown")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_TELEGRAM_ID:
        return

    photo_file_id = None
    text = None

    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        text = caption.replace("/broadcast", "", 1).strip()
    elif update.message.reply_to_message and update.message.reply_to_message.photo:
        photo_file_id = update.message.reply_to_message.photo[-1].file_id
        text = " ".join(context.args) if context.args else (update.message.reply_to_message.caption or "")
    else:
        text = " ".join(context.args) if context.args else ""

    if not text and not photo_file_id:
        await update.message.reply_text(
            "Тарзи истифода:\n`/broadcast Матни хабар`\n\nЁ аксро фиристед ва дар caption нависед:\n`/broadcast Матни хабар`",
            parse_mode="Markdown",
        )
        return

    sent, failed = 0, 0
    status_msg = await update.message.reply_text(f"⏳ Фиристодан ба {len(known_users)} корбар оғоз шуд...")

    for uid in list(known_users):
        try:
            if photo_file_id:
                await context.bot.send_photo(chat_id=uid, photo=photo_file_id, caption=text or None, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(f"✅ Рассылка тамом шуд.\n\nФиристода шуд: {sent}\nХато: {failed}")


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_TELEGRAM_ID:
        return

    status = await update.message.reply_text("⏳ Дар ҳоли гирифтани баланс...")
    result = await asyncio.to_thread(get_fireloot_balance)

    if result.get("success"):
        stars_bal = result.get("stars_balance")
        stars_line = f"\n⭐ *Stars balance:* `{stars_bal}`" if stars_bal is not None else ""
        await status.edit_text(
            f"💰 *Баланси FireLoot Partner*\n\n"
            f"`{result.get('balance')}` {result.get('currency', 'USD')}"
            f"{stars_line}",
            parse_mode="Markdown",
        )
    else:
        await status.edit_text(f"❌ Хатогӣ: {result.get('error', 'номаълум')}")


# ===================== ШАРИКОН (PARTNER) =====================
async def partner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /partner @username  ё  /partner 123456789 """
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    args = context.args
    target_id = None
    username = ""

    # 1) Агар reply бошад
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        username = update.message.reply_to_message.from_user.username or ""

    # 2) Агар аргумент бошад
    if args:
        target = args[0].lstrip("@")
        if target.isdigit():
            target_id = int(target)
            username = username or ""
        else:
            # Username дода шудааст, аммо бе reply ID-ро намедонем
            if not target_id:
                await update.message.reply_text(
                    "⚠️ Барои илова кардан бо username, лутфан ба паёми он шахс **reply** кунед ва `/partner` нависед.\n"
                    "Ё ID-и рақамии ӯро нависед:\n`/partner 123456789`",
                    parse_mode="Markdown",
                )
                return

    if not target_id:
        await update.message.reply_text(
            "Тарзи истифода:\n"
            "`/partner 123456789`\n"
            "Ё ба паёми мизоҷ **reply** карда `/partner` нависед.",
            parse_mode="Markdown",
        )
        return

    if add_partner(target_id, username):
        await update.message.reply_text(
            f"✅ Шарик илова шуд!\n\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 Username: @{username or '—'}\n"
            f"💰 Ҳоло нархҳои махсуси шарик ва системаи баланс фаъол аст.",
            parse_mode="Markdown",
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "🤝 *Шумо ҳамчун Шарик қайд шудед!*\n\n"
                    "Акнун барои шумо:\n"
                    "• Нархҳои махсуси шарик\n"
                    "• Системаи баланс (пуркунӣ + харид бе интизорӣ)\n\n"
                    "Барои дидан /start -ро пахш кунед.\n"
                    "Тугмаи «💰 Баланс | Пур кардан»-ро мебинед."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Хатогӣ ҳангоми илова кардан.")


async def unpartner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /unpartner 123456789  ё reply """
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    target_id = None
    if context.args and context.args[0].isdigit():
        target_id = int(context.args[0])
    elif update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    else:
        await update.message.reply_text(
            "Тарзи истифода:\n`/unpartner 123456789`\nЁ ба паёми ӯ reply карда `/unpartner`",
            parse_mode="Markdown",
        )
        return

    if remove_partner(target_id):
        await update.message.reply_text(f"✅ Шарик нест карда шуд.\nID: `{target_id}`", parse_mode="Markdown")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="ℹ️ Статуси Шарикии шумо бекор карда шуд. Нархҳо ба ҳолати оддӣ баргаштанд.",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Ин ID дар рӯйхати шарикон нест.")


async def partners_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /partners — рӯйхати шарикон """
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    partners = list_partners()
    if not partners:
        await update.message.reply_text("📭 Ҳоло ягон шарик нест.")
        return

    lines = [f"🤝 *Рӯйхати шарикон* ({len(partners)} нафар):\n"]
    for row in partners:
        uid, uname, disc, bal, added = row
        uname_str = f"@{uname}" if uname else "—"
        bal_str = fmt_price(float(bal or 0))
        lines.append(f"• `{uid}` | {uname_str} | 💰 {bal_str} с. | {added}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def addbalance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /addbalance 123456789 100  — ба баланси шарик илова кардан """
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Тарзи истифода:\n`/addbalance 123456789 100`\n(ID ва маблағ)",
            parse_mode="Markdown",
        )
        return
    try:
        target_id = int(args[0])
        amount = float(args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ ID ва маблағро дуруст нависед.")
        return
    if not is_partner(target_id):
        await update.message.reply_text("❌ Ин ID шарик нест.")
        return
    if add_partner_balance(target_id, amount):
        new_bal = get_partner_balance(target_id)
        await update.message.reply_text(
            f"✅ Баланс илова шуд.\nID: `{target_id}`\n+{fmt_price(amount)} → *{fmt_price(new_bal)}* с.",
            parse_mode="Markdown",
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"💰 Ба баланси шумо *{fmt_price(amount)}* сомонӣ илова шуд.\nБаланси нав: *{fmt_price(new_bal)}* сомонӣ",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Хатогӣ.")


async def setbalance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /setbalance 123456789 0  — балансро ба рақами дақиқ гузоштан """
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Тарзи истифода:\n`/setbalance 123456789 0`\n(ID ва маблағи нав)",
            parse_mode="Markdown",
        )
        return
    try:
        target_id = int(args[0])
        amount = float(args[1].replace(",", "."))
        if amount < 0:
            await update.message.reply_text("❌ Маблағ наметавонад манфӣ бошад.")
            return
    except ValueError:
        await update.message.reply_text("❌ ID ва маблағро дуруст нависед.")
        return
    if not is_partner(target_id):
        await update.message.reply_text("❌ Ин ID шарик нест.")
        return
    old_bal = get_partner_balance(target_id)
    if set_partner_balance(target_id, amount):
        await update.message.reply_text(
            f"✅ Баланс тағйир дода шуд.\nID: `{target_id}`\n{fmt_price(old_bal)} → *{fmt_price(amount)}* с.",
            parse_mode="Markdown",
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"ℹ️ Баланси шумо тағйир дода шуд.\nБаланси нав: *{fmt_price(amount)}* сомонӣ",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Хатогӣ.")


# ===================== АВТО-ХОДАНДАН АЗ DC NEXT BOT =====================

def parse_dc_notification(text: str) -> dict | None:
    if not text:
        return None
    text_lower = text.lower()
    if "zachislenie" not in text_lower and "зачисление" not in text_lower:
        return None

    amount = None
    m_amount = re.search(r"(?:summa|zachislenie)\s+([\d.,]+)\s*tjs", text, re.IGNORECASE)
    if m_amount:
        amount = float(m_amount.group(1).replace(",", "."))

    kod = None
    m_kod = re.search(r"kod\s+(\d{8,15})", text, re.IGNORECASE)
    if m_kod:
        kod = m_kod.group(1)

    karta = None
    m_karta = re.search(r"karta\s+(\d{10,20})", text, re.IGNORECASE)
    if m_karta:
        karta = m_karta.group(1)

    if amount is None:
        return None

    return {
        "amount": amount,
        "kod": kod,
        "karta": karta,
        "raw": text,
    }


async def process_dc_payment(amount: float, kod: str | None, bot):
    if kod and is_tx_used(kod):
        print(f"⚠️ DC Kod {kod} аллакай истифода шудааст — рад шуд")
        try:
            await bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=f"⚠️ DC Kod `{kod}` аллакай истифода шудааст. Донат фиристода нашуд.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    if kod:
        save_tx(kod)

    matched_uid = None
    matched_order = None
    for uid, order in list(pending_orders.items()):
        order_price = float(order.get("price", 0))
        if abs(order_price - amount) < 0.06:
            matched_uid = uid
            matched_order = order
            break

    if not matched_order:
        try:
            await bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=(
                    f"📥 *DC Zachislenie омад, аммо заказ пайдо нашуд*\n\n"
                    f"💰 Маблағ: `{amount}` TJS\n"
                    f"🔢 Kod: `{kod or '—'}`\n\n"
                    f"Ҳеҷ закази кушода бо ин маблағ нест."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    player_id = matched_order["ff_id"]
    sku = matched_order["sku"]
    order_id = matched_order["order_id"]
    package = matched_order["package"]
    nickname = matched_order.get("nickname", "—")
    price = matched_order["price"]
    stars_amount = matched_order.get("stars_amount")
    game = matched_order.get("game", "ff")
    date_str = datetime.now().strftime("%d.%m.%Y • %H:%M")

    try:
        await bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID,
            text=(
                f"🤖 *АВТО-ДОНАТ аз DC оғоз шуд!*\n\n"
                f"💰 `{amount}` TJS | Kod: `{kod}`\n"
                f"🧾 Заказ: `#{order_id}`\n"
                f"📦 {package}\n"
                f"🎮 ID/User: `{player_id}`"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass

    # ===== Telegram Stars (авто аз DC) =====
    if game == "stars" or (sku and str(sku).startswith("stars_")):
        if not stars_amount:
            stars_amount = 50
        api_res = await asyncio.to_thread(
            send_telegram_stars_order, player_id, stars_amount, order_id
        )
        if not api_res["success"]:
            err = api_res.get("error", "номаълум")
            try:
                await bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=f"❌ АВТО-ДОНАТ Stars (DC) хатогӣ:\n`{err}`\nЗаказ #{order_id}",
                    parse_mode="Markdown",
                )
                await bot.send_message(
                    chat_id=matched_uid,
                    text=(
                        f"❌ Пардохт қабул шуд, аммо Stars иҷро нашуд.\n"
                        f"Сабаб: `{err}`\n"
                        f"Лутфан бо админ тамос гиред:\n`+992933313738`"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            return

        fl_order_id = api_res.get("data", {}).get("order_id") or api_res.get("data", {}).get("id") or "—"
        receipt_text = (
            f"🧾 *ЧЕКИ ПАРДОХТ — ALMAZ TJ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *Статус:* МУВАФФАҚ (авто аз DC)\n"
            f"🔢 *Фармоиш №:* `#{order_id}` (FL: `{fl_order_id}`)\n"
            f"👤 *Username:* `@{player_id}`\n"
            f"👤 *Ном:* {nickname}\n"
            f"📦 *Пакет:* {package}\n"
            f"⭐ *Миқдор:* {stars_amount} Stars\n"
            f"💰 *Маблағ:* {fmt_price(price)} сомонӣ\n"
            f"📅 *Сана:* {date_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 Stars ба аккаунти шумо гузашт!\n"
            f"Барои закази нав /start -ро пахш кунед."
        )
        try:
            await bot.send_message(chat_id=matched_uid, text=receipt_text, parse_mode="Markdown")
            await bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=f"✅ АВТО-ДОНАТ Stars (DC) МУВАФФАҚ!\n#{order_id} | {package} | @{player_id} | FL: {fl_order_id}",
            )
        except Exception:
            pass
        pending_orders.pop(matched_uid, None)
        if matched_uid in user_data:
            user_data[matched_uid]["step"] = None
        return

    # ===== Free Fire / PUBG =====
    api_res = await asyncio.to_thread(send_fireloot_order, player_id, sku, order_id)

    if not api_res["success"]:
        err = api_res.get("error", "номаълум")
        try:
            await bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=f"❌ АВТО-ДОНАТ (DC) хатогӣ:\n`{err}`\nЗаказ #{order_id}",
                parse_mode="Markdown",
            )
            await bot.send_message(
                chat_id=matched_uid,
                text=(
                    f"❌ Пардохт қабул шуд, аммо донат иҷро нашуд.\n"
                    f"Сабаб: `{err}`\n"
                    f"Лутфан бо админ тамос гиред:\n`+992933313738`"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    fl_order_id = api_res["data"].get("order_id", "—")
    final = await wait_for_order_completion(fl_order_id)
    if not final.get("success") or final.get("data", {}).get("status") not in ("completed", "failed", "refunded"):
        fallback = await asyncio.to_thread(get_order_status, order_id, True)
        if fallback.get("success"):
            final = fallback

    final_status = (final.get("data") or {}).get("status")
    date_str = datetime.now().strftime("%d.%m.%Y • %H:%M")

    if final_status == "completed":
        receipt_text = (
            f"🧾 *ЧЕКИ ПАРДОХТ — ALMAZ TJ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *Статус:* МУВАФФАҚ (авто аз DC)\n"
            f"🔢 *Фармоиш №:* `#{order_id}` (FL: `{fl_order_id}`)\n"
            f"🎮 *ID:* `{player_id}`\n"
            f"👤 *Никнейм:* {nickname}\n"
            f"📦 *Пакет:* {package}\n"
            f"💰 *Маблағ:* {fmt_price(price)} сомонӣ\n"
            f"📅 *Сана:* {date_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 Хариди шумо муваффақона иҷро шуд!\n"
            f"Барои закази нав /start -ро пахш кунед."
        )
        try:
            await bot.send_message(chat_id=matched_uid, text=receipt_text, parse_mode="Markdown")
            await bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=f"✅ АВТО-ДОНАТ (DC) МУВАФФАҚ!\n#{order_id} | {package} | {player_id} | FL: {fl_order_id}",
            )
        except Exception:
            pass
        pending_orders.pop(matched_uid, None)
        if matched_uid in user_data:
            user_data[matched_uid]["step"] = None
    else:
        try:
            await bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=f"⚠️ АВТО-ДОНАТ (DC) статус: `{final_status}`\n#{order_id} | FL: {fl_order_id}",
                parse_mode="Markdown",
            )
            await bot.send_message(
                chat_id=matched_uid,
                text=(
                    f"⚠️ Пардохт қабул шуд, аммо статуси донат: `{final_status or 'номаълум'}`.\n"
                    f"Лутфан бо админ тамос гиред:\n`+992933313738`"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def start_dc_listener(application: Application):
    if not TELETHON_ENABLED:
        print("ℹ️ Telethon хомӯш аст (TELETHON_ENABLED=False). Авто-DC кор намекунад.")
        return
    if not TELETHON_AVAILABLE:
        print("⚠️ telethon насб нашудааст — авто-хондани DC хомӯш аст.")
        return

    session_path = TELETHON_SESSION + ".session"
    session_string = os.getenv("TELETHON_SESSION_STRING", "")

    if not session_string and not os.path.exists(session_path):
        print("⚠️ Telethon session нест. Авто-хондани DC хомӯш аст.")
        return

    try:
        if session_string:
            from telethon.sessions import StringSession
            client = TelegramClient(
                StringSession(session_string),
                API_ID,
                API_HASH,
                connection=ConnectionTcpObfuscated,
                connection_retries=None,
                retry_delay=5,
            )
        else:
            client = TelegramClient(
                TELETHON_SESSION,
                API_ID,
                API_HASH,
                connection=ConnectionTcpObfuscated,
                connection_retries=None,
                retry_delay=5,
            )

        @client.on(events.NewMessage)
        async def dc_handler(event):
            try:
                text = event.message.message or ""
                parsed = parse_dc_notification(text)
                if not parsed:
                    return

                sender = await event.get_sender()
                sender_username = (getattr(sender, "username", "") or "").lower()
                if DC_BOT_USERNAME and sender_username and DC_BOT_USERNAME.lower() not in sender_username:
                    if not event.is_private:
                        return

                print(f"📥 DC Zachislenie: {parsed['amount']} TJS | Kod: {parsed.get('kod')}")
                await process_dc_payment(parsed["amount"], parsed.get("kod"), application.bot)
            except Exception as e:
                print(f"DC listener error: {e}")

        await client.connect()
        if not await client.is_user_authorized():
            print("⚠️ Telethon session ваколат надорад. Авто-DC хомӯш аст.")
            await client.disconnect()
            return

        print("✅ Telethon DC listener фаъол шуд.")
        application.bot_data["dc_client"] = client

        async def keep_alive():
            try:
                await client.run_until_disconnected()
            except Exception as e:
                print(f"Telethon keep_alive анҷом ёфт: {e}")

        try:
            application.create_task(keep_alive())
        except Exception:
            asyncio.get_event_loop().create_task(keep_alive())

    except Exception as e:
        print(f"⚠️ Telethon оғоз нашуд (боти асосӣ кор мекунад): {e}")


def main():
    validate_packages_against_fireloot()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("findsku", findsku))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("partner", partner_cmd))
    application.add_handler(CommandHandler("unpartner", unpartner_cmd))
    application.add_handler(CommandHandler("partners", partners_cmd))
    application.add_handler(CommandHandler("addbalance", addbalance_cmd))
    application.add_handler(CommandHandler("setbalance", setbalance_cmd))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    async def post_init(app: Application):
        # Тоза кардани webhook — то хатои Conflict наояд
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook тоза шуд (агар буд).")
        await start_dc_listener(app)

    application.post_init = post_init

    print("🤖 Бот фаъол шуд (Free Fire + PUBG UC)...")
    if TELETHON_ENABLED:
        print("📡 Авто-хондани DC фаъол аст...")
    else:
        print("ℹ️ Авто-DC хомӯш аст. Танҳо акси чек + тасдиқи админ кор мекунад.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
