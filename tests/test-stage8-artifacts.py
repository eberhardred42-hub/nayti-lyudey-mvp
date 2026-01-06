#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
ML_URL = os.environ.get("ML_URL", "http://localhost:8001")


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd, cwd=ROOT)


def wait_url(url: str, name: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{name} not ready: {url}")


def http_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        body = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body[:1000]}
        return e.code, parsed


def valid_profile_fixture() -> dict:
    return {
        "meta": {"contract_version": "v1", "kind": "vacancy_profile"},
        "role": {"title": "Senior Python Developer", "domain": "it", "seniority": "senior"},
        "company": {"name": None, "location": {"city": "Москва", "region": None, "country": "RU"}, "work_format": "hybrid"},
        "compensation": {"range": {"currency": "RUB", "min": 250000, "max": 350000}, "comment": "250–350k"},
    }


def main() -> None:
    print("[stage8] starting services (docker compose if available)")
    if shutil.which("docker"):
        # Best-effort cleanup: if a previous run left containers in a bad state
        # (e.g., after a port conflict), start from a clean slate.
        try:
            run(["docker", "compose", "-f", "infra/docker-compose.yml", "down", "--remove-orphans", "-v"])
        except Exception:
            pass
        run(["docker", "compose", "-f", "infra/docker-compose.yml", "up", "-d", "--build"])
        time.sleep(3)

    wait_url(f"{BACKEND_URL}/health", "api")
    wait_url(f"{ML_URL}/health", "ml")

    code, session_resp = http_json("POST", f"{BACKEND_URL}/sessions", {"profession_query": "stage8"})
    assert code == 200, session_resp
    session_id = session_resp.get("session_id")
    assert session_id, "missing session_id"

    code, job_resp = http_json("POST", f"{BACKEND_URL}/ml/job", {"session_id": session_id, "vacancy_profile": valid_profile_fixture()})
    assert code == 200, job_resp

    code, arts = http_json("GET", f"{BACKEND_URL}/artifacts?session_id={session_id}")
    assert code == 200, arts

    artifacts = arts.get("artifacts") or []
    assert artifacts, "no artifacts returned"

    assert any(a.get("kind") == "manifest" for a in artifacts), "manifest artifact missing"

    for a in artifacts:
        fmt = a.get("format")
        assert fmt is not None and fmt != "", f"format is missing for artifact: {a}"

    print("stage8 artifacts: OK")


if __name__ == "__main__":
    main()
