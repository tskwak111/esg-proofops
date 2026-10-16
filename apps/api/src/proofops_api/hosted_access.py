"""Private scrypt credentials, durable failure locks and reusable hosted sessions.

Credential files never contain plaintext. Password verification is serialized by
the existing SQLite writer fence, bounding KDF memory and concurrent attempts.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from proofops_api.hosted_store import HostedError, digest, identifier

ROLES = ("admin", "organizer")
PREFIX = "access-password:"
SCRYPT = {"n": 32768, "r": 8, "p": 3, "dklen": 32, "maxmem": 64 * 1024 * 1024}


def user_for(role: str) -> str:
    if role not in ROLES:
        raise ValueError("ACCESS_ROLE_INVALID")
    return PREFIX + role


def is_organizer(auth) -> bool:
    return auth.user_sub == user_for("organizer")


def read_password(path: Path) -> str:
    with _private_open(path) as stream:
        raw = stream.read(1025)
    if len(raw) > 1024:
        raise ValueError("ACCESS_PASSWORD_FILE_INVALID")
    try:
        value = raw.decode("utf-8").removesuffix("\n").removesuffix("\r")
    except UnicodeError:
        raise ValueError("ACCESS_PASSWORD_FILE_INVALID") from None
    if not 16 <= len(value) <= 128 or "\n" in value or "\r" in value:
        raise ValueError("ACCESS_PASSWORD_LENGTH_INVALID")
    return value


@contextmanager
def _private_open(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("ACCESS_FILE_PERMISSIONS_INVALID")
        yield stream


class AccessPasswords:
    def __init__(self, store):
        self.store = store
        self.path = store.settings.access_config

    @staticmethod
    def migrate(db):
        db.execute("CREATE TABLE IF NOT EXISTS access_auth_schema (version INTEGER PRIMARY KEY)")
        db.execute("INSERT OR IGNORE INTO access_auth_schema VALUES (1)")
        if [r[0] for r in db.execute("SELECT version FROM access_auth_schema")] != [1]:
            raise ValueError("ACCESS_SCHEMA_UNSUPPORTED")
        db.execute(
            "CREATE TABLE IF NOT EXISTS access_sessions (sid_hash TEXT PRIMARY KEY, "
            "role TEXT NOT NULL, session_epoch TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS access_login_failures "
            "(subject_hash TEXT NOT NULL, attempted REAL NOT NULL)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS access_failure_subject "
            "ON access_login_failures(subject_hash,attempted)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS access_login_locks "
            "(subject_hash TEXT PRIMARY KEY, locked_until REAL NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS access_auth_audit "
            "(created REAL NOT NULL,event TEXT NOT NULL,role TEXT NOT NULL,ip_hash TEXT)"
        )

    def _read(self):
        if self.path is None:
            return {"version": 1, "accounts": {}}
        try:
            with _private_open(self.path) as stream:
                data = stream.read(16385)
        except FileNotFoundError:
            return {"version": 1, "accounts": {}}
        except ValueError:
            raise HostedError("ACCESS_CONFIG_INVALID", 503) from None
        try:
            if len(data) > 16384:
                raise ValueError()
            config = json.loads(data)
            if set(config) != {"version", "accounts"} or config["version"] != 1:
                raise ValueError()
            for role, account in config["accounts"].items():
                user_for(role)
                if set(account) != {
                    "tenant",
                    "role",
                    "expires",
                    "active",
                    "salt",
                    "hash",
                    "session_epoch",
                    "kdf",
                }:
                    raise ValueError()
                identifier(account["tenant"])
                if (
                    account["role"] != role
                    or type(account["active"]) is not bool
                    or type(account["expires"]) not in (int, float)
                    or not math.isfinite(account["expires"])
                    or account["kdf"] != "scrypt-v1"
                    or len(bytes.fromhex(account["salt"])) != 16
                    or len(bytes.fromhex(account["hash"])) != 32
                    or len(bytes.fromhex(account["session_epoch"])) != 16
                ):
                    raise ValueError()
            return config
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HostedError("ACCESS_CONFIG_INVALID", 503) from None

    @contextmanager
    def _edit(self):
        if self.path is None:
            raise ValueError("HOSTED_ACCESS_CONFIG_REQUIRED")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            self.path.with_suffix(self.path.suffix + ".lock"),
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "a+b") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            # All reads and mutations share the SQLite fence. Runtime readers
            # need no file lock/write permission on the read-only private mount.
            with self.store.transaction() as db:
                yield db, self._read()

    def _write(self, config):
        with NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
            staged = Path(stream.name)
            try:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(json.dumps(config, sort_keys=True).encode())
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(staged, self.path)
                fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                staged.unlink(missing_ok=True)

    def set_password(self, role, password, *, tenant=None, expires, now, revoke_sessions=True):
        user = user_for(role)
        if not isinstance(password, str) or not 16 <= len(password) <= 128:
            raise ValueError("ACCESS_PASSWORD_LENGTH_INVALID")
        if type(expires) not in (int, float) or not math.isfinite(expires):
            raise ValueError("ACCESS_EXPIRATION_INVALID")
        salt = secrets.token_bytes(16)
        hashed = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT).hex()
        with self._edit() as (db, config):
            previous = config["accounts"].get(role)
            tenant = tenant or (previous["tenant"] if previous else None)
            identifier(tenant)
            # Changing scope always invalidates sessions, even with keep-sessions.
            revoke = revoke_sessions or previous is None or previous["tenant"] != tenant
            epoch = secrets.token_hex(16) if revoke else previous["session_epoch"]
            config["accounts"][role] = dict(
                tenant=tenant,
                role=role,
                expires=expires,
                active=True,
                salt=salt.hex(),
                hash=hashed,
                session_epoch=epoch,
                kdf="scrypt-v1",
            )
            if revoke:
                db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user,))
            db.execute("UPDATE memberships SET status='revoked' WHERE user_id=?", (user,))
            db.execute(
                "INSERT INTO memberships VALUES (?,?,?,'active') "
                "ON CONFLICT(tenant_id,user_id) DO UPDATE SET role=excluded.role,status='active'",
                (tenant, user, "admin" if role == "admin" else "editor"),
            )
            self._audit(db, "password_set", role, None, now)
            self._write(config)

    def disable(self, role, *, now):
        user = user_for(role)
        with self._edit() as (db, config):
            if role in config["accounts"]:
                config["accounts"][role]["active"] = False
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user,))
            db.execute("UPDATE memberships SET status='revoked' WHERE user_id=?", (user,))
            self._audit(db, "password_disabled", role, None, now)
            self._write(config)

    def _audit(self, db, event, role, ip, now):
        db.execute(
            "INSERT INTO access_auth_audit VALUES (?,?,?,?)",
            (now, event, role, self.store.user_hash("access-ip:" + ip) if ip else None),
        )

    def session_valid(self, db, row, now):
        if not row["user_id"].startswith(PREFIX):
            return True
        linked = db.execute(
            "SELECT * FROM access_sessions WHERE sid_hash=?", (row["sid_hash"],)
        ).fetchone()
        if linked is None:
            return False
        account = self._read()["accounts"].get(linked["role"])
        return bool(
            account
            and account["active"]
            and now < account["expires"]
            and account["tenant"] == row["tenant_id"]
            and row["user_id"] == user_for(linked["role"])
            and hmac.compare_digest(account["session_epoch"], linked["session_epoch"])
        )

    def login(self, role, password, *, ip, now):
        user = user_for(role)
        subjects = [
            self.store.user_hash("access-ip:" + ip),
            self.store.user_hash("access-account:" + role),
        ]
        failure = None
        with self.store.transaction() as db:
            db.execute("DELETE FROM access_login_failures WHERE attempted<=?", (now - 600,))
            db.execute("DELETE FROM access_login_locks WHERE locked_until<=?", (now,))
            locks = db.execute(
                "SELECT max(locked_until) FROM access_login_locks " "WHERE subject_hash IN (?,?)",
                subjects,
            ).fetchone()[0]
            if locks:
                self._audit(db, "login_locked", role, ip, now)
                failure = HostedError(
                    "ACCESS_PASSWORD_LOCKED", 429, retry_after=math.ceil(locks - now)
                )
            else:
                account = self._read()["accounts"].get(role)
                # Always do one bounded KDF, including inactive/missing accounts.
                salt = bytes.fromhex(account["salt"]) if account else bytes(16)
                expected = bytes.fromhex(account["hash"]) if account else bytes(32)
                actual = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
                valid = hmac.compare_digest(actual, expected)
                membership = db.execute(
                    "SELECT role,status FROM memberships " "WHERE tenant_id=? AND user_id=?",
                    (account["tenant"] if account else "", user),
                ).fetchone()
                if (
                    valid
                    and account
                    and account["active"]
                    and now < account["expires"]
                    and membership
                    and membership["status"] == "active"
                    and membership["role"] == ("admin" if role == "admin" else "editor")
                ):
                    sid = secrets.token_urlsafe(32)
                    expires = min(now + 28800, account["expires"])
                    db.execute(
                        "INSERT INTO sessions VALUES (?,?,?,?,?,?,0)",
                        (
                            digest(sid),
                            user,
                            account["tenant"],
                            digest(self.store.sessions.csrf_token_for(sid)),
                            expires,
                            min(expires, now + 1800),
                        ),
                    )
                    db.execute(
                        "INSERT INTO access_sessions VALUES (?,?,?)",
                        (digest(sid), role, account["session_epoch"]),
                    )
                    # Success does not erase other attackers' failure history.
                    self._audit(db, "login_success", role, ip, now)
                else:
                    locked = False
                    for subject in subjects:
                        db.execute("INSERT INTO access_login_failures VALUES (?,?)", (subject, now))
                        count = db.execute(
                            "SELECT count(*) FROM access_login_failures " "WHERE subject_hash=?",
                            (subject,),
                        ).fetchone()[0]
                        if count >= 5:
                            db.execute(
                                "INSERT OR REPLACE INTO access_login_locks VALUES (?,?)",
                                (subject, now + 900),
                            )
                            locked = True
                    self._audit(db, "login_locked" if locked else "login_failed", role, ip, now)
                    failure = (
                        HostedError("ACCESS_PASSWORD_LOCKED", 429, retry_after=900)
                        if locked
                        else HostedError("ACCESS_PASSWORD_INVALID", 401)
                    )
        # Raise outside the transaction so failed-attempt and audit writes commit.
        if failure:
            raise failure
        return sid

    @staticmethod
    def maintain(db, now, audit_days):
        db.execute(
            "DELETE FROM access_sessions WHERE sid_hash NOT IN (SELECT sid_hash FROM sessions)"
        )
        db.execute("DELETE FROM access_login_failures WHERE attempted<=?", (now - 600,))
        db.execute("DELETE FROM access_login_locks WHERE locked_until<=?", (now,))
        db.execute("DELETE FROM access_auth_audit WHERE created<?", (now - audit_days * 86400,))
