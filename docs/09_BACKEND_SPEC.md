# 09 · 백엔드·작업 실행 상세

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 계층
Router 는 DTO/auth/header 처리와 use case 호출만 한다. Application service 는 권한·상태 전이·ports 호출을 조립한다. Domain 은 immutable 값과 순수 판정이다. Repository 는 DDB key/CAS/transaction 을 숨기며 rule 의미를 해석하지 않는다. AWS 및 모델 adapter 는 provider payload 를 내부 계약으로 변환한다. datetime.now/random/환경변수는 composition root 에서 Clock/IdGenerator/config 로 주입한다.

## 2. 공개 내부 인터페이스
```python
class ParserPort(Protocol):
    def parse(self, source: SourceArtifact, profile: ParserProfile) -> ParseCandidateSet: ...
class SourceStore(Protocol):
    def read_verified(self, ref: ArtifactRef) -> bytes: ...
    def put_immutable(self, tenant_id: str, payload: bytes, media_type: str) -> ArtifactRef: ...
class TaggerPort(Protocol):
    def tag(self, packet: EvidencePacket, replicate_id: int, binding: ModelBinding) -> RawTagResponse: ...
class RuleEngine(Protocol):
    def evaluate(self, tags: ConfirmedTags, context: RuleContext, pack: RulePack) -> Decision: ...
class ReviewRepository(Protocol):
    def resolve_cas(self, command: ResolveReviewCommand, expected_revision: int) -> ReviewResolution: ...
```
Protocol/model 파일은 실제 타입으로 구현한다. 외부 DTO dict 를 그대로 domain 으로 넘기지 않는다. 추출 후 허용 source 를 일일이 검증한 `ConfirmedTags`만 RuleEngine 에 들어갈 수 있다.

## 3. 업로드 확정
1. session membership/editor, Upload 상태/만료, expected size/hash 검사.
2. S3 HEAD 에서 크기 확인 후 stream 으로 실제 PDF magic/hash 검사. 필요하면 샌드박스 PDF parser 로 pages/password 검사.
3. 암호 PDF 는 `PDF_PASSWORD_REQUIRED`; 원문 손상은 `PDF_INVALID`; 초과 제한은 `UPLOAD_LIMIT_EXCEEDED`. 비밀번호 수집/복구 기능은 P0에 없다.
4. 검증된 bytes 를 immutable original prefix 로 복사하고 version_id/hash 를 고정한다.
5. Upload accepted+DocumentVersion ready+Document latest pointer CAS+Audit/Idempotency 를 커밋한다. 동시에 다른 버전이 생기면 version 생성은 유지하고 latest 갱신은 created_at/id 정렬 규약으로 한 번 재시도한다.

## 4. Run 생성과 실행
```text
start_run(command, actor):
  authorize(editor, tenant)
  require(version.ready and consent allows document + processing regions)
  require(rulepack validated and runtime preflight passed)
  validate scope, max2 active runs, idempotency
  snapshot = hashes(version, parser_profile, rules, models, prompts, limits)
  transaction: run(queued), PARSE job, outbox, idempotency, audit
  return 202 run
```
동시 실행 제한은 tenant counter CAS/transaction 으로 enforce 하며 API replica 별 메모리 count 를 쓰지 않는다. 완료/취소/실패에서 counter 해제도 멱등하게 기록한다. 인프라 quota 때문에 모델 호출이 실패하면 같은 모델 요청의 retry 이지 임의 provider fallback 이 아니다.

## 5. Stage job 처리
`claim_job(job_id, now)`는 pending 또는 lease 만료일 때만 owner/fence 를 갱신한다. 출력 artifact 는 `attempt/{fence}/` 고유 prefix 다. `commit_job`은 status leased, lease_owner, fence, input_hash 가 같은지 한 번에 확인하고 succeeded+artifact pointer+next outbox 를 저장한다. cancellation_requested 가 켜졌으면 추가 외부 호출을 하지 않는다. 이미 진행 중인 호출의 늦은 응답은 usage 만 기록하고 cancelled run 에 결과를 publish 하지 않는다.

failed input/schema/citation 은 무조건 네트워크 retry 대상으로 분류하지 않는다. schema invalid 는 같은 replica 에서 repair 최대1회, 그 뒤 needs_review; transient429/5xx/timeouts 는 지수 backoff 최대3회이다. 자세한 오류 표는13장이다.

## 6. 검토 확정
현재 review·claim head·tags·Run epoch 를 strong read 한다. source refs 가 같은 document_version/tenant 에 속하는지 다시 검사한다. 제출된 상태와 값에 적절한 근거가 있는지 검증하고 새 TagRevision/DecisionRevision artifact 를 생성한다. label 은 서버 RuleEngine 결과에서만 만든다. transaction 에서 base_tag_revision 과 If-Match 를 동시에 검증한다. 충돌시 새 artifact 를 publish 하지 않고 orphan 으로 회수한다. 새 룰이 필요하다는 reason 은 규칙을 임의 변경하지 않고 gap id 를 생성한다.

## 7. 리포트 스냅샷
S3 snapshot manifest 에는 `run_id, mutation_epoch, claim_id→tag_revision/decision_revision, rulepack hashes, coverage, unverified_basis, generated_at`을 고정한다. epoch 를 읽고 모든 claim head 를 strong paginated query 한 뒤 epoch 를 다시 읽는다. 바뀌었으면 최대3회 재시도하고 계속 변경되면 EXPORT_SNAPSHOT_BUSY 로 job 을 재예약한다. 일치한 목록은 이후 review 가 바뀌어도 과거 immutable revision 을 직접 읽어 export 한다. 같은 export 안에 최신 태깅과 과거 판정이 섞이지 않게 한다.

## 8. 근거/응답 캐시
cache namespace 는 tenant_id+consent_profile+document_version+role+request signature 다. raw model response cache 와 guarded tags/decision cache 를 분리한다. replicate1의 raw response 를2나3으로 복제하지 않는다. 같은 replica 실패 복구만 동일 request id 캐시를 읽는다. 동의 철회·삭제 시 source 와 관련된 모든 cache key 를 manifest 에서 찾아 revoke 한다. `temperature`, model id/profile, prompt/schema, packet hash, tools, max_tokens 가 모두 signature 에 포함된다.
