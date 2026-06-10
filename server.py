import hashlib
import html
import os
import secrets
import socket
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "traffic.db"
USERNAME = os.getenv("MONITOR_USERNAME", "admin")
PASSWORD = os.getenv("MONITOR_PASSWORD", "admin")
PORT = int(os.getenv("MONITOR_PORT", "9090"))
SESSION_TOKEN = os.getenv("MONITOR_SESSION_TOKEN", secrets.token_urlsafe(32))
COOKIE_NAME = "vps_traffic_session"
HOSTNAME = socket.gethostname()
TELEGRAM_TIMEOUT = 15

app = FastAPI(title="VPS Traffic Monitor")

class LoginPayload(BaseModel):
    username: str
    password: str

class SettingsPayload(BaseModel):
    username: str
    password: str = ""
    hostAlias: str = ""
    dailyLimit: str = "500"
    dailyUnit: str = "GB"
    monthlyLimit: str = "2"
    monthlyUnit: str = "TB"
    alertMode: str = "达到 90% 先提醒，100% 再报警"
    muteWindow: str = "同一类型 6 小时只提醒一次"
    tgToken: str = ""
    tgChatId: str = ""
    tgEnabled: str = "已启用"

def month_key(timestamp: Optional[float] = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time()).strftime("%Y-%m")

def day_key(timestamp: Optional[float] = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time()).strftime("%Y-%m-%d")

def mask_token(token: str) -> str:
    if not token: return ""
    if len(token) <= 8: return "*" * len(token)
    return f"{token[:6]}****{token[-4:]}"

def bytes_for_unit(value_text: str, unit: str) -> int:
    try:
        value = float(value_text or 0)
    except ValueError:
        return 0
    unit_map = {"GB": 1024 ** 3, "TB": 1024 ** 4}
    return int(value * unit_map.get(unit, 1024 ** 3))

def format_bytes(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(num_bytes)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if value >= 100: shown = f"{value:.0f}"
    elif value >= 10: shown = f"{value:.1f}"
    else: shown = f"{value:.2f}"
    return f"{shown} {units[index]}"

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS iface_state (iface TEXT PRIMARY KEY, rx INTEGER NOT NULL, tx INTEGER NOT NULL, sampled_at REAL NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS monthly_usage (month TEXT NOT NULL, iface TEXT NOT NULL, rx INTEGER NOT NULL DEFAULT 0, tx INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (month, iface))")
        connection.execute("CREATE TABLE IF NOT EXISTS daily_usage (day TEXT NOT NULL, iface TEXT NOT NULL, rx INTEGER NOT NULL DEFAULT 0, tx INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, iface))")
        connection.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')")
        connection.execute("CREATE TABLE IF NOT EXISTS alert_state (alert_key TEXT PRIMARY KEY, last_sent_at REAL NOT NULL)")
        defaults = {
            "username": USERNAME,
            "password_hash": hashlib.sha256(PASSWORD.encode("utf-8")).hexdigest(),
            "hostAlias": "",
            "dailyLimit": "500",
            "dailyUnit": "GB",
            "monthlyLimit": "2",
            "monthlyUnit": "TB",
            "alertMode": "达到 90% 先提醒，100% 再报警",
            "muteWindow": "同一类型 6 小时只提醒一次",
            "tgToken": "",
            "tgChatId": "",
            "tgEnabled": "已启用",
        }
        for key, value in defaults.items():
            connection.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (key, value))

def get_settings() -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
    settings = {key: value for key, value in rows}
    settings["hostname"] = HOSTNAME
    settings["tgTokenMasked"] = mask_token(settings.get("tgToken", ""))
    return settings

def save_settings(payload: SettingsPayload) -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("REPLACE INTO app_settings (key, value) VALUES (?, ?)", ("username", payload.username or "admin"))
        if payload.password:
            password_hash = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()
            connection.execute("REPLACE INTO app_settings (key, value) VALUES (?, ?)", ("password_hash", password_hash))
        updates = {
            "hostAlias": payload.hostAlias,
            "dailyLimit": payload.dailyLimit,
            "dailyUnit": payload.dailyUnit,
            "monthlyLimit": payload.monthlyLimit,
            "monthlyUnit": payload.monthlyUnit,
            "alertMode": payload.alertMode,
            "muteWindow": payload.muteWindow,
            "tgChatId": payload.tgChatId,
            "tgEnabled": payload.tgEnabled,
        }
        if payload.tgToken: updates["tgToken"] = payload.tgToken
        for key, value in updates.items():
            connection.execute("REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
    settings = get_settings()
    settings.pop("password_hash", None)
    settings.pop("tgToken", None)
    return settings

def verify_login(username: str, password: str) -> bool:
    settings = get_settings()
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return username == settings.get("username", USERNAME) and password_hash == settings.get("password_hash")

def read_interfaces() -> dict[str, dict[str, int]]:
    dev_path = Path("/proc/net/dev")
    if not dev_path.exists(): return {}
    interfaces: dict[str, dict[str, int]] = {}
    for line in dev_path.read_text().splitlines()[2:]:
        if ":" not in line: continue
        name, values = line.split(":", 1)
        columns = values.split()
        interfaces[name.strip()] = {"rx": int(columns[0]), "tx": int(columns[8])}
    return interfaces

def months_list() -> list[str]:
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute("SELECT DISTINCT month FROM monthly_usage ORDER BY month DESC").fetchall()
    existing = [row[0] for row in rows]
    current = month_key()
    if current not in existing: existing.insert(0, current)
    return existing

def usage_for_month(selected_month: str) -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT iface, rx, tx FROM monthly_usage WHERE month = ? ORDER BY iface", (selected_month,)).fetchall()
    interfaces = [dict(row) for row in rows]
    return {"month": selected_month, "totalRx": sum(item["rx"] for item in interfaces), "totalTx": sum(item["tx"] for item in interfaces), "interfaces": interfaces}

def usage_for_day(selected_day: str) -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT iface, rx, tx FROM daily_usage WHERE day = ? ORDER BY iface", (selected_day,)).fetchall()
    interfaces = [dict(row) for row in rows]
    return {"day": selected_day, "totalRx": sum(item["rx"] for item in interfaces), "totalTx": sum(item["tx"] for item in interfaces), "interfaces": interfaces}

def send_telegram_message(token: str, chat_id: str, text: str) -> dict:
    if not token or not chat_id: raise RuntimeError("Telegram Token 和 Chat ID 缺失")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=TELEGRAM_TIMEOUT) as response:
        body = response.read().decode("utf-8")
    return {"ok": True, "response": body}

def mute_seconds(label: str) -> int:
    if "1 小时" in label: return 3600
    if "天" in label: return 86400
    return 21600

def should_send_alert(alert_key: str, settings: dict) -> bool:
    window = mute_seconds(settings.get("muteWindow", "同一类型 6 小时只提醒一次"))
    now = time.time()
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute("SELECT last_sent_at FROM alert_state WHERE alert_key = ?", (alert_key,)).fetchone()
        if row and now - float(row[0]) < window: return False
        connection.execute("REPLACE INTO alert_state (alert_key, last_sent_at) VALUES (?, ?)", (alert_key, now))
    return True

def build_alert_message(alert_type: str, used_bytes: int, limit_bytes: int, ratio: float, settings: dict, day_usage: dict, month_usage: dict) -> str:
    alias = settings.get("hostAlias", "")
    hostname = html.escape(settings.get("hostname", HOSTNAME))
    alias_text = f"?{html.escape(alias)}?" if alias else ""
    try: ip_text = html.escape(socket.gethostbyname(socket.gethostname()))
    except Exception: ip_text = "0.0.0.0"
    alert_title = "日流量额度预警" if alert_type.startswith("daily") else "月流量额度预警"
    return (
        f"?🚨 <b>VPS 流量报警</b>\\n\\n"
        f"服务器：<b>{hostname}{alias_text}</b>\\n"
        f"IP?<code>{ip_text}</code>\\n"
        f"报警类型：{alert_title}\\n\\n"
        f"当前用量：<b>{format_bytes(used_bytes)}</b>\\n"
        f"设置额度：<b>{format_bytes(limit_bytes)}</b>\\n"
        f"使用比例：<b>{ratio:.1f}%</b>\\n"
        f"下载累计：{format_bytes(day_usage['totalRx'])}\\n"
        f"下载累计：{format_bytes(day_usage['totalTx'])}\\n"
        f"下载累计：{format_bytes(month_usage['totalRx'])}\\n"
        f"下载累计：{format_bytes(month_usage['totalTx'])}\\n\\n"
        f"触发时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n"
        f"说明：流量已达到预警阈值，请及时检查业务流量。"
    )

def alert_thresholds(settings: dict) -> list[int]:
    mode = settings.get("alertMode", "达到 90% 先提醒，100% 再报警")
    if "80% / 90% / 100%" in mode: return [80, 90, 100]
    if "100%" in mode and "90%" not in mode: return [100]
    return [90, 100]

def evaluate_alerts(day_usage: dict, month_usage: dict) -> None:
    settings = get_settings()
    if settings.get("tgEnabled") != "已启用": return
    token, chat_id = settings.get("tgToken", ""), settings.get("tgChatId", "")
    if not token or not chat_id: return
    thresholds = alert_thresholds(settings)
    daily_limit = bytes_for_unit(settings.get("dailyLimit", "0"), settings.get("dailyUnit", "GB"))
    monthly_limit = bytes_for_unit(settings.get("monthlyLimit", "0"), settings.get("monthlyUnit", "TB"))
    daily_used = day_usage["totalRx"] + day_usage["totalTx"]
    monthly_used = month_usage["totalRx"] + month_usage["totalTx"]
    for threshold in thresholds:
        if daily_limit > 0:
            daily_ratio = daily_used * 100 / daily_limit
            if daily_ratio >= threshold:
                alert_key = f"daily:{day_usage['day']}:{threshold}"
                if should_send_alert(alert_key, settings):
                    text = build_alert_message(alert_key, daily_used, daily_limit, daily_ratio, settings, day_usage, month_usage)
                    send_telegram_message(token, chat_id, text)
        if monthly_limit > 0:
            monthly_ratio = monthly_used * 100 / monthly_limit
            if monthly_ratio >= threshold:
                alert_key = f"monthly:{month_usage['month']}:{threshold}"
                if should_send_alert(alert_key, settings):
                    text = build_alert_message(alert_key, monthly_used, monthly_limit, monthly_ratio, settings, day_usage, month_usage)
                    send_telegram_message(token, chat_id, text)

def record_sample() -> dict:
    now = time.time()
    current_month, current_day = month_key(now), day_key(now)
    interfaces = read_interfaces()
    result, total_rx_rate, total_tx_rate = [], 0.0, 0.0
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        for iface, counters in interfaces.items():
            previous = connection.execute("SELECT rx, tx, sampled_at FROM iface_state WHERE iface = ?", (iface,)).fetchone()
            rx_delta = tx_delta = rx_rate = tx_rate = 0
            if previous:
                elapsed = max(now - float(previous["sampled_at"]), 0.001)
                rx_delta = max(counters["rx"] - int(previous["rx"]), 0)
                tx_delta = max(counters["tx"] - int(previous["tx"]), 0)
                rx_rate, tx_rate = rx_delta / elapsed, tx_delta / elapsed
                connection.execute("INSERT INTO monthly_usage (month, iface, rx, tx) VALUES (?, ?, ?, ?) ON CONFLICT(month, iface) DO UPDATE SET rx = rx + excluded.rx, tx = tx + excluded.tx", (current_month, iface, rx_delta, tx_delta))
                connection.execute("INSERT INTO daily_usage (day, iface, rx, tx) VALUES (?, ?, ?, ?) ON CONFLICT(day, iface) DO UPDATE SET rx = rx + excluded.rx, tx = tx + excluded.tx", (current_day, iface, rx_delta, tx_delta))
            connection.execute("INSERT INTO iface_state (iface, rx, tx, sampled_at) VALUES (?, ?, ?, ?) ON CONFLICT(iface) DO UPDATE SET rx = excluded.rx, tx = excluded.tx, sampled_at = excluded.sampled_at", (iface, counters["rx"], counters["tx"], now))
            total_rx_rate += rx_rate; total_tx_rate += tx_rate
            result.append({"iface": iface, "rxRate": rx_rate, "txRate": tx_rate, "rawRx": counters["rx"], "rawTx": counters["tx"]})
    day_usage, month_usage = usage_for_day(current_day), usage_for_month(current_month)
    try: evaluate_alerts(day_usage, month_usage)
    except Exception: pass
    return {"timestamp": int(now), "month": current_month, "day": current_day, "interfaces": sorted(result, key=lambda item: item["iface"]), "totalRxRate": total_rx_rate, "totalTxRate": total_tx_rate, "availableMonths": months_list(), "currentDayUsage": day_usage}

def require_auth(session: Optional[str]) -> None:
    if session != SESSION_TOKEN: raise HTTPException(status_code=401, detail="Unauthorized")

@app.on_event("startup")
def startup() -> None: init_db()

@app.get("/")
def index() -> FileResponse:
    response = FileResponse(APP_DIR / "static" / "index.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.post("/api/login")
def login(payload: LoginPayload, response: Response) -> dict:
    if not verify_login(payload.username, payload.password): raise HTTPException(status_code=401, detail="账号或密码错误")
    response.set_cookie(COOKIE_NAME, SESSION_TOKEN, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"ok": True, "username": get_settings().get("username", USERNAME)}

@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}

@app.get("/api/me")
def me(vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    return {"username": get_settings().get("username", USERNAME)}

@app.get("/api/settings")
def settings(vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    settings = get_settings()
    settings.pop("password_hash", None)
    settings.pop("tgToken", None)
    return settings

@app.post("/api/settings")
def update_settings(payload: SettingsPayload, vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    return save_settings(payload)

@app.post("/api/test-telegram")
def test_telegram(vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    settings = get_settings()
    if not settings.get("tgToken") or not settings.get("tgChatId"): raise HTTPException(status_code=400, detail="请先设置 Telegram Token 和 Chat ID")
    message = f"✅ <b>VPS 流量监控测试消息</b>\\n\\n服务器：<b>{html.escape(settings.get('hostname', HOSTNAME))}</b>\\n备注：{html.escape(settings.get('hostAlias', '') or '未设置')}\\n时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    try:
        result = send_telegram_message(settings["tgToken"], settings["tgChatId"], message)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Telegram 推送失败：{error}") from error
    return {"ok": True, "result": result}

@app.get("/api/realtime")
def realtime(vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    sample = record_sample()
    sample["currentMonthUsage"] = usage_for_month(sample["month"])
    return sample

@app.get("/api/monthly")
def monthly(month: Optional[str] = None, vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    record_sample()
    return usage_for_month(month or month_key())

@app.get("/api/months")
def months(vps_traffic_session: Optional[str] = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    record_sample()
    return {"months": months_list()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
