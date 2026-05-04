import telebot
import subprocess
import threading
import hashlib
import hmac
import os
import re
import json
import datetime
import google.generativeai as genai
from keep_alive import keep_alive

# ── Configuration ────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DAILY_SECRET = os.environ.get("DAILY_KEY_SECRET", "change-me-in-production")
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "")
ADMIN_IDS    = {5961723105}
USERS_FILE   = "verified_users.json"

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

bot = telebot.TeleBot(BOT_TOKEN)

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
else:
    gemini_model = None

# ── Persistent Verified Users ─────────────────────────────────────────────────
def load_verified_users() -> set[int]:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_verified_users(users: set[int]) -> None:
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

verified_users: set[int] = load_verified_users()

def add_verified_user(uid: int) -> None:
    verified_users.add(uid)
    save_verified_users(verified_users)

def is_authorised(uid: int) -> bool:
    return uid in ADMIN_IDS or uid in verified_users

# ── Daily Access Key ──────────────────────────────────────────────────────────
def todays_key() -> str:
    date_bytes = datetime.date.today().isoformat().encode()
    return hmac.new(
        DAILY_SECRET.encode(), date_bytes, hashlib.sha256
    ).hexdigest()[:8].upper()

# ── ICMP Ping Helper ──────────────────────────────────────────────────────────
_IP_RE = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}$|"
    r"^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$"
)

def ping_host(host: str, count: int = 4) -> dict:
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", "3", host],
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"success": False, "host": host, "error": "Request timed out."}
    except FileNotFoundError:
        return {"success": False, "host": host, "error": "ping binary not found."}

    loss_match   = re.search(r"(\d+)% packet loss", output)
    loss_pct     = int(loss_match.group(1)) if loss_match else 100

    rtt_match = re.search(
        r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output
    )
    if rtt_match:
        min_ms = float(rtt_match.group(1))
        avg_ms = float(rtt_match.group(2))
        max_ms = float(rtt_match.group(3))
    else:
        min_ms = avg_ms = max_ms = None

    sent_match   = re.search(r"(\d+) packets transmitted", output)
    recv_match   = re.search(r"(\d+) received", output)
    packets_sent = int(sent_match.group(1)) if sent_match else count
    packets_recv = int(recv_match.group(1)) if recv_match else 0

    success = loss_pct < 100 and avg_ms is not None

    return {
        "success":      success,
        "host":         host,
        "packets_sent": packets_sent,
        "packets_recv": packets_recv,
        "loss_pct":     loss_pct,
        "min_ms":       min_ms,
        "avg_ms":       avg_ms,
        "max_ms":       max_ms,
    }

def latency_status(avg_ms: float) -> str:
    if avg_ms < 50:
        return "🟢 EXCELLENT"
    if avg_ms < 150:
        return "🟡 ACCEPTABLE"
    if avg_ms < 300:
        return "🟠 DEGRADED"
    return "🔴 CRITICAL"

# ── Formatters ────────────────────────────────────────────────────────────────
def fmt_ping(data: dict) -> str:
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    if not data["success"]:
        return (
            "```\n"
            "╔══════════════════════════════════════╗\n"
            "║  📡  NET-OPS DIAGNOSTIC CONSOLE      ║\n"
            "╚══════════════════════════════════════╝\n"
            f"  TARGET  : {data['host']}\n"
            f"  STATUS  : 🔴 UNREACHABLE\n"
            f"  ERROR   : {data.get('error', 'Host did not respond')}\n"
            f"  TIME    : {ts}\n"
            "──────────────────────────────────────\n"
            "  [RESULT] Host is offline or blocked.\n"
            "```"
        )

    status = latency_status(data["avg_ms"])
    return (
        "```\n"
        "╔══════════════════════════════════════╗\n"
        "║  📡  NET-OPS DIAGNOSTIC CONSOLE      ║\n"
        "╚══════════════════════════════════════╝\n"
        f"  TARGET   : {data['host']}\n"
        f"  STATUS   : {status}\n"
        "──────────────────────────────────────\n"
        f"  ⚡ LATENCY (avg) : {data['avg_ms']:.1f} ms\n"
        f"  ⚡ LATENCY (min) : {data['min_ms']:.1f} ms\n"
        f"  ⚡ LATENCY (max) : {data['max_ms']:.1f} ms\n"
        "──────────────────────────────────────\n"
        f"  📦 SENT     : {data['packets_sent']}\n"
        f"  📦 RECEIVED : {data['packets_recv']}\n"
        f"  📉 LOSS     : {data['loss_pct']}%\n"
        "──────────────────────────────────────\n"
        f"  🕐 {ts}\n"
        "  [SUCCESS] Diagnostic complete.\n"
        "```"
    )

# ── Command Handlers ──────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    if uid in ADMIN_IDS:
        access_line = "👑 ADMIN — Full access granted"
    elif uid in verified_users:
        access_line = "✅ Verified — Access active"
    else:
        access_line = "🔒 Locked — use /unlock <key>"

    bot.reply_to(
        message,
        "```\n"
        "╔══════════════════════════════════════╗\n"
        "║   🛡️  NET-OPS MONITORING BOT  🛡️     ║\n"
        "╚══════════════════════════════════════╝\n"
        "\n"
        "  Professional network health console.\n"
        "\n"
        "  COMMANDS\n"
        "  ────────\n"
        "  /unlock    <key>   Activate daily access\n"
        "  /check     <host>  ICMP latency probe\n"
        "  /ask       <query> AI network advisor\n"
        "  /help              Show this menu\n"
        "\n"
        "  ADMIN ONLY\n"
        "  ──────────\n"
        "  /adminkey          Today's access key\n"
        "  /broadcast <msg>   Message all users\n"
        "  /users             Verified user count\n"
        "  /revoke    <id>    Remove user access\n"
        "\n"
        f"  ACCESS : {access_line}\n"
        "```",
        parse_mode="Markdown",
    )

@bot.message_handler(commands=["help"])
def cmd_help(message):
    cmd_start(message)

@bot.message_handler(commands=["adminkey"])
def cmd_adminkey(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "🔒 Admin only command.")
        return
    key = todays_key()
    bot.reply_to(
        message,
        f"```\n"
        f"  🗝️  TODAY'S ACCESS KEY\n"
        f"  ──────────────────────\n"
        f"  {key}\n"
        f"\n"
        f"  Valid until UTC midnight.\n"
        f"  Share this with your users.\n"
        f"```",
        parse_mode="Markdown",
    )

@bot.message_handler(commands=["users"])
def cmd_users(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "🔒 Admin only command.")
        return
    count = len(verified_users)
    bot.reply_to(
        message,
        f"```\n"
        f"  👥  VERIFIED USERS\n"
        f"  ──────────────────\n"
        f"  Total : {count} user(s)\n"
        f"  (Saved to file — survives restarts)\n"
        f"```",
        parse_mode="Markdown",
    )

@bot.message_handler(commands=["revoke"])
def cmd_revoke(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "🔒 Admin only command.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(message, "⚠️ Usage: `/revoke <user_id>`", parse_mode="Markdown")
        return
    uid = int(parts[1].strip())
    if uid in verified_users:
        verified_users.discard(uid)
        save_verified_users(verified_users)
        bot.reply_to(message, f"✅ User `{uid}` has been revoked.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"⚠️ User `{uid}` was not in the verified list.", parse_mode="Markdown")

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "🔒 Admin only command.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: `/broadcast <your message>`", parse_mode="Markdown")
        return

    text = parts[1].strip()
    all_users = list(verified_users)

    if not all_users:
        bot.reply_to(message, "⚠️ No verified users to broadcast to.")
        return

    status_msg = bot.reply_to(
        message,
        f"📡 Broadcasting to {len(all_users)} user(s)…",
    )

    broadcast_text = (
        "```\n"
        "╔══════════════════════════════════════╗\n"
        "║  📢  NET-OPS ADMIN BROADCAST         ║\n"
        "╚══════════════════════════════════════╝\n"
        "```\n"
        f"{text}"
    )

    def run_broadcast():
        sent = 0
        failed = 0
        for uid in all_users:
            try:
                bot.send_message(uid, broadcast_text, parse_mode="Markdown")
                sent += 1
            except Exception:
                failed += 1

        bot.edit_message_text(
            f"```\n"
            f"  📢  BROADCAST COMPLETE\n"
            f"  ──────────────────────\n"
            f"  ✅ Delivered : {sent}\n"
            f"  ❌ Failed    : {failed}\n"
            f"  👥 Total     : {len(all_users)}\n"
            f"```",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

    threading.Thread(target=run_broadcast, daemon=True).start()

@bot.message_handler(commands=["unlock"])
def cmd_unlock(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: `/unlock <daily-key>`", parse_mode="Markdown")
        return

    provided = parts[1].strip().upper()
    if hmac.compare_digest(provided, todays_key()):
        add_verified_user(message.from_user.id)
        bot.reply_to(
            message,
            "```\n"
            "  [ACCESS GRANTED]\n"
            "  🟢 Daily key accepted.\n"
            "  You may now use /check.\n"
            "  Your access is saved permanently.\n"
            "```",
            parse_mode="Markdown",
        )
    else:
        bot.reply_to(
            message,
            "```\n"
            "  [ACCESS DENIED]\n"
            "  🔴 Invalid or expired key.\n"
            "  Contact the administrator.\n"
            "```",
            parse_mode="Markdown",
        )

@bot.message_handler(commands=["check"])
def cmd_check(message):
    uid = message.from_user.id

    if not is_authorised(uid):
        bot.reply_to(
            message,
            "🔒 Access required. Use `/unlock <daily-key>` first.",
            parse_mode="Markdown",
        )
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(message, "⚠️ Usage: `/check <IP or hostname>`", parse_mode="Markdown")
        return

    host = parts[1].strip()

    if not _IP_RE.match(host):
        bot.reply_to(message, "⚠️ Please provide a valid IP address or hostname.")
        return

    status_msg = bot.reply_to(message, "📡 Probing target — please wait…")

    def run_probe():
        data   = ping_host(host)
        output = fmt_ping(data)
        bot.edit_message_text(
            output,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

    threading.Thread(target=run_probe, daemon=True).start()

@bot.message_handler(commands=["ask"])
def cmd_ask(message):
    if not gemini_model:
        bot.reply_to(
            message,
            "⚠️ AI advisor is not configured.\n"
            "Set the `GEMINI_API_KEY` environment variable to enable it.",
        )
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(
            message,
            "⚠️ Usage: `/ask <your network question>`",
            parse_mode="Markdown",
        )
        return

    query      = parts[1].strip()
    status_msg = bot.reply_to(message, "🤖 Consulting AI advisor…")

    def run_ai():
        try:
            system_prompt = (
                "You are a senior network engineer and security analyst. "
                "Answer clearly and concisely. Focus on practical, actionable advice. "
                "Use plain text — no markdown formatting."
            )
            response = gemini_model.generate_content(f"{system_prompt}\n\nQuestion: {query}")
            answer   = response.text.strip()
        except Exception as exc:
            answer = f"AI request failed: {exc}"

        header = (
            "```\n"
            "╔══════════════════════════════════════╗\n"
            "║  🤖  AI NETWORK ADVISOR              ║\n"
            "╚══════════════════════════════════════╝\n"
            "```\n\n"
        )
        bot.edit_message_text(
            header + answer,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )

    threading.Thread(target=run_ai, daemon=True).start()

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    public_url = os.environ.get("PUBLIC_URL", "http://localhost:8080/health")
    keep_alive(public_url)
    print("[NET-OPS BOT] Keep-alive server started on port 8080")
    print(f"[NET-OPS BOT] Self-ping URL    : {public_url}")
    print(f"[NET-OPS BOT] Admin IDs        : {ADMIN_IDS}")
    print(f"[NET-OPS BOT] Verified users   : {len(verified_users)} loaded from file")
    print(f"[NET-OPS BOT] Today's key      : {todays_key()}")
    print("[NET-OPS BOT] Polling started…")
    bot.infinity_polling(timeout=30, long_polling_timeout=20)
