# app/main.py
import socket
import subprocess
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import (create_engine, Column, Integer, String,
                        BigInteger, DateTime, func)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
import datetime

# --- Настройки ---
DATABASE_URL = "sqlite:///./vpn.db"
MGMT_ADDRESS = "127.0.0.1"
MGMT_PORT = 7505
MGMT_TIMEOUT = 5  # секунд

# --- БД ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=func.now())

class TrafficRecord(Base):
    __tablename__ = "traffic"
    id = Column(Integer, primary_key=True, index=True)
    user_name = Column(String, index=True)
    bytes_recv = Column(BigInteger)
    bytes_sent = Column(BigInteger)
    timestamp = Column(DateTime, default=func.now())

Base.metadata.create_all(bind=engine)

# --- FastAPI ---
app = FastAPI(title="OpenVPN Management via Management Interface")

# --- Pydantic ---
class UserCreate(BaseModel):
    name: str

# --- Утилиты для Management Interface ---
def mgmt_command(cmd: str) -> str:
    """Отправляет команду на management-интерфейс и возвращает ответ."""
    with socket.create_connection((MGMT_ADDRESS, MGMT_PORT), timeout=MGMT_TIMEOUT) as sock:
        # При подключении OpenVPN шлёт баннер — читать до prompt '>\s'
        data = sock.recv(1024)
        # Отправляем команду
        sock.sendall((cmd + "\n").encode())
        # Считываем ответ до строки 'END'
        buf = b""
        while True:
            chunk = sock.recv(4096)
            buf += chunk
            if b"END\n" in buf or not chunk:
                break
        return buf.decode()

# --- Парсинг статуса и запись трафика ---
def parse_status(mgmt_status: str) -> list[dict]:
    clients = []
    for line in mgmt_status.splitlines():
        if line.startswith("CLIENT_LIST"):
            parts = line.split(",")
            # CLIENT_LIST,name,real_ip,virt_ip,bytes_recv,bytes_sent,...
            _, name, real_ip, virt_ip, bytes_recv, bytes_sent, *rest = parts
            clients.append({
                "name": name,
                "real_ip": real_ip,
                "virt_ip": virt_ip,
                "bytes_recv": int(bytes_recv),
                "bytes_sent": int(bytes_sent),
            })
    return clients

def record_traffic() -> None:
    """Регулярно вызывается APScheduler — записывает stats в БД."""
    status = mgmt_command("status")
    clients = parse_status(status)
    db = SessionLocal()
    for c in clients:
        rec = TrafficRecord(
            user_name=c["name"],
            bytes_recv=c["bytes_recv"],
            bytes_sent=c["bytes_sent"],
        )
        db.add(rec)
    db.commit()
    db.close()

# --- Эндпоинты Management Interface ---
@app.get("/management/status/", response_model=list[dict])
def management_status():
    """Получить raw-статус через management-интерфейс."""
    try:
        raw = mgmt_command("status")
    except Exception as e:
        raise HTTPException(500, f"Ошибка подключения к mgmt interface: {e}")
    return parse_status(raw)

@app.post("/management/kill/{client_name}", response_model=dict)
def management_kill(client_name: str):
    """Отключить клиента через mgmt-интерфейс."""
    try:
        # команда kill name <client_name>
        resp = mgmt_command(f"kill name {client_name}")
    except Exception as e:
        raise HTTPException(500, f"Ошибка при отключении: {e}")
    return {"message": resp}

# --- Существующие эндпоинты для add/del — как было ранее ---
def run_script(script_path: str, args: list):
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
def create_user(u: UserCreate):
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
def delete_user(name: str):
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
def start_scheduler():
    scheduler = BackgroundScheduler()
    # Запуск record_traffic() каждую минуту
    scheduler.add_job(record_traffic, 'interval', minutes=1, id="traffic_job")
    scheduler.start()

# --- Эндпоинт истории трафика пользователя ---
@app.get("/traffic/history/{name}", response_model=list[dict])
def traffic_history(name: str, limit: int = 50):
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
