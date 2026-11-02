"""Check real Kotlin HTTP bytes against the unchanged AI checkout, with no external network.

Run ChatSignedTransportIntegrationTest first. Requires the chatbot's Python test environment.
Only consumes synthetic build/integration/signed-chat-requests.json, never operational credentials.
"""
import argparse
import base64
import json
import os
import ipaddress
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ai-root", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
ai = args.ai_root.resolve()
expected_commit = "17cb7b4f26f1f9656a680a77cbf0f88a7b24989d"
commit = subprocess.check_output(["git", "-c", f"safe.directory={ai.parent.as_posix()}", "-C", str(ai), "rev-parse", "HEAD"], text=True).strip()
assert commit == expected_commit, "Review the AI contract before changing its pinned revision"
assert not (ai / ".env").exists(), "Use a clean AI checkout without private configuration"
captures = json.loads((root / "build/integration/signed-chat-requests.json").read_text(encoding="utf-8"))
os.environ.update(FOOD_CHATBOT_ENV="test", FOOD_CHATBOT_DB_PROVIDER="memory",
    FOOD_CHATBOT_API_TOKEN="public-internal-test-token",
    FOOD_CHATBOT_EXTERNAL_AI_CONSENT_SECRET="public-consent-test-secret-not-production",
    FOOD_CHATBOT_ENABLE_EXTERNAL_AI="false", OPENAI_API_KEY="",
    FOOD_CHATBOT_ENABLE_CONVERSATIONS="false", FOOD_CHATBOT_ENABLE_RATE_LIMIT="false",
    FOOD_CHATBOT_STORE_RAW_MESSAGES="false")
sys.path.insert(0, str(ai))

def deny_network(*args, **kwargs):
    raise AssertionError("No network access permitted in compatibility verification")

original_connect = socket.socket.connect
def loopback_only(sock, address):
    # Windows asyncio creates a loopback socketpair even for in-process ASGI.
    if isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback:
        return original_connect(sock, address)
    return deny_network()

report = {"aiCommit": commit, "scope": "Kotlin loopback captures -> real Python verifier + FastAPI ASGI, synthetic data", "cases": []}
with patch.object(socket.socket, "connect", loopback_only), patch.object(socket, "create_connection", deny_network):
    from fastapi.testclient import TestClient
    from app.api.main import app
    from app.infrastructure import external_ai_consent as consent
    from app.infrastructure.repository import InMemoryProductRepository, InMemoryActivityRepository
    from app.services import product, activity
    product._default_repository = InMemoryProductRepository()
    activity.set_activity_repository(InMemoryActivityRepository())
    with TestClient(app) as client:
        for capture in captures:
            body = base64.b64decode(capture["bodyBase64"])
            payload = json.loads(body)
            headers = {k.lower(): v for k,v in capture["headers"].items() if k.lower().startswith("x-")}
            headers["content-type"] = "application/json"
            stamp = int(headers[consent.TIMESTAMP_HEADER])
            consent.reset_external_ai_consent_nonce_registry()
            def verify(data=body, proof=headers, now=stamp):
                return consent.verify_external_ai_consent(headers=proof, method="POST", path="/chat", body=data,
                    operator_enabled=True, now=now)
            proof = verify()
            assert proof.verified and proof.user_id == str(capture["ownerId"])
            assert proof.allowed == (headers[consent.CONSENT_HEADER] == "granted")
            assert not verify().verified, "Repeated proof must fail"
            consent.reset_external_ai_consent_nonce_registry()
            assert not verify(body + b" ").verified, "Even equivalent reserialized JSON must fail"
            assert not verify(now=stamp+1000).verified, "Expired proof must fail"
            consent.reset_external_ai_consent_nonce_registry()
            response = client.post("/chat", content=body, headers=headers)
            assert response.status_code == 200, (capture["case"], response.status_code, response.text)
            result = response.json()
            context = payload["analysisContext"]
            assert response.headers["X-Jjikmuk-Analysis-Contract"] == "chat-analysis-v2"
            assert response.headers["X-Jjikmuk-Analysis-Context"] == context["contextId"]
            expected = {p["profileKey"]: p["analysis"]["status"] for p in context["profileAnalyses"]}
            actual = {p["profileKey"]: p["backend_status"] for p in result["per_profile_results"]}
            assert expected == actual, (expected, actual)
            assert len(result["per_profile_results"]) == len(expected)
            assert result["answer_source"] == "backend"
            assert client.post("/chat", content=body, headers={**headers,"x-food-chatbot-token":"wrong"}).status_code == 401
            assert client.post("/chat", content=body, headers={**headers,"x-jjikmuk-analysis-context":"stale"}).status_code == 422
            report["cases"].append({"case":capture["case"], "status":200, "people":len(actual),
                "signatureVerified":True, "granted":proof.allowed, "negativeProofChecks":3,
                "wrongToken":401, "wrongContext":422})
output = root / "build/integration/python-v2-compatibility.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
