# DB 정비에 필요한 여유 공간 조회 권한

현재 연결은 서버의 고정 명령 실행과 DB 스냅샷 생성을 지원하지만 RDS의 `FreeStorageSpace`를 조회하는 CloudWatch 권한이 없습니다. `AllocatedStorage`는 할당 용량이고 SQL의 `DATA_FREE`는 테이블 내부 여유이므로 이를 디스크 여유 공간으로 대신할 수 없습니다.

이 프로젝트의 이전 테이블 정비에서도 여유 공간이 줄어 작업을 중단한 기록이 있습니다. 이번에도 정비 직전과 진행 중에 최신 여유 공간을 확인해야 합니다. 콘솔에서 한 번 전달받는 값은 초기 상태 확인에는 유용하지만, 자동 감시를 완성하려면 아래 읽기 권한이 필요합니다.

## 기관 관리자가 콘솔에서 할 한 가지 설정

CloudShell, 파일 업로드, 임시 인증 발급은 사용하지 않습니다. 관리자 인증을 Codex에 전달하지 않습니다.

1. 기관 계정 `076767081522`의 AWS 콘솔에서 **IAM → 정책(Policies)**으로 이동합니다.
2. 고객 관리형 정책 **`JjikmukOperationsExecutePolicy`**를 선택합니다. 이름이 비슷한 Read 또는 AutoDeploy 정책은 선택하지 않습니다.
3. **편집(Edit) → JSON**을 엽니다. 기존 `Version`과 기존 `Statement` 항목을 전부 보존합니다.
4. `Statement` 배열의 마지막 항목 뒤에 쉼표와 아래 항목 하나를 추가합니다.

```json
{
  "Sid": "ReadSeoulRdsMaintenanceMetrics",
  "Effect": "Allow",
  "Action": "cloudwatch:GetMetricStatistics",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "aws:RequestedRegion": "ap-northeast-2"
    }
  }
}
```

5. 다음 화면에서 **변경 사항 저장(Save changes)**을 선택합니다. 새 정책 버전을 기본 버전으로 저장합니다. 기존 정책·역할·권한 경계는 삭제하지 않습니다.
6. 저장했음을 채팅으로 알려주면 Codex가 기존 GitHub 연결로 실제 조회 가능 여부를 확인합니다.

이 정책은 실행 역할의 권한 정책과 권한 경계로 함께 연결되어 있으므로 같은 정책 한 곳만 수정합니다. 추가되는 것은 서울 리전 CloudWatch 통계 읽기 API 한 가지입니다. 이 API는 IAM에서 개별 RDS 지표로 리소스를 한정하지 못하므로 `Resource`는 `*`이며, 실행 코드가 `AWS/RDS`와 `jjikmuk-dev-db`의 여유 공간 지표만 요청하도록 별도로 고정해야 합니다. IAM 수정·DB 데이터 변경·서버 재시작 권한은 추가하지 않습니다.

기존 CloudFormation 템플릿에도 같은 항목을 정식 반영해야 다음 연결 갱신 때 이 설정이 빠지지 않습니다. 템플릿의 다른 리소스나 권한은 변경하지 않습니다.

## 되돌리는 방법

같은 정책에서 `ReadSeoulRdsMaintenanceMetrics` 항목 하나를 제거한 새 기본 버전을 저장하면 됩니다. 정비가 진행 중일 때 제거하면 공간 감시가 중단되므로 작업을 마친 뒤 제거합니다. 기존 정책 전체를 이전 버전으로 돌리면 다른 변경까지 되돌릴 수 있으므로 이 항목만 제거합니다.

현재 상태: 안내 준비만 완료. 이 문서를 만들면서 AWS 정책이나 운영 DB를 변경하지 않았습니다.

정식 보완 생성기: `python3 ops/operations/maintenance_metrics_access.py --policy` 또는 `--template`. 이 명령은 JSON 출력만 하며 AWS에 적용하지 않습니다. 기존 연결/복구 템플릿을 수정하지 않아 소비된 기록의 재현성을 보존합니다. `storage` 모드는 기존 GitHub 연결에서 고정 RDS 지표 읽기만 수행합니다.

근거: https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudwatch.html 및 https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-metrics.html
