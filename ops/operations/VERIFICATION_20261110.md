# 통합 CD 준비 검증 기록

앱 소스 변경 없음: 백엔드 기준 main 76bf57aaeee42e27b1f18ec4f096847a9e4de1a0 대비 src/build 설정 변경 0, 챗봇 기준 chatbot 037cf66daf8bf38589c6805f63ae47c2806dae8b 대비 AI/ 변경 0. 자동화 코드는 별도 Draft PR에만 게시했습니다.

- [백엔드 통합 준비 PR17](https://github.com/KW-coworker/JJIKMUK-Backend/pull/17)
- [챗봇 CD PR14](https://github.com/Alphrit/jjikmuk-CO-WORKER-/pull/14)
- [챗봇 기본 main 알림 PR15](https://github.com/Alphrit/jjikmuk-CO-WORKER-/pull/15)

## 검증 범위

- Linux CD/복구 검사 84개 통과 후 DB 열 길이/메타데이터 읽기 검사 1개 추가·해당 모듈 3개 통과. 최종 GitHub CI에서 총 85개 재확인 대상.
- 챗봇 패키지/배포 자동화 11개 통과. 정확한 원본 343개 파일 패키징 확인.
- 연결/비공개 업로드/승인/중단 검사 38개 통과. 실제 고정 SDK와 가짜 인증으로 지역 endpoint·서명·크기/체크섬 조건 검증. AWS 호출 없음.
- actionlint 3개 저장소 통과. cfn-lint 1.60.0 통과. 통합 템플릿 18,222 bytes, 최대 15개 리소스, SHA256 e7fa1e00e153f96e7f651f0eb4d9c35094a1ee8a5d4d786ec448d87c051bdec7.
- 스키마/런타임/RAG 비교 조건을 반전시킨 실험에서 검사 실패 확인 후 원본 바이트 복원·챗봇 자동화 검사 재통과.
- 독립 리뷰에서 변경 기록 저장 순서, 실패한 복구의 차단 유지, 실제 RAG 디렉터리 지문, 명시적 coordinator 설치, 대용량 host-state 읽기, 실제 S3 presign 주소 문제를 발견·보완.

## 실행 중 발견한 사항

Windows 체크아웃의 자동 CRLF 변환이 원본 해시와 RAG 참조 자료 검증을 깨뜨렸습니다. 기존 사본을 덮어쓰지 않고 LF 원본을 보존한 새 사본에서 검사했습니다. Windows 전용 파일 보안 API 차이도 있어 서버용 검사는 Linux에서 수행했습니다.

Linux 원본 전체 검사에서 3,359 PASS/1 대화 조회 인증 401 실패가 한 번 관찰됐습니다. 해당 모듈 단독 131 PASS였고, 앱/테스트 코드를 수정하지 않은 [GitHub 전체 검사](https://github.com/Alphrit/jjikmuk-CO-WORKER-/actions/runs/42640045711)는 성공했습니다. 첫 실패 원인은 확정되지 않았으며 이 이력을 삭제하거나 테스트 제외·조건 완화로 처리하지 않았습니다.

첫 백엔드 CI에서는 root 소유권 검사를 새로 적용한 host-state reader 때문에 일반 사용자 임시 폴더를 사용하는 crash fixture가 먼저 거절됐습니다. 복구 시나리오 테스트의 경로 신뢰 경계만 모의 처리하고, 실제 임시 폴더를 거절하는 독립 보안 검사를 추가했습니다. 운영 경로 검사는 유지합니다. 수정 후 Linux 전체 검사를 재실행했습니다.

## 아직 수행하지 않은 것

AWS 계정 API/설정 변경/SSM 명령/설치/서비스 재시작/DB SQL/유료 AI/실제 배포/운영 롤백/실제 알림 전송: 모두 0.

실제 서버의 Python 환경, RAG 디렉터리 변경 특성, DB 기준, 앱 간 API 호환성, 공개 URL 검사는 연결 후 별도 적용 승인 전에 확인해야 합니다. 모의 검사나 CI 통과를 운영 검증 완료로 해석하지 않습니다. 모든 PR은 Draft이며 CD 활성화 변수는 변경하지 않았습니다.
