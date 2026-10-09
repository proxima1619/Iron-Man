"""Validate the effective public Compose configuration without printing secrets."""
import json
import os
from pathlib import Path
import subprocess
from backend.config import validate_runtime_config
from scripts.deploy_config import validate_domain


def check(config):
    services = config["services"]
    api, web, edge = (services[name] for name in ("api", "web", "caddy"))
    if api.get("ports") or web.get("ports"):
        raise ValueError("Only the HTTPS edge may publish ports")
    ports = {(str(p["published"]), int(p["target"]), p.get("host_ip", "0.0.0.0"))
             for p in edge["ports"]}
    if ports != {("80", 80, "0.0.0.0"), ("443", 443, "0.0.0.0")}:
        raise ValueError("Public edge must publish only TCP 80/443")
    environment = api["environment"]
    if environment.get("IRON_MAN_DEPLOYMENT") != "public":
        raise ValueError("Public runtime validation is disabled")
    # Restore the caller's environment even when validation fails.
    from unittest.mock import patch
    with patch.dict(os.environ, environment, clear=True):
        validate_runtime_config()
    validate_domain(edge["environment"]["DEMO_DOMAIN"])
    if edge["environment"].get("DEMO_ALIAS"):
        validate_domain(edge["environment"]["DEMO_ALIAS"])
    if edge["environment"]["DEMO_DOMAIN"] == "localhost":
        raise ValueError("Use a public DNS hostname for the deployed demo")
    if environment.get("IRON_MAN_EVIDENCE_MODE") not in {"fixture", "live"}:
        raise ValueError("Evidence mode must be fixture or live")
    if environment.get("IRON_MAN_EVIDENCE_MODE") == "live" and not all(
        environment.get(key) for key in ("OPENAI_API_KEY", "IRON_MAN_EVIDENCE_MODEL")
    ):
        raise ValueError("Live evidence mode requires server-side key and model")


if __name__ == "__main__":
    env_path = Path(".env.deploy")
    if not env_path.is_file() or env_path.stat().st_mode & 0o077:
        raise SystemExit(".env.deploy must exist and be readable only by its owner (chmod 600)")
    result = subprocess.run(["docker", "compose", "--env-file", str(env_path), "-f", "compose.deploy.yaml",
                             "config", "--format", "json"], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit("Compose config failed; check required settings and Compose >=2.24.4")
    try:
        check(json.loads(result.stdout))
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"Deployment check failed: {error}")
    print("PASS: private config, distinct role tokens, runtime validation, only 80/443 published")
