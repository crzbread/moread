# dbb-reader v1

A personal Python terminal EPUB reader. The existing library is read-only:
`/Users/dbb/Documents/Self/Books` (161 EPUBs and 16 PDFs at initial inspection).

## User experience

- Launch into a selectable bookshelf, with existing directory categories, search by title/author, recent reading and per-book progress. Prefer EPUB metadata over noisy filenames.
- Enter opens an EPUB at that book's last reading location. PDFs remain listed and clearly unsupported.
- Chinese text layout, chapter navigation/table of contents, page mode by default and configurable scroll mode. Preserve native terminal text selection/copy; do not capture mouse by default.
- Full-book text-based progress bar and percentage. Store logical chapter/text location rather than screen page numbers, preserving location across width changes and restarts.
- Save progress as reading moves. Each book has independent state.
- Global configurable panic key, default Ctrl+D, exits from every screen including search/settings and restores shell via alternate-screen cleanup. No book text or title should intentionally be sent to shell scrollback/title. Test actual Herdr behavior. Opening an extra macOS Terminal tab is deferred.
- Editable TOML config plus a simple settings UI: library path, page/scroll mode, reading width, theme and panic key. User data stays outside repository and books.
- Missing/invalid books, malformed config, empty libraries and unsupported PDFs must produce understandable recoverable behavior.
- No script conversion, annotations, highlighting, explicit bookmark management, online integrations or PDF rendering in v1.

## Implementation and validation

- Use mature Python TUI/EPUB components where useful. Avoid unnecessary architecture and dependencies.
- Large local samples include a 124 MB Jin Yong collection (579 spine items) and a 1415-spine-item novel. Avoid freezing bookshelf or disabling panic while loading.
- Use meaningful tests for position persistence, layout, EPUB ordering, config and global panic behavior. Exercise real local EPUB samples read-only. Never commit book contents or extracted text.
- Each commit must be a complete working feature with a brief message. Do not commit half-built checkpoints. Git excludes books, environment files, caches, personal config and reading state.
- Provide installation/run instructions, controls, known limits and concise validation evidence.

## Ownership

The implementation agent owns source changes and commits. The independent same-tier reviewer inspects requirements, code, tests and commits; reports actionable issues rather than modifying implementation concurrently. The coordinating agent manages scope, fixes and final acceptance. No publishing or remote push is requested.
