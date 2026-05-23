"""Tests for the project notes module."""

from datetime import datetime

import pytest

from smaug.notes import (
    NoteMetadata,
    add_note,
    import_note,
    list_notes,
    remove_note,
    show_note,
)


@pytest.fixture
def data_dir(tmp_path):
    """Create a minimal data directory with a project."""
    projects_dir = tmp_path / "projects" / "TESTPROJ"
    projects_dir.mkdir(parents=True)
    return tmp_path


class TestAddNote:
    def test_creates_file(self, data_dir):
        path = add_note(data_dir, "TESTPROJ", "My Title", "Some content.")
        assert path.exists()
        assert path.suffix == ".md"

    def test_frontmatter_included(self, data_dir):
        path = add_note(data_dir, "TESTPROJ", "My Title", "Body text.")
        content = path.read_text()
        assert "---" in content
        assert "title: My Title" in content
        assert "Body text." in content

    def test_timestamp_in_filename(self, data_dir):
        now = datetime(2026, 3, 15, 10, 30)
        path = add_note(data_dir, "TESTPROJ", "Budget Review", "Notes.", created=now)
        assert path.name.startswith("2026-03-15_")
        assert "budget_review" in path.name

    def test_tags_stored(self, data_dir):
        path = add_note(data_dir, "TESTPROJ", "Tagged", "Content.", tags=["budget", "q1"])
        content = path.read_text()
        assert "budget" in content
        assert "q1" in content

    def test_collision_avoidance(self, data_dir):
        now = datetime(2026, 1, 1, 12, 0)
        p1 = add_note(data_dir, "TESTPROJ", "Same", "First.", created=now)
        p2 = add_note(data_dir, "TESTPROJ", "Same", "Second.", created=now)
        assert p1 != p2
        assert p1.exists()
        assert p2.exists()

    def test_creates_notes_dir(self, tmp_path):
        """Notes dir is created automatically even if project dir doesn't exist yet."""
        path = add_note(tmp_path, "NEWPROJ", "First", "Hello.")
        assert path.exists()
        assert "NEWPROJ" in str(path)
        assert "notes" in str(path)


class TestListNotes:
    def test_empty(self, data_dir):
        notes = list_notes(data_dir, "TESTPROJ")
        assert notes == []

    def test_returns_added_notes(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Note A", "Content A.")
        add_note(data_dir, "TESTPROJ", "Note B", "Content B.")
        notes = list_notes(data_dir, "TESTPROJ")
        assert len(notes) == 2
        titles = {n.title for n in notes}
        assert titles == {"Note A", "Note B"}

    def test_sorted_newest_first(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Old", "Old.", created=datetime(2025, 1, 1))
        add_note(data_dir, "TESTPROJ", "New", "New.", created=datetime(2026, 6, 1))
        notes = list_notes(data_dir, "TESTPROJ")
        assert notes[0].title == "New"
        assert notes[1].title == "Old"

    def test_metadata_fields(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Check Fields", "Body.", tags=["a", "b"])
        notes = list_notes(data_dir, "TESTPROJ")
        assert len(notes) == 1
        note = notes[0]
        assert isinstance(note, NoteMetadata)
        assert note.title == "Check Fields"
        assert isinstance(note.created, datetime)
        assert note.filename.endswith(".md")
        assert "a" in note.tags


class TestShowNote:
    def test_by_index(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Only Note", "The body.")
        content, error = show_note(data_dir, "TESTPROJ", "1")
        assert error is None
        assert content is not None
        assert "The body." in content

    def test_by_title_substring(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Budget Review Q1", "Details.")
        content, error = show_note(data_dir, "TESTPROJ", "budget")
        assert error is None
        assert content is not None
        assert "Details." in content

    def test_not_found(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Something", "Content.")
        content, error = show_note(data_dir, "TESTPROJ", "nonexistent")
        assert content is None
        assert error is not None

    def test_index_out_of_range(self, data_dir):
        add_note(data_dir, "TESTPROJ", "One", "Body.")
        content, error = show_note(data_dir, "TESTPROJ", "5")
        assert content is None
        assert error is not None
        assert "out of range" in error

    def test_empty_project(self, data_dir):
        content, error = show_note(data_dir, "TESTPROJ", "1")
        assert content is None
        assert error is not None
        assert "No notes" in error


class TestRemoveNote:
    def test_remove_by_index(self, data_dir):
        add_note(data_dir, "TESTPROJ", "To Remove", "Gone.")
        title, error = remove_note(data_dir, "TESTPROJ", "1")
        assert error is None
        assert title == "To Remove"
        # Should be gone
        notes = list_notes(data_dir, "TESTPROJ")
        assert len(notes) == 0

    def test_remove_by_title(self, data_dir):
        add_note(data_dir, "TESTPROJ", "Kill This", "Bye.")
        title, error = remove_note(data_dir, "TESTPROJ", "kill")
        assert error is None
        assert title == "Kill This"

    def test_remove_not_found(self, data_dir):
        title, error = remove_note(data_dir, "TESTPROJ", "1")
        assert title is None
        assert error is not None


class TestImportNote:
    def test_import_plain_file(self, data_dir, tmp_path):
        # Create a source file
        src = tmp_path / "analysis.md"
        src.write_text("# My Analysis\n\nSome findings.")

        path = import_note(data_dir, "TESTPROJ", src, title="Imported Analysis")
        assert path.exists()

        content = path.read_text()
        assert "title: Imported Analysis" in content
        assert "Some findings." in content

    def test_import_with_frontmatter(self, data_dir, tmp_path):
        src = tmp_path / "with_meta.md"
        src.write_text("---\ntitle: Original Title\ntags: [a, b]\n---\n\nBody content.")

        path = import_note(data_dir, "TESTPROJ", src)
        assert path.exists()

        # Should use the original title from frontmatter
        notes = list_notes(data_dir, "TESTPROJ")
        assert len(notes) == 1
        assert notes[0].title == "Original Title"

    def test_import_title_override(self, data_dir, tmp_path):
        src = tmp_path / "doc.md"
        src.write_text("---\ntitle: Old Title\n---\n\nBody.")

        import_note(data_dir, "TESTPROJ", src, title="New Title")
        notes = list_notes(data_dir, "TESTPROJ")
        assert notes[0].title == "New Title"

    def test_import_adds_tags(self, data_dir, tmp_path):
        src = tmp_path / "tagged.md"
        src.write_text("Content only, no frontmatter.")

        import_note(data_dir, "TESTPROJ", src, tags=["imported", "review"])
        notes = list_notes(data_dir, "TESTPROJ")
        assert "imported" in notes[0].tags

    def test_import_missing_file(self, data_dir):
        with pytest.raises(FileNotFoundError):
            import_note(data_dir, "TESTPROJ", "/nonexistent/file.md")

    def test_import_preserves_mtime_as_created(self, data_dir, tmp_path):
        import os

        src = tmp_path / "old_file.md"
        src.write_text("Old content.")
        # Set mtime to a known date
        target_time = datetime(2025, 6, 15, 10, 0).timestamp()
        os.utime(src, (target_time, target_time))

        import_note(data_dir, "TESTPROJ", src, title="Old Doc")
        notes = list_notes(data_dir, "TESTPROJ")
        assert notes[0].created.year == 2025
        assert notes[0].created.month == 6
