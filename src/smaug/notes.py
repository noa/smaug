"""
Project notes management.

Stores per-project notes as timestamped Markdown files with YAML
frontmatter in ``projects/<PROJECT>/notes/``.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class NoteMetadata:
    """Metadata for a project note."""

    title: str
    created: datetime
    filename: str
    tags: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        """Basename without extension for display."""
        return Path(self.filename).stem


def _notes_dir(data_dir: str | Path, project_id: str) -> Path:
    """Return the notes directory for a project, creating it if needed."""
    d = Path(data_dir) / "projects" / project_id / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(title: str) -> str:
    """Convert a title to a filesystem-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "_", slug)
    slug = slug.strip("_")
    return slug[:80] if slug else "note"


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse YAML frontmatter from a markdown string.

    Returns (metadata_dict, body) where body is the content after
    the frontmatter block.
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    import yaml

    raw = text[3:end].strip()
    try:
        meta = yaml.safe_load(raw) or {}
    except Exception:
        meta = {}

    body = text[end + 3 :].lstrip("\n")
    return meta, body


def _format_frontmatter(title: str, created: datetime, tags: list[str] | None = None) -> str:
    """Generate YAML frontmatter block."""
    lines = ["---"]
    lines.append(f"title: {title}")
    lines.append(f"created: {created.strftime('%Y-%m-%dT%H:%M:%S')}")
    if tags:
        tag_str = ", ".join(tags)
        lines.append(f"tags: [{tag_str}]")
    lines.append("---")
    return "\n".join(lines)


def list_notes(data_dir: str | Path, project_id: str) -> list[NoteMetadata]:
    """List all notes for a project, sorted by creation date (newest first)."""
    notes_path = _notes_dir(data_dir, project_id)
    results: list[NoteMetadata] = []

    for md_file in sorted(notes_path.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(text)

        title = str(meta.get("title", md_file.stem))
        created_raw = meta.get("created")
        if isinstance(created_raw, datetime):
            created = created_raw
        elif isinstance(created_raw, str):
            try:
                created = datetime.fromisoformat(created_raw)
            except ValueError:
                created = datetime.fromtimestamp(md_file.stat().st_mtime)
        else:
            created = datetime.fromtimestamp(md_file.stat().st_mtime)

        tags_raw = meta.get("tags", [])
        tags = list(tags_raw) if isinstance(tags_raw, list) else []

        results.append(
            NoteMetadata(
                title=title,
                created=created,
                filename=md_file.name,
                tags=tags,
            )
        )

    # Sort newest first
    results.sort(key=lambda n: n.created, reverse=True)
    return results


def add_note(
    data_dir: str | Path,
    project_id: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    created: datetime | None = None,
) -> Path:
    """Create a new note for a project.

    Args:
        data_dir: Root data directory.
        project_id: Project short name (e.g. ``ARTS``).
        title: Human-readable title.
        content: Markdown body content.
        tags: Optional list of tags.
        created: Override creation timestamp (defaults to now).

    Returns:
        Path to the created note file.
    """
    now = created or datetime.now()
    slug = _slugify(title)
    date_prefix = now.strftime("%Y-%m-%d")
    filename = f"{date_prefix}_{slug}.md"

    notes_path = _notes_dir(data_dir, project_id)
    filepath = notes_path / filename

    # Avoid collisions
    counter = 1
    while filepath.exists():
        filename = f"{date_prefix}_{slug}_{counter}.md"
        filepath = notes_path / filename
        counter += 1

    frontmatter = _format_frontmatter(title, now, tags)
    full_content = f"{frontmatter}\n\n{content}\n"
    filepath.write_text(full_content, encoding="utf-8")
    return filepath


def show_note(
    data_dir: str | Path, project_id: str, identifier: str
) -> tuple[str | None, str | None]:
    """Retrieve a note by index (1-based) or title substring.

    Args:
        data_dir: Root data directory.
        project_id: Project short name.
        identifier: Either a 1-based numeric index or a title substring.

    Returns:
        Tuple of (content, error_message).
        On success: (full file content, None).
        On error: (None, error description).
    """
    notes = list_notes(data_dir, project_id)
    if not notes:
        return None, f"No notes found for project {project_id}"

    note = _resolve_note(notes, identifier)
    if isinstance(note, str):
        return None, note  # Error message

    filepath = _notes_dir(data_dir, project_id) / note.filename
    return filepath.read_text(encoding="utf-8"), None


def remove_note(
    data_dir: str | Path, project_id: str, identifier: str
) -> tuple[str | None, str | None]:
    """Remove a note by index (1-based) or title substring.

    Returns:
        Tuple of (removed_title, error_message).
    """
    notes = list_notes(data_dir, project_id)
    if not notes:
        return None, f"No notes found for project {project_id}"

    note = _resolve_note(notes, identifier)
    if isinstance(note, str):
        return None, note

    filepath = _notes_dir(data_dir, project_id) / note.filename
    filepath.unlink()
    return note.title, None


def import_note(
    data_dir: str | Path,
    project_id: str,
    source_path: str | Path,
    title: str | None = None,
    tags: list[str] | None = None,
) -> Path:
    """Import an existing file as a project note.

    If the source file has YAML frontmatter, it is preserved.
    Otherwise, frontmatter is added with the file's modification time
    as the creation date.

    Args:
        data_dir: Root data directory.
        project_id: Project short name.
        source_path: Path to the file to import.
        title: Override title (defaults to filename stem).
        tags: Optional tags to add.

    Returns:
        Path to the imported note file.
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    content = src.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(content)

    # Use existing title from frontmatter, or parameter, or filename
    note_title = title or str(meta.get("title", src.stem.replace("_", " ")))

    # Use file mtime as creation date
    file_mtime = datetime.fromtimestamp(src.stat().st_mtime)
    created = file_mtime

    if isinstance(meta.get("created"), str | datetime):
        with contextlib.suppress(ValueError):
            created = datetime.fromisoformat(str(meta["created"]))

    # Merge tags
    tags_val = meta.get("tags")
    existing_tags = [str(t) for t in tags_val] if isinstance(tags_val, list) else []
    all_tags = list(set(existing_tags + (tags or [])))

    return add_note(
        data_dir, project_id, note_title, body or content, tags=all_tags, created=created
    )


def _resolve_note(notes: list[NoteMetadata], identifier: str) -> NoteMetadata | str:
    """Resolve a note by index or fuzzy title match.

    Returns the matched NoteMetadata, or an error string.
    """
    # Try numeric index
    if identifier.isdigit():
        idx = int(identifier)
        if 1 <= idx <= len(notes):
            return notes[idx - 1]
        return f"Index {idx} out of range (1-{len(notes)})"

    # Fuzzy title match
    query = identifier.lower()
    matches = [n for n in notes if query in n.title.lower()]

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        match_list = "\n".join(f"  {i + 1}. {n.title}" for i, n in enumerate(matches))
        return f"Multiple notes matching '{identifier}':\n{match_list}"

    # Try filename match
    matches = [n for n in notes if query in n.filename.lower()]
    if len(matches) == 1:
        return matches[0]

    return f"No note found matching '{identifier}'"
