"""Nonblocking receipt-root exclusion, released by close or process death."""

import errno
import sys
from pathlib import Path
from typing import BinaryIO


def acquire_operation_lock(path: Path) -> BinaryIO:
    """Return the held handle, or raise BlockingIOError for a busy root.

    Never unlink the lock file: replacing its inode would let contenders own
    different locks. Windows locks byte zero even on an empty file, so no
    initialization write can race a holder. Closing the handle releases either
    platform's kernel lock, including abnormal process termination.
    """
    if sys.platform == "win32":
        import msvcrt
    else:
        import fcntl

    handle = path.open("a+b")
    try:
        if sys.platform == "win32":
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise BlockingIOError(exc.errno, "operation lock busy") from exc
                raise
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BaseException:
        handle.close()
        raise
