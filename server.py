import hashlib
import os
import secrets
import socket
import sqlite3
import time
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
    alertMode: str = "?? 90% ????100% ???"
    muteWindow: str = "???? 6 ???????"
    tgToken: str = ""
    tgChatId: str = ""
    tgEnabled: str = "???"


def month_key(timestamp: Optional[float] = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time()).strftime("%Y-%m")


def mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:6]}****{token[-4:]}"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS iface_state (
                iface TEXT PRIMARY KEY,
                rx INTEGER NOT NULL,
                tx INTEGER NOT NULL,
                sampled_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_usage (
                month TEXT NOT NULL,
                iface TEXT NOT NULL,
                rx INTEGER NOT NULL DEFAULT 0,
                tx INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (month, iface)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
            """
        )
        defaults = {
            "username": USERNAME,
            "password_hash": hashlib.sha256(PASSWORD.encode("utf-8")).hexdigest(),
            "hostAlias": "",
            "dailyLimit": "500",
            "dailyUnit": "GB",
            "monthlyLimit": "2",
            "monthlyUnit": "TB",
            "alertMode": "?? 90% ????100% ???",
            "muteWindow": "???? 6 ???????",
            "tgToken": "",
            "tgChatId": "",
            "tgEnabled": "???",
        }
        for key, value in defaults.items():
            connection.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def get_settings() -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
    settings = {key: value for key, value in rows}
    settings["hostname"] = HOSTNAME
    settings["tgTokenMasked"] = mask_token(settings.get("tgToken", ""))
    return settings


def save_settings(payload: SettingsPayload) -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ("username", payload.username or "admin"),
        )
        if payload.password:
            connection.execute(
                "REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                ("password_hash", hashlib.sha256(payload.password.encode("utf-8")).hexdigest()),
            )
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
        if payload.tgToken:
            updates["tgToken"] = payload.tgToken
        for key, value in updates.items():
            connection.execute(
                "REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
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
    if not dev_path.exists():
        return {}
    interfaces: dict[str, dict[str, int]] = {}
    for line in dev_path.read_text().splitlines()[2:]:
        if ":" not in line:
            continue
        name, values = line.split(":", 1)
        columns = values.split()
        interfaces[name.strip()] = {"rx": int(columns[0]), "tx": int(columns[8])}
    return interfaces


def months_list() -> list[str]:
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute("SELECT DISTINCT month FROM monthly_usage ORDER BY month DESC").fetchall()
    existing = [row[0] for row in rows]
    current = month_key()
    if current not in existing:
        existing.insert(0, current)
    return existing


def record_sample() -> dict:
    now = time.time()
    current_month = month_key(now)
    interfaces = read_interfaces()
    result = []
    total_rx_rate = 0.0
    total_tx_rate = 0.0
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        for iface, counters in interfaces.items():
            previous = connection.execute(
                "SELECT rx, tx, sampled_at FROM iface_state WHERE iface = ?",
                (iface,),
            ).fetchone()
            rx_delta = 0
            tx_delta = 0
            rx_rate = 0.0
            tx_rate = 0.0
            if previous:
                elapsed = max(now - float(previous["sampled_at"]), 0.001)
                rx_delta = max(counters["rx"] - int(previous["rx"]), 0)
                tx_delta = max(counters["tx"] - int(previous["tx"]), 0)
                rx_rate = rx_delta / elapsed
                tx_rate = tx_delta / elapsed
                connection.execute(
                    """
                    INSERT INTO monthly_usage (month, iface, rx, tx)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(month, iface) DO UPDATE SET
                        rx = rx + excluded.rx,
                        tx = tx + excluded.tx
                    """,
                    (current_month, iface, rx_delta, tx_delta),
                )
            connection.execute(
                """
                INSERT INTO iface_state (iface, rx, tx, sampled_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(iface) DO UPDATE SET
                    rx = excluded.rx,
                    tx = excluded.tx,
                    sampled_at = excluded.sampled_at
                """,
                (iface, counters["rx"], counters["tx"], now),
            )
            total_rx_rate += rx_rate
            total_tx_rate += tx_rate
            result.append(
                {
                    "iface": iface,
                    "rxRate": rx_rate,
                    "txRate": tx_rate,
                    "rawRx": counters["rx"],
                    "rawTx": counters["tx"],
                }
            )
    return {
        "timestamp": int(now),
        "month": current_month,
        "interfaces": sorted(result, key=lambda item: item["iface"]),
        "totalRxRate": total_rx_rate,
        "totalTxRate": total_tx_rate,
        "availableMonths": months_list(),
    }


def usage_for_month(selected_month: str) -> dict:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT iface, rx, tx FROM monthly_usage WHERE month = ? ORDER BY iface",
            (selected_month,),
        ).fetchall()
    interfaces = [dict(row) for row in rows]
    return {
        "month": selected_month,
        "totalRx": sum(item["rx"] for item in interfaces),
        "totalTx": sum(item["tx"] for item in interfaces),
        "interfaces": interfaces,
    }


def require_auth(session: Optional[str]) -> None:
    if session != SESSION_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.post("/api/login")
def login(payload: LoginPayload, response: Response) -> dict:
    if not verify_login(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="???????")
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
