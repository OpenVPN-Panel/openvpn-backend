import subprocess

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException

from db.db import UserCreate, SessionLocal, User, TrafficRecord
from utils.managment import mgmt_command, parse_status, record_traffic

app = FastAPI(title="OpenVPN Management via Management Interface")


# --- Endpointы Management Interface ---
@app.get("/management/status/", response_model=list[dict])
async def management_status():
    """Получить raw-статус через management-интерфейс."""
    try:
        raw = mgmt_command("status")
    except Exception as e:
        raise HTTPException(500, f"Ошибка подключения к mgmt interface: {e}")
    return parse_status(raw)


@app.post("/management/kill/{client_name}", response_model=dict)
async def management_kill(client_name: str):
    """Отключить клиента через mgmt-интерфейс."""
    try:
        # команда kill name <client_name>
        resp = mgmt_command(f"kill name {client_name}")
    except Exception as e:
        raise HTTPException(500, f"Ошибка при отключении: {e}")
    return {"message": resp}


# --- Существующие Endpointы для add/del — как было ранее ---
async def run_script(script_path: str, args: list):
    try:
        result = subprocess.run(
            [script_path] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.stderr.strip())


@app.post("/users/", response_model=dict)
async def create_user(u: UserCreate):
    db = SessionLocal()
    if db.query(User).filter_by(name=u.name).first():
        raise HTTPException(400, "Пользователь уже существует")
    db.add(User(name=u.name))
    db.commit()
    try:
        out = run_script("/home/admin/addClient.sh", [u.name])
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {"message": out}


@app.delete("/users/{name}", response_model=dict)
async def delete_user(name: str):
    db = SessionLocal()
    if not db.query(User).filter_by(name=name).first():
        raise HTTPException(404, "Пользователь не найден")
    try:
        out = run_script("/home/admin/delClient.sh", [name])
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    db.query(User).filter_by(name=name).delete()
    db.commit()
    return {"message": out}


# --- Запуск APScheduler при старте приложения ---
@app.on_event("startup")
async def start_scheduler():
    scheduler = BackgroundScheduler()
    # Запуск record_traffic() каждую минуту
    scheduler.add_job(record_traffic, 'interval', minutes=1, id="traffic_job")
    scheduler.start()


# --- Endpoint истории трафика пользователя ---
@app.get("/traffic/history/{name}", response_model=list[dict])
async def traffic_history(name: str, limit: int = 50):
    db = SessionLocal()
    rows = (
        db.query(TrafficRecord)
        .filter_by(user_name=name)
        .order_by(TrafficRecord.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "bytes_recv": r.bytes_recv,
            "bytes_sent": r.bytes_sent,
        } for r in rows
    ]

