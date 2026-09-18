# TASK-037/041 OIDC local implementation evidence

## Technical contract recorded before implementation

Authoritative contracts: docs/07 §6 and docs/11 §1; existing SessionRecord,
AuthStore, membership lookup and TASK-041 cookie contract remain unchanged.
Add only GET /auth/login and GET /auth/callback, with generic no-store errors.
The composition root owns wiring and all deployment/account values.

Proposed interface: `build_oidc_router(auth_store, *, config=None, provider=None,
transactions=None, clock=time.time)`. OIDCConfig requires exact issuer, client_id,
authorization_endpoint, token_endpoint, jwks_uri, redirect_uri, app_origin,
return_to_allowlist; secure HTTPS configuration only. Login is disabled without
configuration/provider/encrypted refresh storage. No account defaults are invented.

Server state contains nonce, S256 verifier, browser-binding hash, return path and
expiry (at most 600 seconds); atomic consume and hash-keyed code reservations
reject replay before exchange. The bounded process-local store is for explicit
local use, not a distributed deployment. Browser gets a random binding cookie
with Secure/HttpOnly/Path=/, SameSite=Lax and no Domain. Only approved exact
same-origin relative return paths are accepted. Callback URL must exactly match
configuration apart from its OIDC query parameters; no request Host-derived URLs.

ID tokens are signature-verified with a reviewed JWT library, fixed RS256,
configured issuer/audience, exp and nonce and Cognito token_use=id. Access tokens
are not authorization inputs. Bounded JWKS cache expires for rotation and never
follows token-provided key URLs. Transport has timeouts, response size limits and
no redirects; tests inject a fake issuer transport and generated signing keys.
New sessions use >=32 random bytes, null tenant, existing session-store CSRF and
8h absolute/30min idle deadlines. Login revokes a presented previous SID after
creating its successor; old records are not overwritten into a new identity.
Membership remains authoritative at tenant selection; JWT/client roles ignored.

## Store migration, compatibility and rollback

No public DTO, persistent session schema or existing session rows change. The
additional pending-login/code replay records are ephemeral, hash-keyed and
bounded. A deployment needs a shared atomic TTL/consume store and KMS encrypted
refresh-token persistence before enabling this boundary across processes.
An injected encrypted refresh sink must persist before a session becomes usable;
without it login fails closed. Tests use only generated synthetic token data and
local authenticated encryption. Real KMS/DynamoDB persistence is not implemented.
Disable/remove the new router wiring to roll back; existing auth routes/sessions
remain readable, pending login attempts expire and cannot be resumed after restart.
No real Cognito, AWS, MFA policy, model or cloud mutation is authorized or run.
Dependency and root wiring changes belong to the coordinator.

## Verification

Pending implementation and focused checks; no production readiness claim.

## Implemented interface and reviewed dependencies

- `proofops_api.oidc.build_oidc_router(auth_store, *, config=None, provider=None,
  transactions=None, clock=time.time)` exposes the two authoritative redirect routes.
- `proofops.adapters.aws.oidc.OIDCConfig`: issuer, client_id,
  authorization_endpoint, token_endpoint, jwks_uri, redirect_uri, app_origin,
  return_to_allowlist (tuple, default `/`), state_ttl_seconds=600,
  jwks_ttl_seconds=300. Issuer and hosted UI are separate explicit inputs;
  no user-pool ARN, hosted domain or region is fabricated. Root can use its
  existing COGNITO_CLIENT_ID/COGNITO_DOMAIN/app origin inputs after validation.
  The configured app client must support public-client Authorization Code + PKCE;
  client-secret authentication is not implemented or silently bypassed.
- `OIDCProvider(config, *, transport=None, save_refresh=None, clock=time.time)`:
  callable encrypted persistence is mandatory even before redirecting to login.
  `KMSRefreshTokenSink(kms_client=..., key_id=..., write_ciphertext=...)` calls only
  the injected client and writes only returned ciphertext with SID-hash/user
  encryption context. Actual SDK client creation, account/key approval and
  durable ciphertext writer belong to deployment composition. Provider.close()
  must run when a configured application shuts down.
- `InMemoryOIDCStore(capacity=4096)` stores hashed state/code keys, browser-binding
  hashes and bounded pending state. Atomic consume/reserve is protected by a
  process-local lock that is never held during issuer HTTP. Code replay hashes
  expire after 600 seconds; the real authorization server must also enforce
  one-use authorization codes and its <=10 minute authorization-code lifetime.
- The coordinator approved and installed `PyJWT[crypto]==2.13.0` (MIT) with
  cryptography 50.0.1 (Apache-2.0 OR BSD-3-Clause); coordinator owns optional-extra,
  lockfile, license/SBOM and dependency audit changes. No dependency file edited
  by this worker. Primary references: [PyJWT package metadata](https://pypi.org/pypi/PyJWT/json)
  and [PyJWT verification documentation](https://pyjwt.readthedocs.io/en/stable/usage.html).

JWT verification uses library RS256 signatures and exact iss/aud (single
configured audience); required claims, finite numeric timestamps, nonce and
Cognito token_use=id are checked. exp/iat/nbf use the injected server clock,
without leeway; library time checks are disabled only to make that single clock
consistent. No unverified payload field authorizes a user, tenant or role.
Access tokens are discarded, never used as ID tokens or authorization claims.
The JWKS cache holds at most 16 configured-issuer RSA signing keys for <=300s;
unknown kids cannot force a refresh before expiry. Requests cannot use key URLs
from JWT headers. HTTP responses are capped at 64KiB, client timeout is 5s,
redirect following and ambient proxy configuration are disabled.

A failed session write triggers successor revocation and returns a generic 503
without a cookie. Encrypted refresh persistence precedes session activation;
a durable deployment needs cleanup/reconciliation for orphan ciphertext if a
later session write/revocation fails. This local implementation does not claim
atomic distributed login rotation or production persistence. Existing immutable
SessionRecord objects are preserved; stores only revoke predecessor records.

## Executed evidence (2026-09-09)

1. Before implementation: `uv run --no-sync pytest tests/acceptance/test_oidc.py -q`
   failed the explicit missing-boundary assertion (1 failed). The expanded
   fail-first cases then reported 23 missing-module setup errors, as expected.
2. First implementation: 23 signed JWT/HTTP boundary cases passed. Extended tests
   found an unhandled post-write session-store error (1 failed); after cleanup
   handling, its focused regression passed. An initial helper edit command used
   unavailable `python`; it made no edit and was rerun with `python3`.
3. Final focused suite:
   `uv run --no-sync pytest tests/acceptance/test_oidc.py tests/acceptance/test_auth.py tests/acceptance/test_session_security.py -q`
   → **79 passed**, exit 0 (39 OIDC + 40 existing auth/security), 3.64s.
   Two upstream deprecation warnings: Starlette TestClient/httpx and AnyIO
   BlockingPortal alias. No warnings suppressed or dependencies added for them.
4. `uv run --no-sync ruff check apps/api/src/proofops_api/oidc.py packages/proofops/adapters/aws/oidc.py packages/proofops/adapters/local/oidc_store.py tests/acceptance/test_oidc.py`
   → All checks passed, exit 0.
5. `uv run --no-sync mypy --follow-imports=silent apps/api/src/proofops_api/oidc.py packages/proofops/adapters/aws/oidc.py packages/proofops/adapters/local/oidc_store.py`
   → Success: no issues found in 3 source files, exit 0.
6. `uv run --no-sync python -m py_compile apps/api/src/proofops_api/oidc.py packages/proofops/adapters/aws/oidc.py packages/proofops/adapters/local/oidc_store.py`
   → exit 0 (focused compilation, not a full application build).

Tests generate real ephemeral RSA signing keys and Fernet ciphertext. The
identity `synthetic-oidc-user-never-real`, issuer example.test URLs, tokens and
KMS client are explicitly synthetic. One test performs actual TCP POST token
exchange and GET JWKS against a bounded 127.0.0.1 HTTP server, remapped only by
an injected test transport; application endpoints run through FastAPI TestClient.
The server is shut down and keys/ciphertext are process-local fixtures.

Coverage includes S256 verifier binding, callback exact URI, cookie flags,
unselected tenant, strong membership choice ignoring admin JWT claims, predecessor
revocation, success→GET /v1/session, expired/replayed state, missing browser binding,
code replay under fresh state, atomic concurrent consume/reserve, bounded capacity,
nonce/aud/issuer/exp/sub/token-use rejection, numeric timestamp types, signature
mutation, none/HS256/wrong RSA key rejection, untrusted key headers, expired JWKS
rotation, malformed/oversized/redirect/timeout issuer responses, open redirects,
missing config/encryption, encryption failure, encrypted-only KMS sink output,
and failed session-write cleanup.

## Remaining / not_run

Actual Cognito authorization, real AWS/KMS/DynamoDB operations, cloud mutation,
MFA/user-pool policy configuration, real account configuration, browser E2E,
full application build, full WIP repository suite, real token refresh/revocation,
and distributed store migration are **not_run**. Root owns router wiring and
final dependency audit; this worker edited only the five dispatched files and
performed no Git operation, commit or push. Local default login remains 503
until an explicit validated provider/encrypted sink is supplied. No production
readiness, external MFA enforcement or real-account login claim is made.

Coordinator review regression: caller-owned mutable return-path lists could escape
the frozen config. The mutation test failed first; OIDCConfig now copies the list
to a tuple before validation, and the final 79-test/lint/type/compile run above
passed after this fix. Root confirmed it owns the installed httpx runtime extra.
