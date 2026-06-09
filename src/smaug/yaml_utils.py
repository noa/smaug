"""
Robust YAML read-modify-write transactions and Git auto-commit utilities.
"""

import contextlib
import fcntl
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

_LOCK_TIMEOUT_SECONDS = 5
_LOCK_RETRY_INTERVAL = 0.1
_STALE_LOCK_AGE_SECONDS = 60


def _acquire_lock_with_timeout(lock_file: Path, timeout: float = _LOCK_TIMEOUT_SECONDS):
    """
    Acquire an advisory file lock with timeout.

    Uses non-blocking attempts with retries to prevent deadlocks from stale
    lock files left behind by crashed processes (e.g. timed-out MCP calls).
    Automatically removes stale lock files older than 60 seconds.
    """
    import time

    deadline = time.monotonic() + timeout
    lf = open(lock_file, "w")  # noqa: SIM115
    while True:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lf
        except OSError:
            # Lock is held by another process — check if stale
            try:
                age = time.time() - lock_file.stat().st_mtime
                if age > _STALE_LOCK_AGE_SECONDS:
                    # Stale lock — forcibly remove and retry
                    with contextlib.suppress(OSError):
                        os.unlink(lock_file)
                    lf.close()
                    lf = open(lock_file, "w")  # noqa: SIM115
                    continue
            except OSError:
                pass

            if time.monotonic() >= deadline:
                lf.close()
                raise TimeoutError(
                    f"Could not acquire lock on {lock_file} within {timeout}s. "
                    f"A previous operation may have crashed. "
                    f"Delete {lock_file} manually if the problem persists."
                ) from None
            time.sleep(_LOCK_RETRY_INTERVAL)


@contextlib.contextmanager
def yaml_transaction(file_path: Path):
    """
    Context manager for atomic YAML read-modify-write transactions with locking and backups.
    Preserves comments, quoting styles, and indentation using ruamel.yaml.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = file_path.with_suffix(file_path.suffix + ".lock")

    # 1. Advisory lock with timeout (prevents deadlocks from stale locks)
    lf = _acquire_lock_with_timeout(lock_file)
    try:
        # Setup YAML parser
        yaml_obj = YAML()
        yaml_obj.preserve_quotes = True
        yaml_obj.indent(mapping=2, sequence=4, offset=2)

        if file_path.exists() and file_path.stat().st_size > 0:
            with open(file_path, encoding="utf-8") as f:
                data = yaml_obj.load(f)
        else:
            data = CommentedMap()

        yield data

        # Create backup if original exists
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, backup_path)

        # Atomic write using temp file and os.replace
        temp_fd, temp_path_str = tempfile.mkstemp(
            dir=file_path.parent, prefix=file_path.name + ".tmp"
        )
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_f:
                yaml_obj.dump(data, temp_f)
            os.replace(temp_path, file_path)
        except Exception:
            if temp_path.exists():
                os.unlink(temp_path)
            raise
    finally:
        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        lf.close()
        with contextlib.suppress(OSError):
            os.unlink(lock_file)


_GIT_TIMEOUT_SECONDS = 10


def git_commit_change(data_dir: str | Path, message: str) -> bool:
    """
    Automatically commit any modified files in the data directory to Git,
    if it is initialized as a Git repository.

    All subprocess calls use a timeout to prevent hangs (e.g. from
    credential prompts, large repos, or lock contention).
    """
    data_path = Path(data_dir).expanduser()
    git_dir = data_path / ".git"
    if not git_dir.exists():
        return False

    try:
        # Run git add for all changed/untracked files inside data_path
        subprocess.run(
            ["git", "add", "."],
            cwd=str(data_path),
            capture_output=True,
            check=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        # Check if there are changes staged
        diff_status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(data_path),
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if diff_status.returncode != 0:
            # Staged changes exist, commit them
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(data_path),
                capture_output=True,
                check=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
            return True
    except subprocess.TimeoutExpired:
        # Git operation timed out — non-fatal, the YAML write already succeeded
        return False
    except Exception:
        # Fail silently to avoid breaking the core command on environmental issues
        return False
    return False
