"""Read local AI code; probe synthetic backend payload without external calls or DB writes."""
import argparse
import copy
import json
import os
import ipaddress
from pathlib import Path
import socket
import sys
from unittest.mock import patch


_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_create_connection = socket.create_connection


def check_loopback(address):
    # Windows asyncio uses a loopback socket pair internally.
    try:
        allowed = ipaddress.ip_address(address[0]).is_loopback
    except (ValueError, TypeError, IndexError):
        allowed = False
    if not allowed:
        raise RuntimeError("External network disabled by the isolated integration harness")


def loopback_connect(sock, address):
    check_loopback(address)
    return _connect(sock, address)


def loopback_connection(address, *args, **kwargs):
    check_loopback(address)
    return _create_connection(address, *args, **kwargs)


def loopback_connect_ex(sock, address):
    check_loopback(address)
    return _connect_ex(sock, address)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-root", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pytest-xml", type=Path)
    args = parser.parse_args()
    for key in list(os.environ):
        if "API_KEY" in key or key in {"FOOD_CHATBOT_DB_PATH", "LLM_API_URL"}:
            os.environ.pop(key, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.ai_root.resolve()))
    import dotenv
    from fastapi.testclient import TestClient
    payload = json.loads(args.samples.read_text(encoding="utf-8"))["aiRequest"]
    report = {"externalNetworkAllowed": False, "database": "in-memory repositories",
              "realLlmTested": False, "checks": []}
    with patch.object(dotenv, "load_dotenv", return_value=False), \
         patch.object(socket.socket, "connect", loopback_connect), \
         patch.object(socket.socket, "connect_ex", loopback_connect_ex), \
         patch.object(socket, "create_connection", loopback_connection):
        from app.api.main import app
        from app.core.models import ChatRequest
        from app.infrastructure.repository import InMemoryActivityRepository, InMemoryProductRepository
        from app.services.activity import set_activity_repository
        from app.services.product import set_product_repository
        set_activity_repository(InMemoryActivityRepository())
        set_product_repository(InMemoryProductRepository())
        headers = {"X-Jjikmuk-Analysis-Contract": payload["analysisContext"]["contractVersion"],
                   "X-Jjikmuk-Analysis-Context": payload["analysisContext"]["contextId"]}
        with TestClient(app) as client:
            for name, changed in [("exact_backend_payload", False), ("diagnostic_profiles_empty_array", True)]:
                candidate = copy.deepcopy(payload)
                if changed:
                    candidate["profiles"] = []
                response = client.post("/chat", json=candidate, headers=headers)
                data = response.json()
                check = {"name": name, "httpStatus": response.status_code,
                         "contractAcknowledged": response.headers.get("X-Jjikmuk-Analysis-Contract") == headers["X-Jjikmuk-Analysis-Contract"],
                         "contextAcknowledged": response.headers.get("X-Jjikmuk-Analysis-Context") == headers["X-Jjikmuk-Analysis-Context"],
                         "validationErrors": [{"loc": e.get("loc"), "type": e.get("type")} for e in data.get("detail", [])] if isinstance(data.get("detail"), list) else [],
                         "responseKeys": sorted(data.keys())}
                if response.status_code == 200:
                    normalized = ChatRequest.model_validate(candidate).model_dump()
                    check["analysisContextPreserved"] = "analysisContext" in normalized
                    check["riskLevel"] = data.get("risk_level")
                report["checks"].append(check)
        if args.pytest_xml:
            import pytest
            args.pytest_xml.parent.mkdir(parents=True, exist_ok=True)
            report["pytestExitCode"] = pytest.main([str(args.ai_root / "tests"), "-q", "-p", "no:cacheprovider", f"--junitxml={args.pytest_xml}"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
