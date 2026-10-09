"""Check public HTTPS access, API role authentication and real evaluation.

Reads credentials from a private JSON file; never prints them. Default TLS trust
is the system CA store. --ca-file is for the CI-local Caddy test CA only.
"""
import argparse
import json
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


def run(access, ca_file=None, http_url=None):
    base = access["url"].rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.path:
        raise ValueError("Test URL must be an HTTPS origin without embedded credentials")
    context = ssl.create_default_context(cafile=ca_file)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    # Send no credentials over HTTP. Confirm the edge redirects to HTTPS.
    try:
        response = urllib.request.build_opener(NoRedirect()).open(
            http_url or f"http://{parsed.hostname}/", timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status in {301, 308}
        location = urllib.parse.urlsplit(response.headers["Location"])
        assert location.scheme == "https" and location.hostname == parsed.hostname
    def request(path, *, token=None, body=None, auth=None):
        headers = {}
        if auth:
            headers["Authorization"] = auth
        if token:
            headers["X-Iron-Man-Token"] = token
        if body is not None:
            headers["Content-Type"] = "application/json"
        data = None if body is None else json.dumps(body).encode()
        try:
            response = urllib.request.urlopen(urllib.request.Request(base + path, headers=headers, data=data),
                                              context=context, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    assert request("/", auth="Basic ZGVtbzppbmNvcnJlY3Q=")[0] == 200
    status, html = request("/")
    assert status == 200 and b'<div id="root"></div>' in html
    assert request("/api/requests")[0] == 401
    assert request("/api/requests", token="incorrect")[0] == 401
    assert request("/api/requests", token=access["operator_token"])[0] == 200
    assert request("/api/health")[0] == 200
    operator, approver = access["operator_token"], access["approver_token"]
    from scripts.tep_smoke import run as run_tep
    def tep_request(path, *, token, body=None):
        status, raw = request("/api" + path, token=token, body=body)
        return status, json.loads(raw)
    run_tep(tep_request, operator, approver)
    assert request("/api/state", token=operator)[0] == 200
    assert request("/api/demo/reset", token=approver, body={})[0] == 200
    for speed, verdict in ((60, "blocked"), (80, "awaiting_approval")):
        if speed == 80:
            assert request("/api/demo/state", token=approver, body={"load_ratio": .6})[0] == 200
        status, body = request("/api/requests", token=operator,
                               body={"command": {"target_pct": speed}, "purpose": "HTTPS deployment smoke"})
        assert status == 201
        row = json.loads(body)
        path = f'/api/requests/{row["id"]}'
        status, body = request(path + "/evaluate", token=operator, body={})
        assert status == 202 and json.loads(body)["status"] == "evaluating"
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            status, body = request(path, token=operator)
            assert status == 200
            row = json.loads(body)
            if row["status"] != "evaluating":
                break
            time.sleep(0.2)
        assert row["status"] == verdict
        assert row["report"]["can_approve"] == (speed == 80)
        decision = {"decision": "approve", "reason": "smoke test must not override policy",
                    "report_digest": row["report"]["digest"]}
        assert request(path + "/decisions", token=operator, body=decision)[0] == 403
        if speed == 60:
            assert request(path + "/decisions", token=approver, body=decision)[0] == 409
        else:
            execution = {"report_digest": row["report"]["digest"]}
            assert request(path + "/execute", token=operator, body=execution)[0] == 409
            assert request(path + "/decisions", token=approver, body=decision)[0] == 200
            status, body = request(path + "/execute", token=operator, body=execution)
            applied = json.loads(body)
            assert status == 200 and applied["execution"]["virtual"] is True
            assert applied["execution"]["state"]["target_pump_speed_pct"] == 80
            assert json.loads(request(path + "/execute", token=operator, body=execution)[1]) == applied
    status, body = request("/api/demo/advance", token=approver, body={"seconds_s": 10})
    moved = json.loads(body)
    assert status == 200 and 80 < moved["pump_speed_pct"] < 100 and moved["temperature_c"] < 60
    assert request("/api/demo/state", token=approver, body={"load_ratio": 1, "sensor_quality": "invalid"})[0] == 200
    status, body = request("/api/requests", token=operator, body={"command": {"target_pct": 80}})
    assert status == 201
    path = f'/api/requests/{json.loads(body)["id"]}'
    assert request(path + "/evaluate", token=operator, body={})[0] == 202
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        row = json.loads(request(path, token=operator)[1])
        if row["status"] != "evaluating":
            break
        time.sleep(.2)
    assert row["status"] == "hold" and row["report"]["reason_code"] == "INVALID_STATE"
    assert row["report"]["can_approve"] is False
    # Restore a fresh starting point before the independent browser smoke test.
    assert request("/api/demo/reset", token=approver, body={})[0] == 200
    print("PASS: public trusted HTTPS, API role auth, blocked/held requests, human approval, virtual application and clock")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-file", type=Path, default=Path(".deploy-private/access.json"))
    parser.add_argument("--ca-file")
    parser.add_argument("--http-url", help="HTTP redirect origin override for CI")
    parser.add_argument("--url", help="Override test origin (CI uses a nonstandard port)")
    args = parser.parse_args()
    access = json.loads(args.access_file.read_text())
    if args.url:
        access["url"] = args.url
    run(access, args.ca_file, args.http_url)
