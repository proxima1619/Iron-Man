"""Start the local API with the repository's .env, without extra dependencies.

Supports literal single-line KEY=value and quoted values. No interpolation,
inline comments or shell execution. Loads only OPENAI_API_KEY and IRON_MAN_*
settings. Existing shell settings take precedence. Never prints secret values.
"""
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def load_local_env(path):
    if not path.exists():
        raise ValueError(".env is missing. Copy .env.example to .env first.")
    settings = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env syntax on line {number}; use KEY=value.")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid setting name on line {number}.")
        if name != "OPENAI_API_KEY" and not name.startswith("IRON_MAN_"):
            continue
        if name in settings:
            raise ValueError(f"Duplicate setting name on line {number}.")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed quoted value on line {number}.")
            value = value[1:-1]
        settings[name] = value
    for name, value in settings.items():
        os.environ.setdefault(name, value)


def main():
    try:
        load_local_env(ROOT / ".env")
        mode = os.environ.get("IRON_MAN_EVIDENCE_MODE", "fixture")
        if mode not in {"fixture", "live"}:
            raise ValueError("IRON_MAN_EVIDENCE_MODE must be fixture or live.")
        if mode == "live":
            missing = [name for name in ("OPENAI_API_KEY", "IRON_MAN_EVIDENCE_MODEL")
                       if not os.environ.get(name, "").strip()]
            if missing:
                raise ValueError("Configure these settings in .env: " + ", ".join(missing))
        source_mode = os.environ.get("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
        if source_mode not in {"local", "europepmc"}:
            raise ValueError("IRON_MAN_EVIDENCE_SOURCE_MODE must be local or europepmc.")
        if os.environ.get("IRON_MAN_DEPLOYMENT", "local") != "local":
            raise ValueError("This launcher is for local demos only.")
    except ValueError as exc:
        # Validation messages contain only fixed names and line numbers, never values.
        print("Cannot start:", str(exc), file=sys.stderr)
        return 1
    except OSError:
        print("Cannot start: .env could not be read.", file=sys.stderr)
        return 1
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    print("Local .env loaded. Evidence mode:", mode, "| source mode:", source_mode)
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
