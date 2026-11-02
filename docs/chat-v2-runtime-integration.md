# 챗봇 v2 운영 인증 연결

기존 v2 `ChatService`가 만든 판정·profileKey·선택 정보를 그대로 `AiChatClient`로 보내면서, AI가 요구하는 내부 인증과 외부 AI 동의 증명을 추가한다. 예전 `OperationalChatService` 경로를 복사하거나 개인별 결과를 지우지 않는다.

## 요청과 설정

- 앱은 `POST /api/chat`에 기존 로그인 Bearer와 `externalAiConsent: true|false`를 보낸다. 생략/null은 false, 문자열·숫자는 400이다. 요청의 다른 필드와 프로필 선택 규칙은 기존 v2 계약을 따른다.
- 서명의 계정은 JWT owner ID다. 선택한 가족 ID나 요청의 프로필 id가 아니다. 최종 UTF-8 JSON을 한 번 직렬화해 그 바이트 전체를 해시·서명하고 같은 바이트를 보낸다.
- `X-Food-Chatbot-Token`, 기존 두 v2 확인 헤더, v1 HMAC-SHA256 동의 헤더 5개를 전달한다. v2 분석 계약과 v1 서명 버전은 별개다.
- 누락/잘못된 내부 토큰 또는 서명 키 설정은 외부 호출 전 `503 AI_AUTH_UNAVAILABLE`. 동의 OFF도 유효한 서명 키가 필요하다. 동의를 임의로 true로 만들거나 서명 없이 전송하는 우회는 없다.
- 본문 1 MiB 초과는 `413 AI_REQUEST_TOO_LARGE`, 응답 버전/contextId 불일치는 기존 `502 AI_ANALYSIS_CONTRACT_MISMATCH`다. 자동 재시도·HTTP 리다이렉트 전달은 하지 않는다.

| 백엔드 설정 | 환경변수 | AI 측 대응 |
|---|---|---|
| `chat.ai.url` | `CHAT_AI_URL` | 신뢰하는 AI의 정확한 `/chat` 주소 |
| `chatbot.api-token` | `CHATBOT_API_TOKEN` | `FOOD_CHATBOT_API_TOKEN`과 동일 |
| `chatbot.external-ai-consent-secret` | `CHATBOT_EXTERNAL_AI_CONSENT_SECRET` | `FOOD_CHATBOT_EXTERNAL_AI_CONSENT_SECRET`과 동일 |

토큰·서명 키는 서로 다른 기존 운영 값을 서버의 비밀 설정에 유지한다. 키는 공백 없는 ASCII 32자 이상이다. 공개 네트워크에서는 HTTPS를 사용하고, HTTP는 접근 통제된 loopback/사설망에서만 사용한다. 실제 값은 GitHub/앱/로그에 넣지 않는다. 키를 바꾸거나 새 키를 발급하는 PR이 아니다.

이 경로는 main의 v2 단일 경로다. 예전 로컬 운영 코드의 `chatbot.mode`, `chatbot.enabled` 설정이 이 경로를 전환한다고 가정하지 않는다. 배포 전에 `chat.ai.url`과 위 두 비밀 설정을 확인해야 한다. 기존 AI의 외부 호출 운영 스위치, 동의 검증·nonce·호출 누계·DB는 별도로 유지한다.

## 재현 검사

대조한 AI: `Alphrit/jjikmuk-CO-WORKER-`의 `chatbot`, 커밋 `17cb7b4f26f1f9656a680a77cbf0f88a7b24989d`, `AI/`.

```text
./gradlew test bootJar
python tools/verify_chatbot_v2.py --ai-root /path/to/clean/chatbot-checkout/AI
```

두 번째 명령은 AI의 테스트용 Python 환경에서 실행한다. 첫 명령의 `ChatSignedTransportIntegrationTest`가 실제 JWT→H2 분석→로컬 HTTP로 생성한 **합성** 요청 바이트와 서명을 그대로 검증한다. 실제 Python 검증기와 FastAPI ASGI 라우트를 사용하며 운영 DB·API 키는 사용하지 않는다. 외부 소켓 연결을 차단한다. 결과는 `build/integration/python-v2-compatibility.json`.

범위: 0/1/2/21명, 동의 ON/OFF/누락/null, 동일 이름·동일 로컬 ID, 본문 바이트 변경·만료·재사용 거절, 잘못된 내부 토큰/분석 context 거절, 개인별 판정 보존. 실제 외부 LLM/RAG 호출·AWS·앱 UI 품질 검사는 아니다. AI의 상품/프로필 텍스트 한도는 계속 적용되며 긴 DB 라벨을 임의로 잘라 보내지 않는다.

## 적용 순서

PR 검토·main 병합 후 별도 배포 승인이 필요하다. AI v2 커밋과 운영 설정을 먼저 검증하고 백엔드 main을 원본 그대로 빌드·배포한다. 기존 OCR, 로그인, 메일, Google, DB 스키마, 외부 호출 누계는 이 변경에서 수정하지 않는다. 이 문서와 테스트 성공만으로 서버 배포나 유료 호출 완료를 뜻하지 않는다.
