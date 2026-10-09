import os
from typing import Annotated
from fastapi import Depends, FastAPI, Header, HTTPException
from backend.contracts import NewRequest, DecisionInput, ExecutionInput, DemoStateInput
from backend.gateway.service import Gateway

app = FastAPI(title="Iron Man — demo scaffold", version="0.1.0")
gateway = Gateway()

def identity(authorization: Annotated[str | None, Header()] = None):
    token = (authorization or "").removeprefix("Bearer ")
    if token == os.getenv("IRON_MAN_APPROVER_TOKEN", "local-approver"):
        return "approver"
    if token == os.getenv("IRON_MAN_OPERATOR_TOKEN", "local-operator"):
        return "operator"
    raise HTTPException(401, "데모 토큰이 필요합니다.")

def approver(actor=Depends(identity)):
    if actor != "approver":
        raise HTTPException(403, "승인 담당자만 판단할 수 있습니다.")
    return actor

@app.get("/health")
def health():
    return {"status": "ok", "mode": "demo_only", "mock_modules": ["simulator", "evidence"],
            "storage": "in_memory", "real_equipment_connected": False}

@app.get("/state")
def state(actor=Depends(identity)):
    with gateway.lock:
        return gateway.adapter.read_state()

@app.post("/requests", status_code=201)
def create(body: NewRequest, actor=Depends(identity)):
    return gateway.create(body)

@app.get("/requests/{request_id}")
def read(request_id: str, actor=Depends(identity)):
    with gateway.lock:
        return gateway.get(request_id)

@app.post("/requests/{request_id}/evaluate")
def evaluate(request_id: str, actor=Depends(identity)):
    return gateway.evaluate(request_id)

@app.post("/requests/{request_id}/decisions")
def decide(request_id: str, body: DecisionInput, actor=Depends(approver)):
    return gateway.decide(request_id, body, actor)

@app.post("/requests/{request_id}/execute")
def execute(request_id: str, body: ExecutionInput, actor=Depends(identity)):
    return gateway.execute(request_id, body)

@app.post("/demo/state")
def change_state(body: DemoStateInput, actor=Depends(approver)):
    with gateway.lock:
        gateway.adapter.update_demo_state(body.load_ratio, body.sensor_quality)
        return gateway.adapter.read_state()
