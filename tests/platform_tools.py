"""Launch package CLIs across Windows and POSIX without a shell."""

import os
from pathlib import Path


def esbuild_command(executable: Path) -> list[str]:
    # Windows cannot execute esbuild's Node shebang shim directly. On POSIX
    # the package may optimize that path to a native executable.
    return ["node", str(executable)] if os.name == "nt" else [str(executable)]
