"""Persistent virtual plant with an explicit manual clock; never connect to a PLC."""
import json
import time
from backend.contracts import Command, DemoAdvanceInput, DemoStateInput, Snapshot
from backend.gateway.storage import SQLiteStore, encode, initial_demo_state
from backend.simulator.model import MODEL, advance_state
from backend.simulator.service import ModelDomainError, _check_state, domain_reasons


class DemoAdapter:
    def __init__(self, store=None):
        self.store = store if store is not None else SQLiteStore()

    @staticmethod
    def _snapshot(state):
        return Snapshot.model_validate(state)

    @staticmethod
    def _read(db):
        return json.loads(db.execute("SELECT state_json FROM demo_state WHERE id=1").fetchone()[0])

    @staticmethod
    def _write(db, state):
        db.execute("UPDATE demo_state SET state_json=? WHERE id=1", (encode(state),))

    def read_state(self) -> Snapshot:
        return self._snapshot(self.store.read_demo_state())

    def update_demo_state(self, load_ratio, sensor_quality):
        update = DemoStateInput(load_ratio=load_ratio, sensor_quality=sensor_quality)
        with self.store.transaction() as db:
            state = self._read(db)
            # A configuration edit cannot clear a failed model trajectory.
            quality = update.sensor_quality if state["domain_status"] == "ready" else "invalid"
            state.update(load_ratio=update.load_ratio, sensor_quality=quality,
                         revision=state["revision"] + 1, observed_at=time.time())
            self._write(db, state)

    def sample_state(self) -> Snapshot:
        """Explicitly take a synthetic observation of the paused virtual plant."""
        with self.store.transaction() as db:
            state = self._read(db)
            state["observed_at"] = time.time()
            self._write(db, state)
            return self._snapshot(state)

    def reset_state(self) -> Snapshot:
        """Start another demo run. Historical records/receipts remain immutable."""
        with self.store.transaction() as db:
            state = initial_demo_state(self._read(db)["revision"] + 1)
            self._write(db, state)
            return self._snapshot(state)

    def advance_time(self, seconds_s: int) -> Snapshot:
        """Advance the manual clock, stopping at the last state within the model domain."""
        seconds_s = DemoAdvanceInput(seconds_s=seconds_s).seconds_s
        with self.store.transaction() as db:
            state = self._read(db)
            if state["domain_status"] != "ready":
                raise ValueError("가상 설비가 모델 범위 밖입니다. 데모 초기화가 필요합니다.")
            snapshot = self._snapshot(state)
            reasons = domain_reasons(snapshot)
            failure = ", ".join(reasons) if reasons else None
            temperature, speed = snapshot.temperature_c, snapshot.pump_speed_pct
            elapsed_s = snapshot.simulation_time_s
            if failure is None:
                for _ in range(seconds_s):
                    next_temperature, next_speed = advance_state(
                        temperature, speed, state["target_pump_speed_pct"], state["load_ratio"], 1.0, MODEL.dt_s)
                    try:
                        _check_state(next_temperature, next_speed, elapsed_s + MODEL.dt_s)
                    except ModelDomainError as exc:
                        failure = str(exc)
                        break
                    temperature, speed = next_temperature, next_speed
                    elapsed_s += MODEL.dt_s
            now = time.time()
            state.update(temperature_c=temperature, pump_speed_pct=speed,
                         simulation_time_s=elapsed_s, calculated_at=now, observed_at=now,
                         revision=state["revision"] + 1)
            if failure:
                state.update(domain_status="out_of_domain", domain_reason=failure, sensor_quality="invalid")
            self._write(db, state)
            return self._snapshot(state)

    def apply_command(self, execution_id: str, command: Command) -> dict:
        # Virtual state and receipt commit together. Real hardware cannot share this transaction.
        with self.store.transaction() as db:
            prior = db.execute("SELECT result_json FROM adapter_executions WHERE id=?", (execution_id,)).fetchone()
            if prior:
                result = json.loads(prior[0])
                if result["command"] != command.model_dump():
                    raise ValueError("Execution ID was already used for a different command")
                return result
            command = Command.model_validate(command)
            state = self._read(db)
            if domain_reasons(self._snapshot(state)):
                raise ValueError("모델이 지원하지 않는 가상 설비 상태에는 명령을 적용할 수 없습니다.")
            # A setpoint is persistent; duration_s only bounds the evaluation forecast.
            # Actual speed and temperature change only when virtual time advances.
            state.update(target_pump_speed_pct=command.target_pct, revision=state["revision"] + 1)
            result = {"execution_id": execution_id, "status": "applied", "virtual": True,
                      "command": command.model_dump(), "state": self._snapshot(state).model_dump()}
            self._write(db, state)
            db.execute("INSERT INTO adapter_executions VALUES (?, ?)", (execution_id, encode(result)))
            return result

    def get_execution(self, execution_id):
        return self.store.get_execution(execution_id)

    @property
    def executions(self):
        return self.store.list_executions()
