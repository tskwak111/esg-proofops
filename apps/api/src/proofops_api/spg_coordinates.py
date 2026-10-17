"""Warm disposable W19 pages while tagging waits for its existing provider calls."""

import fcntl
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace

from proofops_api.hosted_store import HostedError, copy_verified_file


def warm(store, job, workspace):
    from proofops_api import w18_source_view as w19

    try:
        with store.transaction(readonly=True) as db:
            store._fenced(db, job, time.time())
            doc = dict(store._document(db, job["tenant_id"], job["document_id"]))
        directory = store.document_dir(job["tenant_id"], job["document_id"])
        # Parent retains the real analysis.lock throughout the child. Use an
        # authenticated private copy so W19's ordinary SH-lock reader remains
        # unchanged and cannot deadlock against that parent-owned EX lock.
        with TemporaryDirectory(prefix="spg-w19-", dir=workspace) as temporary:
            root = Path(temporary)
            copy_verified_file(directory / "original.pdf", root / "original.pdf", doc["sha256"])
            private = SimpleNamespace(root=root, document_dir=lambda *_: root)
            with w19._lock:
                pages, _ = w19._inventories(
                    private,
                    job,
                    doc,
                    set(json.loads(job["pages"])),
                    deadline=time.monotonic() + w19.W19_WARM_SECONDS,
                )
            # Fence and current source identity are checked again before any
            # derived page is installed. These pages never grant source approval.
            with store.transaction(readonly=True) as db:
                store._fenced(db, job, time.time())
                current = dict(store._document(db, job["tenant_id"], job["document_id"]))
            if current != doc or time.time() >= doc["expires"]:
                return
            scope = (str(store.root), job["tenant_id"], job["document_id"], doc["sha256"])
            with w19._lock, (store.root / "w18-coordinates.lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for page, inventory in pages.items():
                    w19._disk_inventory(directory, scope, page, doc, json.dumps(inventory).encode())
    except (OSError, ValueError, KeyError, HostedError):
        pass  # Existing W19 foreground reader retries with all original guards.


def start(store, job, workspace):
    thread = Thread(target=warm, args=(store, dict(job), workspace), daemon=True, name="spg-w19")
    thread.start()
    return thread
