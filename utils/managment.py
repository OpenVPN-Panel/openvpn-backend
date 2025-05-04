import socket

from config import MGMT_ADDRESS, MGMT_PORT, MGMT_TIMEOUT


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
