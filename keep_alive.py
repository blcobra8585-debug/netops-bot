import time
import requests
import threading
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "NET-OPS BOT — Online", 200

@app.route("/health")
def health():
    return "OK", 200

def run():
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

def self_ping(url: str, interval: int = 240):
    time.sleep(30)
    while True:
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass
        time.sleep(interval)

def keep_alive(public_url: str = "http://localhost:8080/health"):
    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=self_ping, args=(public_url,), daemon=True).start()
