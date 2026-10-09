"""Generate private API role tokens; the website itself has no login.

Run on the deployment server: python3 -m scripts.deploy_config --domain demo.example.com
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets


def validate_domain(domain):
    if len(domain) > 253 or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", domain
    ):
        raise ValueError("Use a lowercase DNS hostname without scheme, port or path")


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
    operator, approver = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink():
        raise ValueError("Private credentials directory must not be a symlink")
    private.chmod(0o700)
    access = {"url": f"https://{domain}", "operator_token": operator, "approver_token": approver}
    values = {"DEMO_DOMAIN": domain, "DEMO_ALIAS": "",
              "IRON_MAN_OPERATOR_TOKEN": operator, "IRON_MAN_APPROVER_TOKEN": approver,
              "IRON_MAN_EVALUATION_WORKERS": "2", "IRON_MAN_EVALUATION_TIMEOUT_S": "90",
              "IRON_MAN_EVIDENCE_MODE": "fixture", "OPENAI_API_KEY": "",
              "IRON_MAN_EVIDENCE_MODEL": "", "IRON_MAN_EVIDENCE_TIMEOUT_S": "20"}
    # Keep the token file private and avoid shell interpolation in dotenv values.
    write_private(env_path, "".join(f"{key}='{value}'\n" for key, value in values.items()))
    write_private(access_path, json.dumps(access, indent=2) + "\n")
    return env_path, access_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    try:
        env, access = generate(args.domain)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Setup failed: {error}\n")
    print(f"Created private files: {env}, {access}. Keep both out of Git and shared logs.")
