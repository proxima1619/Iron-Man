"""Pull successful main commits and replace only the production web container.

The EC2 timer runs this script as its Docker-enabled deployment user. It needs
no GitHub token: the repository and CI results are public. API/data/config are
kept in the separate production checkout. Failed builds keep the current web;
failed replacement restores the previous image.
"""
import argparse
import json
import logging
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY = "https://github.com/proxima1619/Iron-Man.git"
WORKFLOW = "https://api.github.com/repos/proxima1619/Iron-Man/actions/workflows/check.yml/runs"
FRONTEND_PATHS = ("frontend/", "deploy/Dockerfile.web", "deploy/nginx.conf")
LOG = logging.getLogger("frontend-deploy")


def command(args, cwd, timeout=60):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True,
                          check=True, timeout=timeout).stdout.strip()


def get_json(url):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "IronManFrontendDeploy",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def ci_status(runs, sha):
    matching = [r for r in runs.get("workflow_runs", [])
                if r.get("head_sha") == sha and r.get("head_branch") == "main"
                and r.get("event") == "push"]
    if not matching:
        return "pending"
    latest = max(matching, key=lambda r: (r.get("run_number", 0), r.get("run_attempt", 1)))
    if latest.get("status") != "completed":
        return "pending"
    return "success" if latest.get("conclusion") == "success" else "failed"


def frontend_changed(paths):
    return any(path.startswith("frontend/") or path in FRONTEND_PATHS[1:] for path in paths)


def write_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def replace_web(run, verify, old_image, candidate, sha):
    # Tag only after a successful candidate build. Restore on health/version failure.
    run(["docker", "tag", candidate, "iron-man-web:latest"])
    compose = ["docker", "compose", "--env-file", ".env.deploy", "-f", "compose.deploy.yaml",
               "up", "-d", "--no-deps", "--force-recreate", "--wait", "--wait-timeout", "90", "web"]
    try:
        run(compose)
        verify(sha)
    except Exception:
        run(["docker", "tag", old_image, "iron-man-web:latest"])
        run(compose)
        raise


def deploy(production, checkout, url, force=False):
    import fcntl  # Linux deployment only; pure selection/rollback checks are portable.
    if not re.fullmatch(r"https://[a-z0-9.-]+", url):
        raise ValueError("Use an HTTPS origin without credentials, path or port")
    private = production / ".deploy-private"
    private.mkdir(mode=0o700, exist_ok=True)
    with (private / "frontend-deploy.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state_path = private / "frontend-deploy-state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if not (checkout / ".git").exists():
            command(["git", "clone", "--no-checkout", REPOSITORY, str(checkout)], production, 120)
        command(["git", "fetch", "origin", "main"], checkout, 120)
        sha = command(["git", "rev-parse", "origin/main"], checkout)
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid commit ID")
        if sha == state.get("source_sha") and not force:
            return
        if (not force and state.get("pending_sha") == sha
                and time.time() - state.get("last_ci_check", 0) < 60):
            return
        query = urllib.parse.urlencode({"branch": "main", "event": "push", "head_sha": sha, "per_page": 5})
        status = ci_status(get_json(WORKFLOW + "?" + query), sha)
        state.update(pending_sha=sha, last_ci_check=time.time())
        write_state(state_path, state)
        if status != "success":
            LOG.info("Waiting for successful CI: %s (%s)", sha[:7], status)
            return
        previous = state.get("source_sha")
        if previous and not force:
            changed = command(["git", "diff", "--name-only", previous, sha], checkout).splitlines()
            if not frontend_changed(changed):
                state.update(source_sha=sha)
                write_state(state_path, state)
                return
        command(["git", "checkout", "--detach", sha], checkout)
        old_image = command(["docker", "inspect", "--format", "{{.Image}}", "iron-man-web-1"], production)
        candidate = "iron-man-web:ci-" + sha
        LOG.info("Building frontend from successful CI: %s", sha)
        command(["docker", "build", "-f", "deploy/Dockerfile.web", "--build-arg",
                 "IRON_MAN_WEB_COMMIT=" + sha, "-t", candidate, "."], checkout, 600)

        def verify(expected):
            for attempt in range(10):
                try:
                    if get_json(url + "/deployment.json").get("commit") == expected:
                        return
                except (OSError, ValueError):
                    pass
                time.sleep(2)
            raise RuntimeError("Public HTTPS did not serve the new frontend commit")

        replace_web(lambda args: command(args, production, 180), verify, old_image, candidate, sha)
        state.update(source_sha=sha, deployed_sha=sha, deployed_at=time.time())
        write_state(state_path, state)
        LOG.info("Frontend deployed and verified over public HTTPS: %s", sha)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", type=Path, default=Path("/opt/iron-man"))
    parser.add_argument("--checkout", type=Path, default=Path("/opt/iron-man-frontend"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--force", action="store_true", help="Rebuild even if only non-web files changed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        deploy(args.production.resolve(), args.checkout.resolve(), args.url.rstrip("/"), args.force)
    except Exception as error:
        # subprocess output may contain configuration; log only its type.
        LOG.error("Frontend deployment failed; previous version retained/restored (%s)", type(error).__name__)
        raise SystemExit(1)
