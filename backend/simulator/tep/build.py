"""Explicit, offline build of the pinned external TE core. Never builds in an HTTP worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / ".tep-cache" / "engine"
FLAGS = ["-std=c++17", "-O2", "-fno-fast-math"]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_lock():
    lock = json.loads((ROOT / "source.lock.json").read_text(encoding="utf-8"))
    for name, expected in lock["files"].items():
        if sha(ROOT / "vendor" / name) != expected:
            raise ValueError(f"Pinned TE source checksum mismatch: {name}")
    return lock

def launcher():
    return ["wsl", "-d", os.getenv("IRON_MAN_TEP_WSL_DISTRO", "Ubuntu"), "--exec"] if os.name == "nt" else []

def engine_path(path):
    absolute = str(Path(path).resolve())
    if os.name != "nt":
        return absolute
    return subprocess.check_output(launcher() + ["wslpath", "-a", "-u", absolute], text=True, timeout=15).strip()

def build(output=DEFAULT_OUTPUT):
    lock = source_lock()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    prefix = launcher()
    binary = output / "tep-runner"
    command = prefix + ["g++", *FLAGS, engine_path(ROOT / "runner.cpp"),
                        engine_path(ROOT / "vendor" / "teprob.cpp"), "-o", engine_path(binary)]
    subprocess.run(command, check=True, timeout=120)
    manifest = {"source_commit": lock["commit"], "source_files_sha256": lock["files"],
                "wrapper_sha256": sha(ROOT / "runner.cpp"), "binary_sha256": sha(binary),
                "compiler": subprocess.check_output(prefix + ["g++", "--version"], text=True, timeout=15).splitlines()[0],
                "compiler_flags": FLAGS,
                "platform": subprocess.check_output(prefix + ["uname", "-sm"], text=True, timeout=15).strip(),
                "build_host": platform.platform()}
    (output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
