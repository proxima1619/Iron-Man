"""Fail startup if an externally deployed server still uses local demo secrets."""
import os
import re


def validate_runtime_config():
    mode = os.getenv("IRON_MAN_DEPLOYMENT", "local")
    if mode not in {"local", "public"}:
        raise ValueError("IRON_MAN_DEPLOYMENT must be local or public")
    if mode == "local":
        return
    tokens = [os.getenv(name, "") for name in
              ("IRON_MAN_OPERATOR_TOKEN", "IRON_MAN_APPROVER_TOKEN")]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) for token in tokens):
        raise ValueError("Public deployment requires two generated role tokens (32..128 characters)")
    if tokens[0] == tokens[1]:
        raise ValueError("Operator and approver tokens must be different")
