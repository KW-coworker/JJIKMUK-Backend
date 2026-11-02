# 백엔드 v2 인증·라이브러리 보완 검증 (2026-11-02)

기준 main `8b34dd2a512a588dc99faa44286515630aa229e2`(OCR PR #7 병합 후). AI 비교 대상은 `Alphrit/jjikmuk-CO-WORKER-`의 `chatbot` 커밋 `17cb7b4f26f1f9656a680a77cbf0f88a7b24989d`. main 병합·AWS 반영 완료 보고가 아니다.

| 검사 | 결과 |
|---|---|
| 인증 연결 후, 라이브러리 변경 전 전체 검사 | 347개: 통과 341 / 기존 skip 6 / 실패·오류 0 |
| 추가 경계 검사 및 라이브러리 보정 후 전체 검사 | 351개: 통과 345 / 기존 skip 6 / 실패·오류 0 |
| `bootJar` | 성공. Tomcat 11.0.25, Jackson 2.21.7/3.1.7, Guava 33.7.2-jre 실제 포함 확인 |
| Kotlin 실제 HTTP 바이트 → Python 검증기·FastAPI | 0/1/2/21명, 동의 ON/OFF/생략/null, 5개 경우 모두 200. 개인별 profileKey·판정 동일 |
| 부정 사례 | 서명 본문 변경·재사용·만료 거절; 내부 토큰 오류 401, context 불일치 422; 앱의 계정/동의 헤더 위조 무시 |
| JSON 동의 | boolean true만 승인. 문자열·숫자 거절; false/생략/null은 거부 |
| 인증·크기·HTTP 경계 | 설정 누락 503, 1 MiB 초과 413, 응답 계약 불일치 차단, 실제 로컬 HTTP 리다이렉트로 비밀 전달 0회 |
| 검사 유효성 | 토큰 유효성 조건을 반전하면 AiChatClient 검사 14개 실패. 원본 바이트로 복원 후 최종 재검사 |
| 의존성 | 해석된 외부 모듈 124개(플랫폼/BOM 포함), 변경 78개. 공개 OSV 버전 일치: 전 69개 advisory/20개 패키지 → 후 0개 |

백엔드 전체 검사는 H2·로컬 HTTP·모의 외부 서비스 기반이다. OCR 29개 검사와 최신 JWT/Refresh/프로필·상품/검색 등 기존 검사를 포함한다. **실제 Google OAuth, 실서비스 MySQL migration, APK UI, AWS 통합, 외부 생성/임베딩은 실행하지 않았다.** 버전 일치 취약점 수는 실제 공격 가능성 측정이 아니다.

Python의 추가 원본 검사 `test_backend_analysis_v2.py` + `test_backend_consent_contract.py`에서는 **92개 통과, RAG 5개 환경 제약으로 실패**했다. Windows는 안전한 디렉터리 파일 열기 기능 미지원, 별도 Linux 최소 테스트 환경은 langchain_chroma 등 RAG 패키지 미설치다. AI 코드나 보호 검사를 고쳐 성공 처리하지 않았다. 해당 5개와 실제 동의 ON RAG 생성 품질은 완전한 Linux AI 환경에서 별도 확인해야 하며, 챗봇 전체 검사 통과를 주장하지 않는다.

재현 방법과 운영 설정은 [연동 안내](chat-v2-runtime-integration.md), 라이브러리 변경 이유·공식 출처는 [의존성 안내](runtime-dependencies.md) 참조. 한도·nonce 저장소·AI 모델·DB·서버 설정·기존 OCR 소스와 로그인 소스는 변경하지 않았다. 새 설정 비밀값은 소스에 저장하지 않는다.

향후 배포에서는 기존 AI가 v2를 실제 지원하는지와 필요한 설정이 존재하는지 확인한 뒤 진행한다. 이 PR을 병합하기만 해도 현재 AWS의 AI 버전이 자동으로 갱신되지는 않는다.
