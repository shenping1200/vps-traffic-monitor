import os
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "traffic.db"
USERNAME = os.getenv("MONITOR_USERNAME", "admin")
PASSWORD = os.getenv("MONITOR_PASSWORD", "QQqq308008685")
PORT = int(os.getenv("MONITOR_PORT", "9090"))
SESSION_TOKEN = os.getenv("MONITOR_SESSION_TOKEN", secrets.token_urlsafe(32))
COOKIE_NAME = "vps_traffic_session"

app = FastAPI(title="VPS Traffic Monitor")


class LoginPayload(BaseModel):
    username: str
    password: str


def month_key(timestamp: float | None = None) -> str:
    return datetime.fromtimestamp(timestamp or time.time()).strftime("%Y-%m")


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
                "SELECT rx, tx, sampled_at FROM iface_state WHERE iface = ?", (iface,)
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


def require_auth(session: str | None) -> None:
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
    if payload.username != USERNAME or payload.password != PASSWORD:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    response.set_cookie(
        COOKIE_NAME,
        SESSION_TOKEN,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return {"ok": True, "username": USERNAME}


@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(vps_traffic_session: str | None = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    return {"username": USERNAME}


@app.get("/api/realtime")
def realtime(vps_traffic_session: str | None = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    sample = record_sample()
    sample["currentMonthUsage"] = usage_for_month(sample["month"])
    return sample


@app.get("/api/monthly")
def monthly(month: str | None = None, vps_traffic_session: str | None = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    record_sample()
    return usage_for_month(month or month_key())


@app.get("/api/months")
def months(vps_traffic_session: str | None = Cookie(default=None)) -> dict:
    require_auth(vps_traffic_session)
    record_sample()
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute(
            "SELECT DISTINCT month FROM monthly_usage ORDER BY month DESC"
        ).fetchall()
    existing = [row[0] for row in rows]
    current = month_key()
    if current not in existing:
        existing.insert(0, current)
    return {"months": existing}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
