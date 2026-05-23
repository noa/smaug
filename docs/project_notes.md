# Project Notes

Smaug supports per-project notes stored as Markdown files with YAML
frontmatter. Use notes to record budget decisions, meeting minutes,
sponsor communications, or any project-specific documentation.

## Storage

Notes are stored as individual Markdown files in each project's `notes/`
directory:

```
projects/QUASAR/notes/
├── 2025-11-15_budget_review.md
├── 2026-01-20_sponsor_call.md
└── 2026-03-10_no_cost_extension.md
```

Filenames are generated automatically from the creation date and a
slugified version of the title.

## File Format

Each note is a Markdown file with YAML frontmatter:

```markdown
---
title: Budget Review Meeting
created: 2025-11-15T14:30:00
tags: [budget, meeting]
---

## Attendees
- Jane Smith (PI)
- Program Officer

## Key Decisions
- Approved reallocation of $15k from travel to compute.
- No-cost extension request to be submitted by March.
```

## Commands

### List notes

```bash
smaug note list QUASAR
```

Notes are displayed newest first with their index, title, date, and tags.

### Show a note

By index (1-based, as shown in the list):

```bash
smaug note show QUASAR 1
```

By title substring (fuzzy matching):

```bash
smaug note show QUASAR "budget"
smaug note show QUASAR "sponsor"
```

### Add a note

With inline content:

```bash
smaug note add QUASAR "Budget Review" --message "Approved reallocation of..."
```

Using your `$EDITOR` (opens an editor for longer notes):

```bash
smaug note add QUASAR "Q3 Progress Report"
```

### Import an existing file

Import a Markdown file as a project note:

```bash
smaug note import QUASAR /path/to/meeting_notes.md --title "Sponsor Meeting"
```

If the source file has YAML frontmatter, it is preserved. Otherwise, smaug
adds frontmatter with the file's modification time as the creation date.

Tags can be added during import:

```bash
smaug note import QUASAR report.md --title "Annual Report" --tags review,sponsor
```

### Remove a note

```bash
# By index
smaug note remove QUASAR 1

# By title substring
smaug note remove QUASAR "budget"
```

## Note Resolution

When accessing notes by identifier, smaug uses the same resolution logic
as personnel names:

1. **Numeric** — treated as a 1-based index into the notes list
2. **String** — fuzzy title match (case-insensitive substring search)
3. **Filename match** — falls back to matching against the filename

If multiple notes match a substring, smaug lists the ambiguous matches:

```
Multiple notes matching 'review':
  1. Budget Review Meeting
  2. Annual Review Presentation
```

## Tags

Tags are stored in the YAML frontmatter and can be used for organization.
Currently, tags are for display purposes — there is no tag-based filtering
in the CLI (a planned future feature).

```yaml
---
title: Budget Review
created: 2025-11-15T14:30:00
tags: [budget, meeting, sponsor]
---
```
