# Sol application/reconciliation interface

## Service

```python
reconcile(
    packet: dict,
    policy: dict,
    *,
    source_reader,
    explanation_search,
    policy_registry=None,
    coverage_registry=None,
    document_registry=None,
) -> dict
```

`source_reader(ref) -> bytes`와 `explanation_search(packet) -> list[dict]`는 frozen callable 계약을 유지한다. Application은 adapter를 import하지 않는다. packet/policy semantic hash는 1.1 호환을 위해 `json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",", ":"))`의 UTF-8 SHA-256이다.

## Trusted registries

모든 registry는 운영자 주입 신뢰 입력이며 raw packet/policy 안의 동명 boolean을 신뢰하지 않는다.

### policy_registry

Canonical policy SHA-256을 key로 사용한다.

```json
{
  "<canonical-policy-sha256>": {
    "approved": true,
    "approved_by": "reviewer-id",
    "approved_on": "2026-09-21",
    "version": "policy-v1",
    "source_policy_sha256": "<64 lowercase hex>",
    "synthetic_only": true
  }
}
```

Registry entry가 없거나 `approved`가 false이면 blocked다. version/source hash/synthetic scope가 policy와 다르면 승인으로 사용하지 않는다.

### coverage_registry

`receipt_id`를 key로 사용한다.

```json
{
  "receipt-1": {
    "state": "complete",
    "coverage_policy_id": "coverage-v1",
    "tenant_id": "tenant-1",
    "company_id": "company-1",
    "package_id": "package-1",
    "required_document_ids": ["sr-doc", "fin-doc"],
    "reviewed_source_ids": ["sr-source", "fin-source"],
    "failed_document_ids": []
  }
}
```

Application은 packet의 `search.state`, reviewed/failed 목록을 이 receipt 값으로 교체한다. `complete`는 failed 문서가 없고 required 문서와 reviewed source가 실제 registry/source 집합에 존재할 때만 유효하다.

### document_registry

`document_id`를 key로 사용한다. 각 entry는 identity/as-of/relevance와 source별 정규화 fact binding을 모두 가진다.

```json
{
  "sr-doc": {
    "tenant_id": "tenant-1",
    "company_id": "company-1",
    "package_id": "package-1",
    "document_version_id": "sr-v1",
    "document_role": "sustainability",
    "synthetic": true,
    "artifact_sha256": "<64 lowercase hex>",
    "corp_code": "00123456",
    "fiscal_year": 2025,
    "rcept_no": null,
    "consolidation": "consolidated",
    "published_at": "2026-03-01",
    "available_on": "2026-03-01",
    "as_of_date": "2026-06-30",
    "period_start": "2025-01-01",
    "period_end": "2025-12-31",
    "relevant_items": ["C1", "C2", "C3", "C4"],
    "decision_binding": {
      "item": "C1",
      "comparability": "comparable",
      "claim": {"track": "performance", "quote": "...", "source_id": "sr-source", "trigger_elements": ["organizational_boundary"], "fiscal_year": 2025},
      "c3_context": null,
      "c4_context": null,
      "claim_id": "claim-1"
    },
    "source_bindings": {
      "sr-source": {"locator": "id:scope", "quote": "...", "roles": ["claim", "sustainability_fact"]}
    },
    "fact_bindings": {
      "sr-source": {
        "raw": "A, B",
        "normalized": "[\"A\",\"B\"]",
        "kind": "entity_set",
        "unit": null
      }
    }
  }
}
```

Financial role의 `document_version_id`, `rcept_no`, `corp_code`, fiscal year, consolidation은 packet identity와 정확히 같아야 한다. Registry `as_of_date`는 packet identity와 정확히 같아야 하고 role별 `published_at`도 identity의 해당 publication date와 일치해야 하며, `available_on`은 registry as-of 이후일 수 없다. 모든 source는 artifact hash와 requested item relevance가 일치해야 한다. Sustainability/financial의 raw/normalized/kind/unit은 해당 source의 `fact_bindings`와 정확히 같아야 하며, raw packet 값만으로 engine 입력을 만들지 않는다.

`decision_binding`은 item, comparability, claim(track/trigger/source/FY 포함), C3/C4 context와 claim ID를 packet과 정확히 결합한다. `source_bindings`는 locator/quote와 semantic role을 결합하며 role은 `claim`, `sustainability_fact`, `financial_fact`, `c3_commitment`, `c3_funding`, `c4_definition`, `c4_calculation`, `explanation` 중 필요한 값을 사용한다. 실제 문자열이 존재하더라도 registry가 지정한 role/claim에 속하지 않으면 engine 입력으로 사용하지 않는다.

## FileSourceReader

```python
FileSourceReader(root, artifacts)
```

`artifacts`는 `document_id` key mapping이다.

```json
{
  "sr-doc": {
    "path": "reports/sr.html",
    "format": "html",
    "sha256": "<64 lowercase hex>"
  }
}
```

지원 format은 `text`, `xml`, `html`, `pdf`다. Instance는 `reader(ref) -> bytes` callable이며 `reader.validate(ref, payload=None) -> bool`도 제공한다. 상대 경로만 허용하고 resolved path와 symlink가 root 밖이면 거부하며, 매 read마다 manifest hash와 ref hash를 검사한다.

Locator는 text `chars:<start>:<end>`(Unicode code point, end-exclusive), XML/XBRL·HTML `id:<element-id>`, PDF `page:<1-based-page>`다. Quote는 해당 locator가 가리키는 내용에 정확히 존재해야 하며 유사도/정규화로 승인하지 않는다. PDF bbox는 생성하지 않으며, unsupported locator/format, 암호화 PDF, 추출 불가 text는 fail-closed다.

최종 통합 보완: 50 MiB 읽기 제한과 매 읽기 시 경로 확인을 적용한다. XML DTD는
인코딩과 무관하게 거부하고 중복 element ID, HTML target 밖 문장, 닫히지 않은
target을 거부한다. Adapter와 bare callable은 같은 byte 검증 함수를 사용한다.
문서 `synthetic`은 명시적 boolean이며 packet과 같아야 한다. Policy registry의
`synthetic_only`도 명시적 boolean으로 원 policy 범위와 일치해야 한다.

반환 `packet_sha256`/`policy_sha256`은 제출된 원 입력을 해시한다. 재현을 위해
신뢰 레지스트리·후보 snapshot도 함께 보관한다. Registry 검증 후 만들어진 내부
engine 입력 해시를 client packet revision처럼 반환하지 않는다.
