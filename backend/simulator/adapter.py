"""Owner 2: in-process virtual equipment only; never connect this to a PLC."""
import time
from backend.contracts import Command, Snapshot

class DemoAdapter:
    def __init__(self):
        self.revision = 1
        self.load_ratio = 1.0
        self.pump_speed_pct = 100.0
        self.sensor_quality = "valid"
        self.executions = {}

    def read_state(self) -> Snapshot:
        return Snapshot(revision=self.revision, temperature_c=60.0,
            load_ratio=self.load_ratio, pump_speed_pct=self.pump_speed_pct,
            sensor_quality=self.sensor_quality, observed_at=time.time())

    def update_demo_state(self, load_ratio, sensor_quality):
        self.load_ratio = load_ratio
        self.sensor_quality = sensor_quality
        self.revision += 1

    def apply_command(self, execution_id: str, command: Command) -> dict:
        if execution_id in self.executions:
            return self.executions[execution_id]
        self.pump_speed_pct = command.target_pct
        self.revision += 1
        result = {"execution_id": execution_id, "status": "applied",
                  "virtual": True, "command": command.model_dump(),
                  "state": self.read_state().model_dump()}
        self.executions[execution_id] = result
        return result

    def get_execution(self, execution_id):
        return self.executions.get(execution_id)
