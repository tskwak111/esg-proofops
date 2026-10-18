# 웹

React·TypeScript·Vite 기반의 업로드, 분석 진행, 결과 탐색, PDF 원문 검토 화면입니다.

- 진입점: [main.tsx](src/main.tsx) → [App.tsx](src/App.tsx). 공개 화면과 저장 사례는 [StaticDemo.tsx](src/StaticDemo.tsx)에서 연결합니다.
- 분석·결과: [HostedAnalysis.tsx](src/features/hosted/HostedAnalysis.tsx), [HostedResult.tsx](src/features/hosted/HostedResult.tsx), [hostedClient.ts](src/features/hosted/hostedClient.ts).
- 원문: [SourceSplitView.tsx](src/features/hosted/SourceSplitView.tsx)와 [OriginalPdfPage.tsx](src/features/hosted/OriginalPdfPage.tsx)가 서버의 쪽·좌표를 PDF에 표시합니다.
- 실행: 루트에서 `pnpm --filter proofops-web dev`, 빌드는 `pnpm build`. 키 없는 사례 실행은 [루트 안내](../../README.md)를 따릅니다.

등급은 API 결과를 표시합니다. 모델 키는 웹에 넣지 않으며, API 연결은 [vite.config.ts](vite.config.ts)와 `VITE_API_BASE_URL`·`VITE_ANALYSIS_BACKEND` 설정을 확인합니다.

## 개발 검사

루트에서 `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm --filter proofops-web test:ci`, `pnpm build`를 실행합니다. `test:ci`는 공개 checkout에 포함된 합성·공개 fixture만 사용하는 테스트 파일을 명시적으로 실행하며 frontend CI에도 연결되어 있습니다.

전체 `pnpm test`는 아래 비공개 저장 결과 fixture도 필요합니다. 테스트와 검증 조건은 그대로 유지하며, 권한 있는 로컬 fixture를 준비했을 때 실행합니다. CI를 위해 비공개 결과를 커밋하지 않습니다.

| 테스트 (`src/features/hosted/` 기준) | 추가로 필요한 fixture (`test/fixtures/` 기준) |
| --- | --- |
| `resultBrowser.test.cjs` | `w12/lg.result.json`, `w12/kakao.result.json` |
| `resultReport.test.cjs` | `w12/lg.result.json` |
| `ux3.test.cjs` | `w12/lg.result.json`; `UX3_REAL_DATA_DIR` 설정 시 해당 디렉터리의 저장 결과 |

Python 검사는 루트의 `scripts/test_core.sh`(개발 중 관련 검사)와 `scripts/test_full.sh`(전체 검사)를 구분합니다. 웹 테스트 통과는 실모델 정확도 측정이 아닙니다.

웹 동기화 기준은 제출 main `379f98b`입니다. 개발 저장소의 기존 회귀 검사는 추가로 보존하며, `hostedClient.ts`의 점검·파싱·lease 오류 안내와 `resultModel.ts`의 과거 `cf6_status` 요소 표시, `ClaimWorkspace.tsx`의 부분 검토 후보·빈 판정 필드 호환성을 유지합니다. 원문 미연결 추출값은 확인된 사실과 분리해 표시합니다. 분석·판정·권한·비용 계산은 변경하지 않습니다. PDF 의존성 고지는 [PDF 라이선스 안내](PDF_LIB_LICENSE.md)를 참고합니다.
