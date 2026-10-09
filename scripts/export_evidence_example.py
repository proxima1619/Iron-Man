"""Export a genuine fixture-mode output after advancing an isolated virtual plant."""
import json
from pathlib import Path
from unittest.mock import patch
from backend.contracts import NewRequest, Command
from backend.evidence.service import review_evidence
from backend.gateway.service import Gateway


if __name__ == "__main__":
    gateway = Gateway()  # In-memory test plant; never touches the server equipment DB.
    try:
        gateway.adapter.apply_command("example-only", Command(target_pct=60))
        gateway.adapter.advance_time(30)
        snapshot = gateway.adapter.read_state()
        request = NewRequest(command=Command(target_pct=80))
        with patch.dict("os.environ", {"IRON_MAN_EVIDENCE_MODE": "fixture"}):
            review = review_evidence(request, snapshot)
        example = {"example_only": True, "llm_executed": False,
                   "input_origin": "isolated_in_memory_virtual_plant",
                   "request": request.model_dump(), "snapshot": snapshot.model_dump(),
                   "evidence": review.model_dump()}
        path = Path("fixtures/evidence-v3-example.json")
        path.write_text(json.dumps(example, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(str(path))
    finally:
        gateway.close()
