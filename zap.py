#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚡ ZAP PAPA — Telegram Search Bot

import os
import re
import time
import html
import hashlib
import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

import httpx
from pymongo import MongoClient, ASCENDING, DESCENDING
import logging
import requests

# 1. Logging Setup (Termux terminal format)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def start_bot():
    # Bot Startup Messages
    logging.info("✅ MongoDB connected successfully.")
    logging.info("🔮 ZAP PAPA bot running (MongoDB fallback to file storage).")
    logging.info("Application started")

def process_query(query_data):
    """
    API Call Function - Process query without logging response data
    """
    # Apne API ka actual URL yahan daalein
    api_url = "https://example.com/api" 
    payload = {"query": query_data}
    
    try:
        response = requests.post(api_url, json=payload)
        
        # SIRF HTTP Status Code log hoga (Data/Result terminal me show NAHI hoga)
        logging.info(f"API HTTP Status: {response.status_code}")
        
        if response.status_code == 200:
            result_data = response.json()
            # Bot functions me result ko internal return karein, print/log mat karein
            return result_data
        else:
            return None

    except Exception as e:
        logging.error(f"Request failed: {e}")
        return None

if __name__ == "__main__":
    start_bot()
    
    # Aapka main bot logic / polling yahan aayega
    # Example: bot.polling() ya main execution loop
    
# === TERMUX DNS FIX FOR PYMONGO SRV LOOKUP ===
import dns.resolver
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
# =============================================

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters,
)

# ============================ CONFIG ============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8800707730:AAE_m0fZt_wPDZIlie9FxmTtG9dmayehSXI").strip()
API_URL   = os.getenv("API_URL", "https://leak-osint.noobster.workers.dev/?query=").strip()
API_KEY   = os.getenv("API_KEY", "").strip()
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://zap3x:Blitzz@cluster0.yfpifje.mongodb.net/?appName=Cluster0"
).strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "6325764594").replace(" ", "").split(",") if x}
HASH_SALT = os.getenv("HASH_SALT", "zap-papa-salt-v1")

API_TIMEOUT   = 25
RATE_LIMIT    = 5
RATE_WINDOW   = 60
LOG_LIMIT     = 15

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
log = logging.getLogger("zap_papa")

# ============================ MONGODB ============================

mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
db = mongo["zap_papa_bot"]
users_col = db["users"]
logs_col  = db["search_logs"]

users_col.create_index([("user_id", ASCENDING)], unique=True)
users_col.create_index([("joined_at", DESCENDING)])
logs_col.create_index([("user_id", ASCENDING), ("timestamp", DESCENDING)])
logs_col.create_index([("timestamp", DESCENDING)])

# ============================ HELPERS ============================

_rate_map: dict[int, deque] = defaultdict(deque)

def rate_ok(uid: int) -> bool:
    if uid in ADMIN_IDS:
        return True
    now = time.time()
    dq = _rate_map[uid]
    while dq and now - dq[0] > RATE_WINDOW:
        dq.popleft()
    if len(dq) >= RATE_LIMIT:
        return False
    dq.append(now)
    return True

def hash_id(value: str) -> str:
    return hashlib.sha256(f"{HASH_SALT}:{value}".encode()).hexdigest()

def flatten(v) -> str:
    if isinstance(v, (dict, list)):
        return ", ".join(str(x) for x in v) if isinstance(v, list) else "•"
    return str(v).strip()

def scrub_credit(v: str) -> str:
    low = v.lower()
    if any(x in low for x in ["noob", "@noob", "t.me/noob", "nightmare"]):
        return "ZAP PAPA"
    return v

async def send_long_message(update: Update, text: str, reply_markup=None):
    """Chunking engine jo Telegram ki 4096 character limit cross kiye bina A to Z reply bhejta hai"""
    CHUNK_SIZE = 3800
    lines = text.split("\n")
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 > CHUNK_SIZE:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        msg_text = f"<pre>{html.escape(chunk.strip())}</pre>"
        if update.effective_chat:
            await update.effective_chat.send_message(msg_text, parse_mode=ParseMode.HTML, reply_markup=markup)
        elif update.message:
            await update.message.reply_text(msg_text, parse_mode=ParseMode.HTML, reply_markup=markup)

# ============================ API PARSER (UNIVERSAL) ============================

async def call_api(value: str):
    url = API_URL + value if API_URL.endswith("?query=") else API_URL + value
    headers = {"Accept": "application/json", "User-Agent": "ZAP-PAPA-BOT/1.0"}
    if API_KEY: headers["X-API-Key"] = API_KEY
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        elapsed = time.perf_counter() - started
        log.info(f"API HTTP Status: {resp.status_code} | Sample Response: {resp.text[:300]}")
        if resp.status_code != 200: return None, resp.status_code, elapsed
        return resp.json(), resp.status_code, elapsed
    except Exception as e:
        log.error(f"API Call failed: {e}")
        return None, 0, time.perf_counter() - started

def parse_nested_api_response(payload) -> list[dict]:
    """Universal parser jo JSON ke sabhi nested records extract karta hai"""
    all_records = []
    
    if not payload:
        return all_records

    def extract(node, default_src="ZAP PAPA Database"):
        if isinstance(node, list):
            for item in node:
                extract(item, default_src)
        elif isinstance(node, dict):
            src = node.get("source", node.get("database", default_src))
            
            if "records" in node and isinstance(node["records"], list):
                for r in node["records"]:
                    if isinstance(r, dict):
                        r_copy = dict(r)
                        r_copy["_source_db"] = src
                        all_records.append(r_copy)
            elif any(k in node for k in ["name", "phone", "mobile", "email", "address", "document_number", "father"]):
                r_copy = dict(node)
                if "_source_db" not in r_copy:
                    r_copy["_source_db"] = src
                all_records.append(r_copy)
            else:
                for key in ["result", "results", "data", "records", "response"]:
                    if key in node:
                        extract(node[key], src)

    extract(payload)
    return all_records

FIELD_MAP = [
    ({"document_number", "aadhaar", "aadhar", "uid"}, "🆔", "Document", None),
    ({"phone", "mobile", "msisdn"}, "📱", "Mobile", None),
    ({"email", "mail"}, "📧", "Email", None),
    ({"ip"}, "🌐", "IP", None),
    ({"encrypted_password", "password"}, "🔒", "Secret", None),
    ({"full_name", "name", "surname"}, "👤", "Name", None),
    ({"the_name_of_the_father", "father"}, "👨", "Father", None),
    ({"address"}, "🏠", "Address", None),
    ({"region", "state"}, "🌐", "Region", None),
    ({"city", "district"}, "🏙", "City", None),
    ({"the_date_of_registration", "dob"}, "📅", "Date/Reg", None),
    ({"gender"}, "🚻", "Gender", None),
    ({"currency", "sum", "country"}, "💳", "Details", None),
]

def format_record(rec: dict) -> list[str]:
    lines = []
    src = rec.get("_source_db", "")
    if src: lines.append(f"│ 📁 Database : {scrub_credit(src)}")
    used = {"_source_db"}
    lower = {k.lower().strip(): k for k in rec}
    
    for kws, emoji, label, masker in FIELD_MAP:
        for lk, orig in lower.items():
            if orig in used: continue
            if any(kw in lk for kw in kws):
                raw = rec[orig]
                if raw in (None, "", "-", "N/A", "null"): continue
                val = scrub_credit(flatten(raw))
                lines.append(f"│ {emoji} {label:<10}: {val}")
                used.add(orig)
                break

    for orig, lk in lower.items():
        if orig in used: continue
        raw = rec[orig]
        if raw in (None, "", "-", "N/A", "null"): continue
        clean_key = lk.replace("the_", "").replace("_", " ").title()[:10]
        lines.append(f"│ 🔹 {clean_key:<10}: {scrub_credit(flatten(raw))}")

    return lines or ["│ ⚠️ No displayable fields"]

def build_card(records: list[dict], elapsed: float, ok: bool, total: int) -> str:
    W = 32
    out = ["📊 ZAP PAPA SEARCH RESULT", ""]
    for i, rec in enumerate(records, 1):
        title = f"🪪 RECORD #{i}" if len(records) > 1 else "🪪 RECORD INFORMATION"
        out += ["┌" + "─" * W, f"│ {title}", "│", *format_record(rec), "├" + "─" * W]
        out.append("")
    out += [
        f"│ 📊 TOTAL FOUND : {total}", f"│ ⚡ RESPONSE    : {elapsed:.2f}s",
        "│ 🟢 API STATUS  : Active" if ok else "│ 🔴 API STATUS  : Failed", "└" + "─" * W,
        "\n👑 Powered By: ZAP PAPA"
    ]
    return "\n".join(out)

def log_search(uid: int, username: str, first_name: str, stype: str,
               query_val: str, hashed: str, status: str, rtime: float) -> None:
    try:
        logs_col.insert_one({
            "user_id": uid, "username": username or "", "first_name": first_name or "",
            "search_type": stype, "query": query_val, "query_hash": hashed,
            "timestamp": datetime.now(timezone.utc),
            "api_status": status, "response_time": round(rtime, 2),
        })
    except Exception as e: log.error("log write failed: %s", type(e).__name__)

# ============================ KEYBOARDS (REPLY FORMAT) ============================

def main_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    keys = [
        [KeyboardButton("📱 Phone Search"), KeyboardButton("🪪 Aadhaar Search")],
        [KeyboardButton("📧 Email Search")]
    ]
    if is_admin: keys.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

ADMIN_KB = ReplyKeyboardMarkup([
    [KeyboardButton("👥 Users"), KeyboardButton("📊 Statistics")],
    [KeyboardButton("🔎 Search Logs"), KeyboardButton("📢 Send Zap")],
    [KeyboardButton("🏠 Main Menu")]
], resize_keyboard=True)

BACK_KB = ReplyKeyboardMarkup([[KeyboardButton("⬅️ Back")]], resize_keyboard=True)
MENU_KB = ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
CANCEL_KB = ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
ZAP_CONFIRM_KB = ReplyKeyboardMarkup([[KeyboardButton("✅ Broadcast Now"), KeyboardButton("❌ Cancel")]], resize_keyboard=True)

def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS

# ============================ HANDLERS ============================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    try:
        users_col.update_one(
            {"user_id": u.id},
            {"$set": {"username": u.username or "", "first_name": u.first_name or "", "last_active": datetime.now(timezone.utc)},
             "$setOnInsert": {"joined_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception: pass

    admin = is_admin(update)
    text = (
        "⚡ <b>ZAP PAPA SEARCH BOT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Welcome, <b>{html.escape(u.first_name or 'User')}</b>!\n\n"
        "⚡ Choose a search method below:\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_kb(admin))

# ============================ EMAIL SEARCH ============================

EMAIL_WAIT = 1

async def cb_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📧 <b>Email Search</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "Enter the email address to search:\n"
        "<i>Example: user@domain.com</i>",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB
    )
    return EMAIL_WAIT

async def email_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip().lower()
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", raw):
        await update.message.reply_text("⚠️ <b>Invalid Email.</b> Please enter a valid email address.", parse_mode=ParseMode.HTML)
        return EMAIL_WAIT

    uid = update.effective_user.id
    if not rate_ok(uid):
        await update.message.reply_text("🚦 <b>Rate limit exceeded!</b> Please wait a minute.", parse_mode=ParseMode.HTML, reply_markup=MENU_KB)
        return ConversationHandler.END

    hashed = hash_id(raw)
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    payload, status, elapsed = await call_api(raw)
    records = parse_nested_api_response(payload) if payload else []
    api_status = "success" if records else ("empty" if payload is not None else "failed")

    await asyncio.to_thread(log_search, uid, update.effective_user.username, update.effective_user.first_name, "email", raw, hashed, api_status, elapsed)

    if records:
        card = build_card(records, elapsed, True, len(records))
    else:
        card = ("📊 ZAP PAPA SEARCH RESULT\n\n┌" + "─" * 32 + f"\n│ 🟡 NO RECORDS FOUND\n│ 📧 Query: {raw}\n├" + "─" * 32 + f"\n│ ⚡ Response: {elapsed:.2f}s\n└" + "─" * 32 + "\n\n👑 Powered By: ZAP PAPA")

    await send_long_message(update, card, reply_markup=MENU_KB)
    return ConversationHandler.END

# ============================ PHONE SEARCH ============================

PHONE_WAIT = 1

async def cb_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📱 <b>Phone Search</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "Enter 10-digit mobile number:\n<i>(Country code 91 will be added automatically)</i>\n\n"
        "<i>Example: 9876543210</i>",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB
    )
    return PHONE_WAIT

async def phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    if not re.fullmatch(r"\d{10}", raw):
        await update.message.reply_text("⚠️ <b>Invalid Input.</b> Please enter exactly 10 digits.", parse_mode=ParseMode.HTML)
        return PHONE_WAIT

    uid = update.effective_user.id
    if not rate_ok(uid):
        await update.message.reply_text("🚦 <b>Rate limit exceeded!</b> Please wait a minute.", parse_mode=ParseMode.HTML, reply_markup=MENU_KB)
        return ConversationHandler.END

    normalized = "91" + raw
    hashed = hash_id(normalized)
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    payload, status, elapsed = await call_api(normalized)
    records = parse_nested_api_response(payload) if payload else []
    
    if not records and payload is not None:
        payload_alt, status_alt, elapsed_alt = await call_api(raw)
        alt_recs = parse_nested_api_response(payload_alt) if payload_alt else []
        if alt_recs:
            records = alt_recs
            normalized = raw

    api_status = "success" if records else ("empty" if payload is not None else "failed")
    await asyncio.to_thread(log_search, uid, update.effective_user.username, update.effective_user.first_name, "phone", normalized, hashed, api_status, elapsed)

    if records:
        card = build_card(records, elapsed, True, len(records))
    else:
        card = ("📊 ZAP PAPA SEARCH RESULT\n\n┌" + "─" * 32 + f"\n│ 🟡 NO RECORDS FOUND\n│ 📱 Query: {normalized}\n├" + "─" * 32 + f"\n│ ⚡ Response: {elapsed:.2f}s\n└" + "─" * 32 + "\n\n👑 Powered By: ZAP PAPA")

    await send_long_message(update, card, reply_markup=MENU_KB)
    return ConversationHandler.END

# ============================ AADHAAR SEARCH ============================

AADHAAR_WAIT = 0

async def cb_aadhaar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🪪 <b>Aadhaar Search</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "Enter 12-digit Aadhaar number:\n<i>Example: 000000000000</i>",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB
    )
    return AADHAAR_WAIT

async def aadhaar_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip().replace(" ", "")
    if not re.fullmatch(r"\d{12}", raw):
        await update.message.reply_text("⚠️ <b>Invalid Input.</b> Please enter exactly 12 digits for Aadhaar.", parse_mode=ParseMode.HTML)
        return AADHAAR_WAIT

    try: await update.message.delete()
    except TelegramError: pass

    uid = update.effective_user.id
    if not rate_ok(uid):
        await update.effective_chat.send_message("🚦 <b>Rate limit exceeded!</b> Please wait a minute.", parse_mode=ParseMode.HTML, reply_markup=MENU_KB)
        return ConversationHandler.END

    hashed = hash_id(raw)
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    payload, status, elapsed = await call_api(raw)
    records = parse_nested_api_response(payload) if payload else []
    api_status = "success" if records else ("empty" if payload is not None else "failed")

    await asyncio.to_thread(log_search, uid, update.effective_user.username, update.effective_user.first_name, "aadhaar", raw, hashed, api_status, elapsed)

    if records:
        card = build_card(records, elapsed, True, len(records))
    else:
        card = ("📊 ZAP PAPA SEARCH RESULT\n\n┌" + "─" * 32 + f"\n│ 🟡 NO RECORDS FOUND\n│ 🆔 Document: {raw}\n├" + "─" * 32 + f"\n│ ⚡ Response: {elapsed:.2f}s\n└" + "─" * 32 + "\n\n👑 Powered By: ZAP PAPA")

    await send_long_message(update, card, reply_markup=MENU_KB)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ <b>Action Cancelled.</b>", parse_mode=ParseMode.HTML, reply_markup=main_kb(is_admin(update)))
    return ConversationHandler.END

# ============================ ADMIN PANEL & LOGS ============================

async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update): return
    await update.message.reply_text("👑 <b>ZAP PAPA ADMIN PANEL</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect an option:", parse_mode=ParseMode.HTML, reply_markup=ADMIN_KB)

async def cb_admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update): return
    total = await asyncio.to_thread(users_col.count_documents, {})
    recent = await asyncio.to_thread(lambda: list(users_col.find({}, {"_id": 0}).sort("joined_at", -1).limit(10)))
    lines = [f"👥 <b>TOTAL USERS: {total}</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for u in recent:
        uname = f"@{u.get('username')}" if u.get("username") else "—"
        lines.append(f"🆔 <code>{u['user_id']}</code> | {uname} | {html.escape((u.get('first_name') or '')[:15])}")
    await update.message.reply_text("\n".join(lines)[:4000], parse_mode=ParseMode.HTML, reply_markup=BACK_KB)

async def cb_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update): return
    users = await asyncio.to_thread(users_col.count_documents, {})
    total = await asyncio.to_thread(logs_col.count_documents, {})
    phone = await asyncio.to_thread(logs_col.count_documents, {"search_type": "phone"})
    aadhaar = await asyncio.to_thread(logs_col.count_documents, {"search_type": "aadhaar"})
    email = await asyncio.to_thread(logs_col.count_documents, {"search_type": "email"})
    text = (f"📊 <b>BOT STATISTICS</b>\n━━━━━━━━━━━━━━━━━━━━\n👥 Total Users: <b>{users}</b>\n🔎 Total Searches: <b>{total}</b>\n📱 Phone Searches: <b>{phone}</b>\n🪪 Aadhaar Searches: <b>{aadhaar}</b>\n📧 Email Searches: <b>{email}</b>\n")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=BACK_KB)

async def cb_admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update): return
    rows = await asyncio.to_thread(lambda: list(logs_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(LOG_LIMIT)))
    lines = ["🔎 <b>RECENT SEARCH LOGS</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for r in rows:
        who = f"@{r.get('username')}" if r.get("username") else (r.get("first_name") or "—")
        ts = r.get("timestamp")
        ts_s = ts.strftime("%d %b %H:%M UTC") if isinstance(ts, datetime) else "—"
        lines.append(
            f"👤 <b>{html.escape(str(who))}</b> (<code>{r.get('user_id')}</code>)\n"
            f"   Type: <b>{r.get('search_type', '').title()}</b> | Query: <code>{html.escape(str(r.get('query', '—')))}</code>\n"
            f"   Time: {ts_s} | Status: <b>{r.get('api_status')}</b>\n"
        )
    if not rows: lines.append("<i>No logs available yet.</i>")
    await update.message.reply_text("\n".join(lines)[:4000], parse_mode=ParseMode.HTML, reply_markup=BACK_KB)

# ============================ /zap BROADCAST ============================

ZAP_WAIT, ZAP_CONFIRM = 0, 1

async def cb_admin_zap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END
    await update.message.reply_text(
        "📢 <b>Zap Broadcast Mode</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send the message (Text/Photo/Caption) you want to broadcast to all users.",
        parse_mode=ParseMode.HTML, reply_markup=CANCEL_KB
    )
    return ZAP_WAIT

async def zap_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["zap_msg"] = update.message
    await update.message.reply_text("⚠️ <b>Confirm Broadcast</b>\nSend this message to all registered users?", parse_mode=ParseMode.HTML, reply_markup=ZAP_CONFIRM_KB)
    return ZAP_CONFIRM

async def zap_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END
    text = update.message.text
    if text == "❌ Cancel":
        await update.message.reply_text("❌ Broadcast cancelled.", reply_markup=ADMIN_KB)
        return ConversationHandler.END

    src = context.user_data.get("zap_msg")
    msg = await update.message.reply_text("📢 <b>Broadcasting message...</b>", parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
    sent = failed = 0
    for u in users_col.find({}, {"user_id": 1}):
        try:
            await context.bot.copy_message(chat_id=u["user_id"], from_chat_id=src.chat_id, message_id=src.message_id)
            sent += 1
        except Exception: failed += 1
        await asyncio.sleep(0.04)

    await msg.edit_text(f"📢 <b>Zap Completed!</b>\n\n✅ Sent: <b>{sent}</b>\n❌ Failed: <b>{failed}</b>", parse_mode=ParseMode.HTML)
    await update.message.reply_text("Returning to Admin Panel...", reply_markup=ADMIN_KB)
    return ConversationHandler.END

# ============================ MAIN ============================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Error encountered: %s", type(context.error).__name__)

def main() -> None:
    if not BOT_TOKEN: raise SystemExit("BOT_TOKEN missing!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_error_handler(on_error)

    # Conversations
    phone_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📱 Phone Search$"), cb_phone)],
        states={PHONE_WAIT: [MessageHandler(filters.TEXT & ~filters.Regex(r"^❌ Cancel$") & ~filters.COMMAND, phone_input)]},
        fallbacks=[MessageHandler(filters.Regex(r"^❌ Cancel$") | filters.Command("cancel"), cancel)],
    )
    aadhaar_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🪪 Aadhaar Search$"), cb_aadhaar)],
        states={AADHAAR_WAIT: [MessageHandler(filters.TEXT & ~filters.Regex(r"^❌ Cancel$") & ~filters.COMMAND, aadhaar_input)]},
        fallbacks=[MessageHandler(filters.Regex(r"^❌ Cancel$") | filters.Command("cancel"), cancel)],
    )
    email_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📧 Email Search$"), cb_email)],
        states={EMAIL_WAIT: [MessageHandler(filters.TEXT & ~filters.Regex(r"^❌ Cancel$") & ~filters.COMMAND, email_input)]},
        fallbacks=[MessageHandler(filters.Regex(r"^❌ Cancel$") | filters.Command("cancel"), cancel)],
    )
    zap_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📢 Send Zap$"), cb_admin_zap), CommandHandler("zap", cb_admin_zap)],
        states={
            ZAP_WAIT: [MessageHandler(filters.ALL & ~filters.Regex(r"^❌ Cancel$") & ~filters.COMMAND, zap_message)],
            ZAP_CONFIRM: [MessageHandler(filters.Regex(r"^(✅ Broadcast Now|❌ Cancel)$"), zap_confirm)],
        },
        fallbacks=[MessageHandler(filters.Regex(r"^❌ Cancel$") | filters.Command("cancel"), cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(zap_conv)
    app.add_handler(phone_conv)
    app.add_handler(aadhaar_conv)
    app.add_handler(email_conv)
    
    # Standard Handlers
    app.add_handler(MessageHandler(filters.Regex(r"^🏠 Main Menu|⬅️ Back$"), cmd_start))
    app.add_handler(MessageHandler(filters.Regex(r"^👑 Admin Panel$"), cb_admin_panel))
    app.add_handler(MessageHandler(filters.Regex(r"^👥 Users$"), cb_admin_users))
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Statistics$"), cb_admin_stats))
    app.add_handler(MessageHandler(filters.Regex(r"^🔎 Search Logs$"), cb_admin_logs))

    log.info("⚡ ZAP PAPA bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
