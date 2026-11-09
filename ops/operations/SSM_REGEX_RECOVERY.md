# SSM 문서 생성 오류 보완

## 2026-11-10 실제 응답에 맞춘 기존 변경 세트 실행안

첫 복구는 변경 항목이 2개라는 가정 때문에 `UNEXPECTED_CHANGE_COUNT`로 중단됐습니다.
후속 보완은 이전 변경 세트의 `Tags`가 비어 있을 것이라는 가정 때문에
`PREVIOUS_PREVIEW_CHANGED`로 중단됐습니다. 두 가정은 잘못됐습니다. 추가 조회에서
이전 변경 세트의 태그가 이미 `Project=JJIKMUK`임을 확인했습니다. 태그 전달 누락이
13개 추가 변경의 확정 원인이라는 이전 설명은 철회합니다.

관측한 변경 세트는 정확한 ARN `ssm-regex-repair-61fb267d7b184b2e3477/30cc9193-55fe-496d-b4a4-018ea2a01908`
이며 실행 전 `CREATE_COMPLETE / AVAILABLE`입니다. 변경 목록은 다음과 같습니다.

- 생성에 실패했고 현재 존재하지 않는 SSM 배포 문서 2개: 복구 생성.
- 기존 연결 리소스 13개: `Modify`, `Replacement=False`, 범위 `Tags`만,
  `Evaluation=Static`, `RequiresRecreation=Never`. 권한/신뢰 내용이나 저장소 속성 변경은
  표시되지 않았습니다. 실행 후 스택 태그도 기존 `Project=JJIKMUK`와 같습니다.

13건이 표시되는 AWS 내부 원인은 확인되지 않았습니다. 태그 처리가 완전히 없는 작업이라고
단정하지 않습니다. **기존과 같은 태그 유지·재적용이 포함될 수 있는 15항목 실행안**으로
설명하며, 이전 두 문서만 처리한다는 안내와 달라진 범위를 사용자에게 승인받기 전에는
실행하지 않습니다. PR 병합은 AWS 실행 승인이 아닙니다.

`--complete-reviewed-preview`는 이미 있는 이 변경 세트만 검증해 실행합니다. 새 변경
세트를 만들지 않습니다. 스택 원본/수정 템플릿 전체 SHA, 기존 물리 ID, 문서 부재,
원래 실패 기록, 실제 관측한 변경 목록 전체, 현재/실행 후 스택 태그를 대조합니다.
이전 문서 2개용 확인 문구로는 진행되지 않으며 새 문구는
`COMPLETE JJIKMUK REVIEWED CONNECTION`입니다.

기존 setup/recovery 기록은 보존합니다. 중단된 태그 보완 실행이 새 기록
`jjikmuk-ssm-regex-tags-recovery.json`을 남겼다면 상황이 다르므로 실행하지 않습니다.
새 `jjikmuk-ssm-reviewed-preview-recovery.json`을 한 번만 만들고, 검증한 미리보기 내용을
함께 저장합니다. 실행 직전 다시 대조하고 `DisableRollback=True`로 한 번 실행합니다.
불명확한 결과나 실패는 자동 재시도하지 않습니다. `--observe --complete-reviewed-preview`
는 새 기록 기준 읽기 대조만 하며 영수증을 임의 재업로드하지 않습니다.

완료 후 태그·템플릿·기존 리소스 물리 ID·문서 내용을 확인하고 비공개 연결 영수증을
저장합니다. IAM 권한 확대·앱 설치·배포·재시작·SQL·CD 활성화는 포함하지 않습니다.
기존 `--preserve-stack-tags` 실행 안내는 더 이상 사용하지 않습니다.

새로운 미리보기를 만드는 일반 경로는 두 문서만 허용하는 제한을 유지합니다.
15건 허용은 실제 관측된 고정 ARN/템플릿/상태/목록에 한정된 별도 확인 경로입니다.

검증: 사용자 응답의 태그로 기존 오류를 재현한 뒤 수정 성공, 이전 확인 문구 거절,
권한 내용/삭제/교체/태그값/변경 목록/기록 불일치 거절, 불명확한 실행 재전송 금지,
AWS SDK 요청 형식 검증. 모의 검사는 실제 AWS 복구 성공을 의미하지 않습니다.

근거: [DescribeChangeSet의 Tags는 실행 후 스택 태그](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DescribeChangeSet.html),
[실패한 스택의 자원 보존](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stack-failure-options.html).

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
