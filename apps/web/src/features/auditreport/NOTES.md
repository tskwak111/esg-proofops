# 감사 보고서 화면

- 기본 내보내기: `AuditReportPage.tsx`의 `default` 컴포넌트. 별도 props 없이 `useParams()`에서 `company`를 읽습니다.
- 경로: `route.ts`의 `auditReportRoute.path` (`/report/:company`), `company`는 `naver` 또는 `kia`입니다. 라우터에 `<Route path={auditReportRoute.path} element={<AuditReportPage />} />`로 연결하면 됩니다.
- 데이터: `/demo/{company}-2025.json`을 읽습니다. KIA 스냅샷이 아직 없으면 오류 화면을 표시합니다. `demo_mode` 또는 `relaxed_rules`가 스냅샷/`run`에 있으면 작은 `시연 모드` 표식을 표시합니다.
- 화면/내보내기: 확정 등급 분포, 미판정 구분, 처리 단계, 주장별 200자 이하 요약과 근거 물리 쪽수, 방법론·한계를 포함합니다. PDF 버튼은 브라우저 인쇄 대화상자를 열고 JSON/CSV는 브라우저에서 생성합니다.
- 데이터 검사: `cd apps/web && node src/features/auditreport/check.mjs`.
