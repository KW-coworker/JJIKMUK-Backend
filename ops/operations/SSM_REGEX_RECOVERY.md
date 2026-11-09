# SSM 문서 생성 오류 보완

## 2026-11-10 미실행 복구 미리보기의 태그 누락 보완

첫 복구는 `UNEXPECTED_CHANGE_COUNT`로 실행 전에 중단됐습니다. 실제 미리보기에는
실패한 문서 2개 외에 기존 자원 13개의 `Tags` 변경이 있었습니다. 최초 생성 요청은
`Project=JJIKMUK`를 지정했지만 복구 `create_change_set`에는 `Tags`가 누락됐습니다.
기존 13개는 `Replacement=False`, 문서 2개는 부재 확인 후 생성 대상입니다.

보완본은 원래 태그가 그대로 있는지 먼저 검사하고 동일 태그를 명시하여 새 미리보기를
만듭니다. 새 미리보기에는 **문서 2개만** 허용합니다. 태그 변경을 추가 허용하거나
변경 개수 제한을 늘리지 않습니다. 완료 후에도 원래 태그·물리 ID·문서 내용을 검사합니다.

이미 중단 기록이 있는 이번 스택은 `--preserve-stack-tags` 전용 경로를 사용합니다.
이 경로는 이전 기록이 정확한 main/템플릿/스택에 속하고 실행 의도 기록 전 중단됐으며,
AWS의 이전 미리보기가 아직 `AVAILABLE`이고 관측한 15개 변경과 동일한지 확인합니다.
이전 미리보기의 전체 템플릿 SHA와 비어 있는 태그도 확인합니다. 다른 오류나 이미 실행된
변경 세트를 일반 재시도로 처리하지 않습니다.

기존 `jjikmuk-operations-setup.json`, `jjikmuk-ssm-regex-recovery.json`은 보존하고,
새 기록 `jjikmuk-ssm-regex-tags-recovery.json`을 한 번만 생성합니다. 이전 미리보기는
실행하지 않으며 내용을 새 기록에도 보존합니다. 다른 이름의 새 변경 세트만 검증·실행합니다.
CloudFormation이 실행 후 다른 변경 세트를 정리할 수 있으므로 이전 미리보기의 보존 근거는
로컬 기록입니다. 도구가 스택·변경 세트·기존 기록을 삭제하는 API는 호출하지 않습니다.

정확한 병합 main과 보완 파일 해시 확인 후 별도 실행 블록을 제공합니다. 과거 실행 블록을
반복하거나 기록을 지우지 않습니다. 새 경로도 실패하면 다시 실행하지 않고 기록을 보존합니다.
`--observe --preserve-stack-tags`는 세 번째 기록 기준 읽기 대조만 수행합니다.

검증: 태그 전달 누락 검사 수정 전 실패, 수정 후 성공. 실제 사용자 응답 구조로 15개 변경
거부와 제한된 후속 경로를 검사하고, 기존 기록/미리보기 변조·실행 의도 단계·추가 변경·태그
변경을 거절합니다. AWS SDK 입력 형식과 읽기/쓰기 호출 순서도 모의 검증합니다.
**모의 검사는 실제 AWS 복구 성공을 의미하지 않습니다.** 서버 설치·배포·재시작·SQL은 없습니다.

근거: [CreateChangeSet의 스택 태그 전달과 실행 전 미변경 원칙](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_CreateChangeSet.html),
[ResourceChange의 변경 범위](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ResourceChange.html).

## 최초 SSM 정규식 오류

최초 연결에서 BackendDeployDocument와 ChatbotDeployDocument가 `{1,1024}`의
`invalid repeat count`로 CREATE_FAILED가 됐습니다. Go 정규식 엔진은 한 반복의
상한이 1000을 넘으면 거절합니다. Python 검사와 CloudFormation lint만으로는
이 제약을 검증하지 못했습니다.

SSM 문서의 버전 ID 패턴을 동일 문자 집합의 `{1,1000}`과 `{0,24}` 연결로
바꿔 허용 길이 1~1024자를 유지합니다. Python 실행기 검증과 권한·서비스 명령은
변경하지 않습니다. 독립 백엔드 SSM 정의와 생성된 연결 파일에도 반영합니다.

필수 operations-validation에서 실제 Go 엔진으로 모든 SSM allowedPattern을
컴파일하고 경계 길이와 금지 문자를 검사합니다. Go가 없으면 검사를 건너뛰지 않고
실패합니다. GitHub Ubuntu runner의 Go를 사용하며 모듈/도구 자동 다운로드는 끕니다.
로컬에서는 Go를 PATH에 넣거나 SSM_TEST_GO에 실행 파일을 지정합니다.

기존 실패 스택에 connect_once.py를 다시 실행하거나 생성 기록을 지우지 않습니다.
복구는 기존 스택·원본 템플릿·실패 문서·기존 리소스를 대조한 별도 변경 계획으로
진행합니다. 이 코드 병합 자체는 AWS 수정·설치·배포 승인이 아닙니다.

`recover_regex.py`는 이번 실패 스택 ARN과 이전/수정 템플릿 SHA에 고정된 사람용
CloudShell 복구 도구입니다. 기존 생성 기록을 보존하고, 현재 main에 수정된 연결
파일이 있는지 해시로 확인합니다. 원본 템플릿이 다르거나 다른 리소스도 실패했거나
동일 이름의 문서가 이미 존재하면 진행하지 않습니다.

UPDATE 변경 세트를 만들고, 변경 대상이 실패한 두 SSM 문서뿐인지 확인한 뒤
기존 자원 보존(DisableRollback)으로 한 번 실행합니다. 성공 후 기존 리소스 물리 ID와
새 문서 내용을 검증하고 비공개 연결 영수증을 저장합니다. AWS SDK 쓰기 자동 재시도는
없으며 복구 기록이 있으면 재실행을 거부합니다. 결과가 불명확하면 `--observe`로
읽기 대조만 할 수 있습니다. 영수증이 없다고 자동 재업로드하거나 업데이트하지 않습니다.

복구 도구는 직접 AWS에 접근할 수 있는 기관 관리자 CloudShell에서만 실행합니다.
Codex가 관리자 자격을 가져오는 방식이 아닙니다. 사용자의 실제 복구 승인과 병합된
정확한 main을 확인한 뒤 실행 명령을 제공합니다. 앱 설치·서버 재시작·SQL은 없습니다.

근거: [Go 반복 상한](https://go.dev/pkg/regexp/syntax/),
[SSM의 Java/Go 정규식 검증](https://docs.aws.amazon.com/systems-manager/latest/userguide/documents-syntax-data-elements-parameters.html),
[CloudFormation 실패 자원 보존 및 Update](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stack-failure-options.html).
