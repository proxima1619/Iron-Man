"""Persistent virtual equipment only; never connect this implementation to a PLC."""
import json
import time
from backend.contracts import Command, Snapshot
from backend.gateway.storage import SQLiteStore, encode


class DemoAdapter:
    def __init__(self, store=None):
        self.store = store if store is not None else SQLiteStore()

    @staticmethod
    def _snapshot(state):
        return Snapshot(revision=state["revision"], temperature_c=60.0,
            load_ratio=state["load_ratio"], pump_speed_pct=state["pump_speed_pct"],
            sensor_quality=state["sensor_quality"], observed_at=time.time())

    def read_state(self) -> Snapshot:
        return self._snapshot(self.store.read_demo_state())

    def update_demo_state(self, load_ratio, sensor_quality):
        with self.store.transaction() as db:
            state = json.loads(db.execute("SELECT state_json FROM demo_state WHERE id=1").fetchone()[0])
            state.update(load_ratio=load_ratio, sensor_quality=sensor_quality, revision=state["revision"] + 1)
            db.execute("UPDATE demo_state SET state_json=? WHERE id=1", (encode(state),))

    def apply_command(self, execution_id: str, command: Command) -> dict:
        # Virtual state and receipt commit together. Real hardware cannot share this transaction.
        with self.store.transaction() as db:
            prior = db.execute("SELECT result_json FROM adapter_executions WHERE id=?", (execution_id,)).fetchone()
            if prior:
                result = json.loads(prior[0])
                if result["command"] != command.model_dump():
                    raise ValueError("Execution ID was already used for a different command")
                return result
            state = json.loads(db.execute("SELECT state_json FROM demo_state WHERE id=1").fetchone()[0])
            state.update(pump_speed_pct=command.target_pct, revision=state["revision"] + 1)
            result = {"execution_id": execution_id, "status": "applied", "virtual": True,
                      "command": command.model_dump(), "state": self._snapshot(state).model_dump()}
            db.execute("UPDATE demo_state SET state_json=? WHERE id=1", (encode(state),))
            db.execute("INSERT INTO adapter_executions VALUES (?, ?)", (execution_id, encode(result)))
            return result

    def get_execution(self, execution_id):
        return self.store.get_execution(execution_id)

    @property
    def executions(self):
        return self.store.list_executions()
