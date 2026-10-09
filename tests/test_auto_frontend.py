import pytest
from scripts.auto_frontend import ci_status, frontend_changed, replace_web


def test_only_successful_main_push_can_deploy_and_latest_rerun_wins():
    success = dict(head_sha="abc", head_branch="main", event="push", run_number=1,
                   status="completed", conclusion="success")
    assert ci_status({"workflow_runs": [success]}, "abc") == "success"
    for field, value in (("head_sha", "other"), ("head_branch", "feature"), ("event", "pull_request")):
        assert ci_status({"workflow_runs": [dict(success, **{field: value})]}, "abc") == "pending"
    failed = dict(success, run_number=2, conclusion="failure")
    assert ci_status({"workflow_runs": [success, failed]}, "abc") == "failed"
    assert ci_status({"workflow_runs": [dict(success, status="in_progress")]}, "abc") == "pending"


def test_frontend_paths_exclude_backend_config_data_and_docs():
    assert frontend_changed(["frontend/src/Home.tsx"])
    assert frontend_changed(["deploy/nginx.conf"])
    assert not frontend_changed(["backend/config.py", ".env.deploy", "data/tep/file.dat", "docs/README.md"])


def test_failed_public_version_check_restores_original_image_and_only_web():
    calls = []
    def fail(_):
        raise RuntimeError("new web did not become available")
    with pytest.raises(RuntimeError):
        replace_web(calls.append, fail, "sha256:old", "candidate", "new-sha")
    assert calls[0] == ["docker", "tag", "candidate", "iron-man-web:latest"]
    assert calls[2] == ["docker", "tag", "sha256:old", "iron-man-web:latest"]
    assert calls[1] == calls[3]
    assert calls[1][-1] == "web" and "--no-deps" in calls[1]
