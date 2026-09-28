# Kia case route

Import `KiaCasePage` (default export) from `./features/kia/KiaCasePage` and mount it at `/demo/kia`. It needs no props and fetches `public/demo/kia-2025.json` itself. `route.ts` also exports `{ path, Component }` as `kiaRoute` for direct route wiring.

Add a NAVER / 기아 switcher linking `/demo` and `/demo/kia` in the demo header. The Kia page includes numeric checks and assurance links below its claim explorer. It uses only short quotes and physical page numbers. `시연 모드` marks the user confirmed sample and range floors are shown as `추정`.
