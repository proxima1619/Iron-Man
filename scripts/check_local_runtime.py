"""Check the running local synthetic demo and its SQLite records.

Creates two labelled demo requests. Does not send email or control real equipment.
Run from the repository root while the local API is running.
"""
import argparse
import http.client
import json
from pathlib import Path
import sqlite3
import time


def api(path, body=None, role="operator", expected=200):
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
    headers = {"X-Iron-Man-Token": "local-" + role, "Content-Type": "application/json"}
    connection.request("GET" if body is None else "POST", path,
                       None if body is None else json.dumps(body), headers)
    response = connection.getresponse()
    value = json.loads(response.read())
    connection.close()
    assert response.status == expected, (path, response.status, value)
    return value


def run(db_path):
    assert api("/health")["storage"] == "sqlite"
    api("/demo/sample", {}, "approver")
    result = []
    for speed, status in ((60, "blocked"), (80, "awaiting_approval")):
        row = api("/requests", {"purpose": "Runtime verification: synthetic cooling demo",
                  "command": {"target_pct": speed, "duration_s": 300},
                  "requester_contact": "synthetic-requester@example.invalid"}, expected=201)
        api(f"/requests/{row['id']}/evaluate", {}, expected=202)
        deadline = time.monotonic() + 30
        while True:
            row = api(f"/requests/{row['id']}")
            if row["status"] != "evaluating":
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Evaluation did not finish")
            time.sleep(0.2)
        assert row["status"] == status, row
        report = row["report"]
        assert report["simulation"]["status"] == "completed"
        contact = api(f"/requests/{row['id']}/review-contact", role="approver")
        assert contact["requester_contact"] == "synthetic-requester@example.invalid"
        assert "synthetic-requester" not in json.dumps(row)
        if speed == 80:
            api(f"/requests/{row['id']}/decisions", {"decision": "approve",
                "report_digest": report["digest"], "reason": "Synthetic runtime verification"},
                expected=403)
            row = api(f"/requests/{row['id']}/decisions", {"decision": "approve",
                "report_digest": report["digest"], "reason": "Synthetic runtime verification"}, "approver")
            assert row["status"] == "approved"
            row = api(f"/requests/{row['id']}/execute", {"report_digest": report["digest"]}, "approver")
            assert row["status"] == "completed" and row["execution"]["virtual"] is True
        result.append({"id": row["id"], "target_pct": speed, "status": row["status"], "digest": report["digest"]})
    with sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for row in result:
            stored = json.loads(db.execute("SELECT record_json FROM requests WHERE id=?", (row["id"],)).fetchone()[0])
            assert stored["status"] == row["status"] and stored["report"]["digest"] == row["digest"]
        print(json.dumps({"database": str(db_path), "schema": db.execute("PRAGMA user_version").fetchone()[0],
                          "integrity": "ok", "checks": result}, ensure_ascii=False))
    Path("data/runtime-check.json").write_text(json.dumps(result), encoding="utf-8")


def verify_restart():
    rows = json.loads(Path("data/runtime-check.json").read_text(encoding="utf-8"))
    for saved in rows:
        row = api(f"/requests/{saved['id']}")
        assert row["status"] == saved["status"]
        assert row["report"]["digest"] == saved["digest"]
        assert row["events"]
    print("PASS: request statuses, report digests and audit events restored after restart")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-restart", action="store_true")
    parser.add_argument("--db", type=Path, default=Path("data/ironman.sqlite3"))
    args = parser.parse_args()
    verify_restart() if args.after_restart else run(args.db)
