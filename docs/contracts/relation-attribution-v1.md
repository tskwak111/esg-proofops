# SY1 관계·축 귀속 가드

새 `RunService`의 실제 태깅 실행은 `relation-attribution-v1` 정책과 SHA-256을
run snapshot 및 tag checkpoint에 고정한다. 기존 snapshot에 정책이 없으면
기존 reader를 사용한다. 기존 모델·프롬프트·규칙 해시와 revision은 재작성하지 않는다.

Luna 사전분류의 literal 축과 relation 역할 선택은 원문 검증 후 다음 제한을 받는다.
대상 주장과 같은 물리쪽의 같은 canonical 문단만 허용한다. 같은 블록에서도
빈 줄·글머리 기호로 나뉜 문단은 별개다. 다른 블록은 PS1의 명시적 `derived_from`
연결과 `source_recovery_join=ps1-v1` 표지, verified 품질, 같은 쪽, 원문 그대로의
결합을 확인한 그룹만 허용한다. 공유 제목·근접 좌표·같은 단어는 귀속 근거가 아니다.
기존에 검증된 동일 표의 행·열 헤더 계약은 그대로 사용한다.

토큰 중간의 부분 문자열은 거절한다. `기아는`에서 `기아`처럼 온전한 조사만
떼는 경우는 정책에 명시한 조사에 한해 허용한다. `탄소가격`의 `탄소`는 거절한다.
RE100·SBTi·CDP·GRI 및 ISO 번호 형태의 인증명은 product/material로 허용하지 않는다.
이는 역할 혼동 방지이며 새 입증 기준·등급 규칙이나 의미적 귀속 승인이 아니다.

거절된 축은 명시적 null/unknown으로 남긴다. 외부 원문 블록의 거절은 모델 호출
전에 기록하며, 원시 모델 응답과 replica·원문 위치·해시는 기존 receipt에 보존한다.
v3 후보 패킷에도 같은 토큰/역할 거절을 적용하고 검증 때 같은 목록을 재계산한다.
없어진 후보를 absent/not_applicable로 바꾸거나 다른 후보로 대체하지 않는다.

공개 API/DB column 변경·migration은 없다. 내부 opaque snapshot/checkpoint에만
정책 pin이 추가된다. rollback은 새 실행의 `relation_attribution_policy=None` 선택이다.
정책이 있는 기존 실행은 지원 reader로 계속 읽고, 이전 reader에 새 실행을 배정하지 않는다.
가드만으로 과거 결과를 재채점하거나 기존 보고서를 덮어쓰지 않는다.

무료 재생은 저장된 literal 후보에 대한 거절 비교다. 저장 DB는 읽기 전용이며
원문 attestation·실제 모델·등급 재계산은 수행하지 않는다. 표/블록 그룹 예외는
검증된 runtime graph가 필요하므로 offline raw-block 수치는 보수적 후보 거절 수다.
검수의 `relation-10-01`은 맞음으로 기록돼 있지만 다른 쪽이어서 이번 정책에서는
보류된다. 이 차이는 오답 제거와 분리해 보고하며 독립 human gold 정확도로 표현하지 않는다.
