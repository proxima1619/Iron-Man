import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.config import validate_runtime_config
from scripts import deploy_config, deploy_check


@pytest.mark.parametrize("operator,approver", [
    ("local-operator", "local-approver"), ("", ""), ("a" * 40, "a" * 40),
    ("a" * 40, "short"), ("a" * 40, "b" * 31),
])
def test_public_startup_rejects_weak_or_duplicate_tokens(monkeypatch, operator, approver):
    monkeypatch.setenv("IRON_MAN_DEPLOYMENT", "public")
    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", operator)
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", approver)
    with pytest.raises(ValueError), TestClient(main.app):
        pass


def test_public_runtime_config_accepts_generated_tokens(monkeypatch):
    monkeypatch.setenv("IRON_MAN_DEPLOYMENT", "public")
    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", "o" * 43)
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", "a" * 43)
    validate_runtime_config()


def test_header_role_auth_and_bearer_compatibility(monkeypatch):
    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", "operator-test")
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", "approver-test")
    assert main.identity(x_iron_man_token="operator-test") == "operator"
    assert main.identity(authorization="Bearer approver-test") == "approver"
    assert main.identity(authorization="Basic ZGVtbzpwYXNz", x_iron_man_token="operator-test") == "operator"
    from fastapi import HTTPException
    for args in ({}, {"authorization": "Basic ZGVtbzpwYXNz"},
                 {"authorization": "operator-test"}, {"x_iron_man_token": "잘못된토큰"},
                 {"authorization": "Bearer approver-test", "x_iron_man_token": "operator-test"}):
        with pytest.raises(HTTPException) as error:
            main.identity(**args)
        assert error.value.status_code == 401


def test_empty_config_never_authenticates_empty_headers(monkeypatch):
    monkeypatch.setenv("IRON_MAN_OPERATOR_TOKEN", "")
    monkeypatch.setenv("IRON_MAN_APPROVER_TOKEN", "")
    with pytest.raises(Exception) as error:
        main.identity(x_iron_man_token="")
    assert error.value.status_code == 401


def test_generated_credentials_are_private_distinct_and_not_overwritten(tmp_path, monkeypatch, capsys):
    hashed = "$2a$14$" + "a" * 53
    monkeypatch.setattr(deploy_config, "hash_password", lambda password: hashed)
    env, access = deploy_config.generate("demo.example.com", tmp_path)
    data = json.loads(access.read_text())
    assert len({data["password"], data["operator_token"], data["approver_token"]}) == 3
    assert min(len(data[key]) for key in ("password", "operator_token", "approver_token")) >= 32
    assert data["password"] not in env.read_text()
    assert f"DEMO_PASSWORD_HASH='{hashed}'" in env.read_text()
    # Windows stat mode bits do not describe NTFS ACLs. Check POSIX modes
    # on the Linux deployment platform; credential behavior is tested on both.
    if os.name == "posix":
        assert env.stat().st_mode & 0o777 == access.stat().st_mode & 0o777 == 0o600
        assert access.parent.stat().st_mode & 0o777 == 0o700
    old = env.read_bytes()
    with pytest.raises(FileExistsError):
        deploy_config.generate("demo.example.com", tmp_path)
    assert env.read_bytes() == old and not capsys.readouterr().out


@pytest.mark.parametrize("domain", ["https://demo.example.com", "host:443", "bad\nrespond hi", "../file", "*.example.com"])
def test_domain_cannot_inject_caddy_configuration(domain):
    with pytest.raises(ValueError):
        deploy_config.validate_domain(domain)


def effective_config():
    return {"services": {
        "api": {"environment": {"IRON_MAN_DEPLOYMENT": "public", "IRON_MAN_OPERATOR_TOKEN": "o" * 43,
                "IRON_MAN_APPROVER_TOKEN": "a" * 43, "IRON_MAN_EVIDENCE_MODE": "fixture"}},
        "web": {},
        "caddy": {"ports": [{"published": "80", "target": 80}, {"published": "443", "target": 443}],
                  "environment": {"DEMO_DOMAIN": "demo.example.com"}},
    }}


def test_preflight_rejects_direct_web_port_or_insecure_live_config():
    config = effective_config()
    before = dict(os.environ)
    deploy_check.check(config)
    assert dict(os.environ) == before
    config["services"]["web"]["ports"] = [{"target": 8080, "published": "8080"}]
    with pytest.raises(ValueError, match="Only the HTTPS edge"):
        deploy_check.check(config)
    config = effective_config()
    config["services"]["api"]["environment"]["IRON_MAN_EVIDENCE_MODE"] = "live"
    with pytest.raises(ValueError, match="key and model"):
        deploy_check.check(config)


def test_private_paths_are_ignored_by_git_and_docker():
    root = Path(__file__).resolve().parents[1]
    for filename in (".gitignore", ".dockerignore"):
        rules = (root / filename).read_text().splitlines()
        assert ".env.*" in rules
        assert any(rule.rstrip("/") == ".deploy-private" for rule in rules)


def test_aws_bootstrap_matches_template_and_no_public_app_port():
    root = Path(__file__).resolve().parents[1]
    template = json.loads((root / "deploy/aws/template.json").read_text())
    resources = template["Resources"]
    server = resources["Server"]["Properties"]
    assert server["UserData"]["Fn::Base64"] == (root / "deploy/aws/bootstrap.sh").read_text()
    assert server["MetadataOptions"]["HttpTokens"] == "required"
    assert server["BlockDeviceMappings"][0]["Ebs"]["Encrypted"] is True
    ingress = resources["SecurityGroup"]["Properties"]["SecurityGroupIngress"]
    public = {rule["FromPort"] for rule in ingress if rule["CidrIp"] == "0.0.0.0/0"}
    assert public == {80, 443}
    assert next(rule for rule in ingress if rule["FromPort"] == 22)["CidrIp"] == {"Ref": "AdminCidr"}
