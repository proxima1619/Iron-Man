import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi.responses import JSONResponse
from typing import Annotated
from fastapi import Depends, FastAPI, Header, HTTPException
from backend.contracts import NewRequest, DecisionInput, ExecutionInput, DemoStateInput, DemoAdvanceInput, RequestRecord, Snapshot, RequestHistory
from backend.gateway.service import Gateway
from backend.config import validate_runtime_config

gateway = None

@asynccontextmanager
async def lifespan(app):
    global gateway
    validate_runtime_config()
    default_path = Path(__file__).resolve().parents[1] / "data" / "ironman.sqlite3"
    gateway = Gateway(os.getenv("IRON_MAN_DB_PATH", str(default_path)),
        max_evaluations=int(os.getenv("IRON_MAN_EVALUATION_WORKERS", "2")),
        evaluation_timeout_s=float(os.getenv("IRON_MAN_EVALUATION_TIMEOUT_S", "90")))
    try:
        yield
    finally:
        gateway.close()
        gateway = None

app = FastAPI(title="Iron Man — demo scaffold", version="0.1.0", lifespan=lifespan)

@app.exception_handler(sqlite3.Error)
async def storage_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "저장소 오류: 처리 결과를 확인한 뒤 다시 시도하세요."})

def identity(authorization: Annotated[str | None, Header()] = None,
             x_iron_man_token: Annotated[str | None, Header()] = None):
    # Browser Basic authentication belongs to the HTTPS edge. A separate role
    # header lets same-origin fetch retain the browser's Basic credentials.
    bearer = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    if bearer is not None and x_iron_man_token is not None and bearer != x_iron_man_token:
        raise HTTPException(401, "서로 다른 인증 토큰이 전달됐습니다.")
    token = x_iron_man_token if x_iron_man_token is not None else bearer
    if not token or not token.isascii():
        raise HTTPException(401, "데모 토큰이 필요합니다.")
    if secrets.compare_digest(token, os.getenv("IRON_MAN_APPROVER_TOKEN", "local-approver")):
        return "approver"
    if secrets.compare_digest(token, os.getenv("IRON_MAN_OPERATOR_TOKEN", "local-operator")):
        return "operator"
    raise HTTPException(401, "데모 토큰이 필요합니다.")

def approver(actor=Depends(identity)):
    if actor != "approver":
        raise HTTPException(403, "승인 담당자만 판단할 수 있습니다.")
    return actor

@app.get("/health")
def health():
    return {"status": "ok", "mode": "demo_only", "mock_modules": ["evidence"],
            "storage": "sqlite", "real_equipment_connected": False}

@app.get("/state", response_model=Snapshot)
def state(actor=Depends(identity)):
    with gateway.lock:
        return gateway.adapter.read_state()

@app.post("/requests", status_code=201, response_model=RequestRecord)
def create(body: NewRequest, actor=Depends(identity)):
    return gateway.create(body)

@app.get("/requests", response_model=list[RequestRecord])
def list_requests(actor=Depends(identity)):
    return gateway.list_records()

@app.get("/requests/{request_id}/history", response_model=RequestHistory)
def history(request_id: str, actor=Depends(identity)):
    return gateway.history(request_id)

@app.get("/requests/{request_id}", response_model=RequestRecord)
def read(request_id: str, actor=Depends(identity)):
    with gateway.lock:
        return gateway.get(request_id)

@app.post("/requests/{request_id}/evaluate", status_code=202, response_model=RequestRecord)
def evaluate(request_id: str, actor=Depends(identity)):
    return gateway.submit_evaluation(request_id)

@app.post("/requests/{request_id}/evaluation/cancel", response_model=RequestRecord)
def cancel_evaluation(request_id: str, actor=Depends(identity)):
    return gateway.cancel_evaluation(request_id)

@app.post("/requests/{request_id}/decisions", response_model=RequestRecord)
def decide(request_id: str, body: DecisionInput, actor=Depends(approver)):
    return gateway.decide(request_id, body, actor)

@app.post("/requests/{request_id}/execute", response_model=RequestRecord)
def execute(request_id: str, body: ExecutionInput, actor=Depends(identity)):
    return gateway.execute(request_id, body)

@app.post("/demo/state", response_model=Snapshot)
def change_state(body: DemoStateInput, actor=Depends(approver)):
    with gateway.lock:
        gateway.adapter.update_demo_state(body.load_ratio, body.sensor_quality)
        return gateway.adapter.read_state()


@app.post("/demo/advance", response_model=Snapshot)
def advance_virtual_time(body: DemoAdvanceInput, actor=Depends(approver)):
    with gateway.lock:
        try:
            return gateway.adapter.advance_time(body.seconds_s)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@app.post("/demo/sample", response_model=Snapshot)
def sample_virtual_state(actor=Depends(approver)):
    with gateway.lock:
        return gateway.adapter.sample_state()


@app.post("/demo/reset", response_model=Snapshot)
def reset_virtual_state(actor=Depends(approver)):
    with gateway.lock:
        return gateway.adapter.reset_state()
