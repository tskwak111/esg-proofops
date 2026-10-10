export const bindingReasons: Record<string, string> = {
  parser_conflict: "파서 결과가 충돌하여 원문 표·본문 검토 필요",
  source_unverified: "해당 좌표의 원문 인용을 확인하지 못함",
  tagging_incomplete: "3회 근거 태깅 미완료",
  table_structure_unverified: "표의 행·열 구조 교차 확인 필요",
  calculation_method_review_required: "절감 활동과 수치 산정 방법론의 구분 필요",
  ordinal_scale_review_required: "낮음·높음 등 표현의 등급 척도 연결 필요",
  assurance_scope_review_required: "보증서가 해당 지표·기간·사업장을 포함하는지 확인 필요",
  direct_claim_or_table_binding_required: "직접 주장 또는 같은 표의 해당 셀 연결 필요",
  cross_location_identity_unresolved: "다른 위치 근거의 기업·지표·연도 연결 미확인",
  cross_location_scope_unresolved: "다른 위치 근거의 단위·분모·조건 연결 미확인",
  scope_exclusion_review_required: "제외·제한 범위 검토 필요",
  reporting_period_mismatch: "주장과 근거의 기간 불일치",
  not_found_in_packet: "검색 패킷에서 미확인 · 근거 부재를 뜻하지 않음",
};

export const factNames: Record<string, string> = {
  quantitative_or_qualified_ordinal: "수치·척도", unit_or_qualified_ordinal: "단위",
  comparison_baseline: "비교기준", method: "산정방법론", calculation_boundary: "산정경계",
  assurance_covered: "해당 지표 보증 범위", target_year: "목표연도", target_metric: "목표지표",
  org_boundary: "조직경계", named_means_or_concrete_state: "구체적 수단·운영 상태",
  external_verification: "외부 검증", concrete_implementation_detail: "구체적 이행 내용",
  responsible_organization: "담당 조직", compensation_link: "보상 연계",
};
