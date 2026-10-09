"""Manual approver-triggered SMTP notifications; never an approval mechanism."""
from email.message import EmailMessage
from email.utils import parseaddr
import os
import smtplib
import ssl
import time
import uuid
from backend.contracts import Notification


def email_address(value):
    if not value or any(c.isspace() for c in value):
        return None
    name, address = parseaddr(value)
    if name or address != value or address.count("@") != 1 or "." not in address.split("@")[1]:
        return None
    return address


def config():
    try:
        port = int(os.getenv("IRON_MAN_SMTP_PORT", "587"))
    except ValueError:
        port = 0
    host = os.getenv("IRON_MAN_SMTP_HOST", "")
    sender = email_address(os.getenv("IRON_MAN_SMTP_FROM", ""))
    recipient = email_address(os.getenv("IRON_MAN_APPROVER_EMAIL", ""))
    return {"host": host, "port": port, "sender": sender, "recipient": recipient,
            "configured": bool(host and 1 <= port <= 65535 and sender and recipient)}


def queued(request_id, report_digest):
    cfg = config()
    return Notification(id=str(uuid.uuid4()), request_id=request_id, report_digest=report_digest,
        recipient=cfg["recipient"], status="queued" if cfg["configured"] else "not_configured",
        created_at=time.time(), detail="승인자 발송 버튼 대기" if cfg["configured"] else "SMTP 또는 승인자 이메일 미설정").model_dump()


def send(note, row, contact):
    cfg = config()
    if not cfg["configured"] or note["recipient"] != cfg["recipient"]:
        raise ValueError("알림 설정이 없거나 변경되었습니다. 설정 후 재검증하세요.")
    msg = EmailMessage()
    msg["Subject"] = f"[Iron Man 합성 시연] 검토 요청 {row['id']}"
    msg["From"] = cfg["sender"]
    msg["To"] = note["recipient"]
    msg.set_content(f"합성 시연 검토 알림\n요청 ID: {row['id']}\n"
        f"요청: {row['request']['purpose']}\n목표 속도: {row['request']['command']['target_pct']}%\n"
        f"판정 사유: {row['report']['reason']}\n보고서: {note['report_digest']}\n"
        f"요청자 연락처 (미검증): {contact or '미입력'}\n"
        "요청자에게 연락한 뒤 검토 화면에서 별도로 판단을 제출하세요. 이 이메일은 승인이나 실행 명령이 아닙니다.")
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        username = os.getenv("IRON_MAN_SMTP_USER", "")
        if username:
            smtp.login(username, os.getenv("IRON_MAN_SMTP_PASSWORD", ""))
        refused = smtp.send_message(msg)
        if refused:
            raise RuntimeError("SMTP recipient refused")
