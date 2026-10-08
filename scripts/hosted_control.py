"""Operator CLI for the separate hosted volume. Never prints credentials except a new invite."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from proofops_api.hosted_store import HostedSettings, HostedStore


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite")
    invite.add_argument("--tenant", required=True)
    invite.add_argument("--user", required=True)
    invite.add_argument("--role", choices=("viewer", "editor", "reviewer", "admin"), required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    sub.add_parser("maintain")
    for command in ("backup", "restore"):
        item = sub.add_parser(command)
        item.add_argument("--path", type=Path, required=True)
    args = parser.parse_args()
    store = HostedStore(HostedSettings.from_env(os.environ))
    if args.command == "invite":
        print(store.invite(args.tenant, args.user, args.role, now=time.time()))
    elif args.command == "maintain":
        store.maintain(now=time.time())
    elif args.command == "backup":
        store.backup(args.path, now=time.time())
    elif args.command == "restore":
        store.restore(args.path, now=time.time())
    elif args.command == "worker":
        while True:
            store.maintain(now=time.time())
            store.tick(now=time.time())
            if args.once:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
