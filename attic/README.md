# Attic — quarantined side projects

This directory holds material that is **not part of the N.A.L.L.Y product**.
It was moved out of the repository root to keep the project focused and
reviewable. Nothing here is loaded, imported, or referenced by the
application or its tests.

| Path | What it is | Status |
|------|------------|--------|
| `Lexi/` | Early MVP draft + research notes for a separate idea | Archived |
| `NALLYMAKES/agency-website/` | Static agency-website experiment (CSS/JS) | Archived |

Rules for `attic/`:

- Do not add imports or dependencies pointing into `attic/`.
- Do not revive anything here without opening an issue first.
- Deletion is allowed once history preserves what matters
  (`git log -- attic/` keeps the record even if files are removed).
