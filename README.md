# Net-Ops Monitoring Bot

A professional network health and latency monitoring Telegram bot.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Your bot token from @BotFather |
| `DAILY_KEY_SECRET` | Yes | A secret string you choose — used to generate the daily access key |
| `GEMINI_API_KEY` | No | Google AI Studio API key — enables the /ask command |

### 3. Run the bot

```bash
python main.py
```

On startup the bot prints today's access key to the console:

```
[NET-OPS BOT] Today's access key: A3F9B2C1
```

Share this key with your authorised users each day. It rotates automatically at UTC midnight.

---

## Commands

| Command | Description |
|---|---|
| `/start` | Show welcome screen and current access status |
| `/unlock <key>` | Enter today's daily access key |
| `/check <IP or hostname>` | Run an ICMP latency probe against a target |
| `/ask <question>` | Ask the Gemini AI advisor a network question |
| `/help` | Show the command menu |

---

## Computing tomorrow's key (admin only)

```python
import hmac, hashlib, datetime

secret = "your-DAILY_KEY_SECRET-value"
date   = datetime.date.today().isoformat()   # change to tomorrow's date if needed
key    = hmac.new(secret.encode(), date.encode(), hashlib.sha256).hexdigest()[:8].upper()
print(key)
```
