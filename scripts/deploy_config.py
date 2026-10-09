"""Generate deployment credentials locally; never print secrets or overwrite files.

Run on the deployment server: python3 -m scripts.deploy_config --domain demo.example.com
Docker is required only to produce the Caddy bcrypt password hash.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

CADDY_IMAGE = "caddy:2.10-alpine"


def validate_domain(domain):
    if len(domain) > 253 or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", domain
    ):
        raise ValueError("Use a lowercase DNS hostname without scheme, port or path")


def hash_password(password):
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", CADDY_IMAGE, "caddy", "hash-password"],
        input=password + "\n", text=True, capture_output=True, timeout=120,
    )
    hashed = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}", hashed):
        raise RuntimeError("Caddy password hashing failed; check the Docker engine and image access")
    return hashed


def write_private(path, contents):
    # Exclusive creation prevents accidental rotation and symlink overwrite.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        file.write(contents)


def generate(domain, root=Path(".")):
    validate_domain(domain)
    env_path = root / ".env.deploy"
    private = root / ".deploy-private"
    access_path = private / "access.json"
    if env_path.exists() or access_path.exists():
        raise FileExistsError("Deployment credentials already exist; no files were changed")
    password = secrets.token_urlsafe(24)
    hashed = hash_password(password)
    operator, approver = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink():
        raise ValueError("Private credentials directory must not be a symlink")
    private.chmod(0o700)
    access = {"url": f"https://{domain}", "username": "demo", "password": password,
              "operator_token": operator, "approver_token": approver}
    values = {"DEMO_DOMAIN": domain, "DEMO_USER": "demo", "DEMO_PASSWORD_HASH": hashed,
              "IRON_MAN_OPERATOR_TOKEN": operator, "IRON_MAN_APPROVER_TOKEN": approver,
              "IRON_MAN_EVALUATION_WORKERS": "2", "IRON_MAN_EVALUATION_TIMEOUT_S": "90",
              "IRON_MAN_EVIDENCE_MODE": "fixture", "OPENAI_API_KEY": "",
              "IRON_MAN_EVIDENCE_MODEL": "", "IRON_MAN_EVIDENCE_TIMEOUT_S": "20"}
    # Single quotes preserve bcrypt '$' characters in Docker Compose dotenv syntax.
    write_private(env_path, "".join(f"{key}='{value}'\n" for key, value in values.items()))
    write_private(access_path, json.dumps(access, indent=2) + "\n")
    return env_path, access_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    try:
        env, access = generate(args.domain)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Setup failed: {error}\n")
    print(f"Created private files: {env}, {access}. Keep both out of Git and shared logs.")
