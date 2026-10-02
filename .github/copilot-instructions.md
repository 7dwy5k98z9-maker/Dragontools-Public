# DragonTools Copilot Instructions

## Project context
- This repository contains DragonTools V9.8.7, a Windows desktop application for media analysis, conversion, metadata handling, and renaming.
- Main entry point: `DragonToolsV9.py`
- Source package root: `dragontools/`
- External tools are expected under `third_party/` and are not checked into Git.

## Working style
- Prefer small, focused edits in the relevant module rather than broad refactors.
- Keep compatibility layers and legacy façades in place when the project already depends on them.
- Preserve Windows-specific behavior and the existing PyQt/PySide architecture unless a task clearly requires otherwise.
- Favor explicit, readable code over clever shortcuts.
- Split modules by responsibility, ownership and side effects, not physical line counts. A cohesive module may exceed 300 lines; see `ARCHITECTURE_REVIEW.md`.
- Preserve semantic architecture contracts and do not regenerate `architecture_debt.json` to silence new complexity violations.

## Validation
- Use the project test suite when changing behavior: `python -m pytest -m "not dv_hdr_integration"`.
- For scope-limited fixes, prefer the smallest relevant test target instead of the full suite.
- Do not claim success without fresh verification output from the relevant command.

## Safety and repo conventions
- Do not add secrets, API keys, user credentials, or personal data to the repository.
- Do not modify third-party binaries or vendored external tool directories.
- Keep generated output such as `build/`, `dist/`, and temp pytest folders out of version control.
- Prefer repository-specific paths and existing naming patterns when creating new modules.

## Key directories
- `dragontools/core/` for core logic and orchestration
- `dragontools/gui/` for UI widgets and dialogs
- `dragontools/tests/` for pytest coverage
- `third_party/` for installed external programs

## Development notes
- This project is Windows-focused and may rely on external executables like FFmpeg, mkvmerge, MediaInfo, MP4Box, and similar tools.
- When a change touches metadata, conversion workflows, or file-system operations, consider error handling, rollback safety, and idempotence.
- If a change is uncertain, inspect the nearest existing implementation before introducing a new pattern.
