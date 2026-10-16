# Hosted reusable access password v1 — A1

This additive hosted-only authentication contract retains one-use invitations,
the exact production APP_ORIGIN, existing CSRF checks, Secure/HttpOnly/SameSite=Lax
host cookies, maximum eight-hour sessions and thirty-minute idle expiry. Neither
login grants permission to spend money outside existing run/day/event USD limits,
daily counts, active slots or operator admission settings.

## API and identities

`POST /v1/auth/access-password` accepts strict JSON `{role, password}`. Role is
`admin` or `organizer`; password is a string of 1–128 characters (provisioning
requires 16–128). The exact Origin is mandatory, including before verification;
preview origins remain denied. Success uses the existing session response/cookie
and returns the external role `organizer` or `admin`. Failed validation returns
422 `VALIDATION_ERROR` without echoing any input. Wrong, expired, disabled and
unconfigured credentials return indistinguishable 401 `ACCESS_PASSWORD_INVALID`.
429 `ACCESS_PASSWORD_LOCKED` includes the remaining seconds in `Retry-After`;
bad/unreadable private configuration fails closed with 503. No password/hash or
cookie value appears in API errors or operator output.

Each role has a stable reserved identity `access-password:<role>` and one assigned
tenant. Invitations cannot create these identities. `admin` reuses all existing
admin capabilities within that tenant. `organizer` maps internally to the existing
editor capabilities (upload/analyze/view, no review/admin); public session role is
`organizer`. Ownership is the shared role account, so later sessions/rotations can
reopen its earlier uploads. This is not isolation among people sharing the same
organizer password. Tenant-wide other-user documents/runs are hidden from this
account in collections and all individual/nested document/run routes, including
scope, result, review and original-page paths. Non-owner access returns
opaque 404. POST run admission independently checks document ownership. Existing
invitation members retain their existing shared-tenant behavior.

## Private credentials, failures and rotation

`HOSTED_ACCESS_CONFIG` defaults to `/run/private/access.json`; missing configuration
disables password access and leaves invitation login usable. Absolute path, regular
non-symlink file, no group/other access (operator writes mode0600). JSON version1
holds only two role records: tenant UUID, role, epoch expiry, active bool, random
16-byte salt, scrypt digest, session epoch and fixed `scrypt-v1` algorithm marker.
No plaintext, secret in environment, configurable weak KDF or new dependency.
`hashlib.scrypt` uses N32768/r8/p3, 32-byte output, 64MiB maxmem; comparison uses
`hmac.compare_digest`. This is an [OWASP scrypt parameter set](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt).
The SQLite writer fence serializes verification across API processes, bounding
KDF memory and ensuring concurrent failures cannot bypass counters.

Both IP and role account independently lock after five failures in a sliding
600-second window for900 seconds. The fifth failure is already429. Correct
credentials cannot bypass a live lock; successful login does not erase other
attackers' failure history. Counters/locks survive restart. Audit events contain
timestamp, action, role and keyed IP pseudonym, never submitted values or raw IP;
maintenance deletes expired counters/locks and audit older than HOSTED_AUDIT_DAYS.
No Origin failure runs a KDF. Forwarded IP headers are ignored unless the immediate
peer exactly matches an IP in optional `HOSTED_AUTH_TRUSTED_PROXIES`; then only the
rightmost proxy-appended X-Forwarded-For hop is read. Configure only a proxy that
sanitizes/appends this header. Without it, proxied clients conservatively share the
proxy-IP lock; account locks still apply. Actual proxy behavior requires coordinator
verification, including Vercel-to-Caddy forwarding; never allow arbitrary peers.

Set/rotation defaults to revoking earlier sessions; `--keep-sessions` explicitly
retains the session epoch. Tenant changes always revoke. Disable revokes both
sessions and membership. Every password-session read rechecks active/expiry/tenant
and epoch from the private file. Existing sessions cannot outlive a shortened
credential deadline. Creation expiry is min(credential expiry, now+8h). Logout,
idle/absolute expiry and tenant-selection session rotation retain prior policies.
An atomic private-file replacement and SQLite transaction use the same writer
fence; config reads need no writable private mount. If operator publication fails,
authentication fails closed through scope/epoch/membership validation.

## Migration, compatibility and rollback

Existing `hosted_schema=1`, sessions/invitations/memberships and immutable result
rows are unchanged. Startup transaction adds `access_auth_schema(version=1)`,
`access_sessions(sid_hash,role,session_epoch)`,
`access_login_failures(subject_hash,attempted)` plus index,
`access_login_locks(subject_hash,locked_until)`, and
`access_auth_audit(created,event,role,ip_hash)`. Repeated startup is idempotent;
unknown extension versions are rejected. No historical document/decision rewrite.
Access-session links and auth private data are excluded from ordinary backup;
the private credential file is managed separately, never copied into a web build.
Old control DBs remain usable; old application versions ignore these extra tables.
Rollback MUST first run new CLI `access-password disable` for both roles, committing
session/membership revocation before switching to old code (which lacks dynamic
file/epoch checks). Then restore earlier frontend/backend revisions. Leave extra
tables and ledger/result rows intact; do not restore money/deletion state. Re-enable
only via explicit new `set` after the password-aware backend is active.

## Coordinator-only application order (no deployment performed by A1)

1. Integrate the A1 backend commit on int-20261011 and frontend commit on
   a1-password; review and apply the existing drain/wait-idle/image-update flow.
   Preserve APP_ORIGIN, runtime money limits and all existing private bindings.
2. Copy `/path/to/operator/proofops-deploy/access/admin.txt` and `organizer.txt` through
   the established private channel to a temporary server directory `/srv/proofops/access-input/`
   with0700 directory/0600 files. Never paste secrets into argv, env, terminals or
   the report. Set `PROOFOPS_TENANT_ID` to the verified existing tenant UUID. Use the
   new image and runtime environment via the established coordinator procedure.
3. Run the CLI in a one-off new-image container with the data volume and a **writable**
   bind of `/srv/proofops/private:/run/private` plus the private input directory
   mounted read-only at `/run/access-input`; run as the existing UID10001. API/worker
   retain the ordinary read-only private bind. Parent/file ownership must allow UID10001.
   From the server, with `$A1_IMAGE` set to the integrated new image and the existing
   tenant verified, the complete command sequence is:

```sh
docker run --rm --network none --user 10001:10001 --env-file /srv/proofops/runtime.env -v /srv/proofops/data:/data -v /srv/proofops/private:/run/private -v /srv/proofops/access-input:/run/access-input:ro "$A1_IMAGE" python scripts/hosted_control.py access-password set --role admin --tenant "$PROOFOPS_TENANT_ID" --expires 2026-10-20T23:59:00+09:00 --from-file /run/access-input/admin.txt --config /run/private/access.json --revoke-sessions
docker run --rm --network none --user 10001:10001 --env-file /srv/proofops/runtime.env -v /srv/proofops/data:/data -v /srv/proofops/private:/run/private -v /srv/proofops/access-input:/run/access-input:ro "$A1_IMAGE" python scripts/hosted_control.py access-password set --role organizer --tenant "$PROOFOPS_TENANT_ID" --expires 2026-10-20T23:59:00+09:00 --from-file /run/access-input/organizer.txt --config /run/private/access.json --revoke-sessions
```

4. The server holds0600 `/srv/proofops/private/access.json` with hashes only. Remove
   the temporary server plaintext input files after hashing; keep the local0600
   delivery files private. Start the new API and verify production login/cookies,
   denial from preview Origin, both roles, owner-only organizer reads and unchanged
   runtime budgets. Do not print request/cookie bodies. Production checks are not_run
   here; no AWS/model call, push, EC2 change or runtime.env edit is authorized to A1.
5. Frontend Vercel preview is coordinator-only: from a1-password run the existing
   project-linked `vercel deploy` command without `--prod` after authorization. Review
   UI with intercepted Playwright fixtures; real preview login must remain403. A1's
   local built preview and fixture captures are not a deployed Vercel preview.

Rotation repeats `set --from-file <new0600file> --revoke-sessions`; keeping sessions
requires explicit `--keep-sessions`. Emergency disable and pre-rollback sequence:

```sh
python scripts/hosted_control.py access-password disable --role admin --config /run/private/access.json
python scripts/hosted_control.py access-password disable --role organizer --config /run/private/access.json
```
