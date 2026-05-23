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


@contextlib.contextmanager
def yaml_transaction(file_path: Path):
    """
    Context manager for atomic YAML read-modify-write transactions with locking and backups.
    Preserves comments, quoting styles, and indentation using ruamel.yaml.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = file_path.with_suffix(file_path.suffix + ".lock")

    # 1. Advisory lock
    with open(lock_file, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
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
            with contextlib.suppress(OSError):
                os.unlink(lock_file)


def git_commit_change(data_dir: str | Path, message: str) -> bool:
    """
    Automatically commit any modified files in the data directory to Git,
    if it is initialized as a Git repository.
    """
    data_path = Path(data_dir).expanduser()
    git_dir = data_path / ".git"
    if not git_dir.exists():
        return False

    try:
        # Run git add for all changed/untracked files inside data_path
        subprocess.run(["git", "add", "."], cwd=str(data_path), capture_output=True, check=True)
        # Check if there are changes staged
        diff_status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=str(data_path), capture_output=True
        )
        if diff_status.returncode != 0:
            # Staged changes exist, commit them
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(data_path),
                capture_output=True,
                check=True,
            )
            return True
    except Exception:
        # Fail silently to avoid breaking the core command on environmental issues
        return False
    return False
