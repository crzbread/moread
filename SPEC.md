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

## User steering: bookshelf first

The first TUI preview was not satisfactory. Pause further reader development and
focus the current milestone on a filesystem-style bookshelf. Start at the Books
root showing real folders and root-level books, enter a folder to see its children,
and show the current path with a parent navigation row. Avoid a flat all-books
table with category dropdown. Keyboard interactions should be obvious: Up/Down
select, Enter/Right open, Left/Backspace go to parent, Escape clears search first
then goes back, Ctrl+D exits globally. Show concise Traditional Chinese labels and
contextual help; search and settings should have discoverable labels. Preserve
existing reader work but do not expand it in this milestone. Validate the revised
bookshelf and get user feedback before resuming reader work.

Arrow-key clarification: shelf Up/Down selects, Right opens, Left returns to parent;
Enter also opens. Reader Left/Right pages and Up/Down scrolls one line, independent
of page mode; PageUp/PageDown are optional aliases, never required. Text inputs
retain Left/Right cursor movement and Backspace deletion. Apply the small reader
key mapping correction only; continue focusing development on the bookshelf.

Search matches Simplified/Traditional Chinese equivalently for titles and authors
by default, while preserving all displayed metadata and original book contents.
Use a maintained conversion library rather than an ad-hoc character table. This
is search normalization only, not reader text conversion or semantic synonyms.

Settings shortcut decision: advertise F2, using traditional terminal key sequences.
Keep Tab-to-settings-button as fallback; do not advertise Ctrl+,.

## Bookshelf spacing refinement

User finds typography crowded and requests reference to other terminal tools.
Use Yazi (https://github.com/sxyazi/yazi) and superfile
(https://superfile.dev/overview/) as layout references: clearer whitespace,
separated path/search/list/help regions, calmer secondary metadata and comfortable
rows, responsive compact layout for short/narrow terminals. Preserve folder-first
navigation, arrows, search normalization and panic behavior. Font itself belongs
to the terminal; do not change terminal settings. No reader feature expansion.

Navigation correction: Right must ONLY enter directories, never open a book.
Enter opens a selected directory or book. Left returns to the parent directory
on the shelf. Reading keeps Left/Right paging and Escape returning to shelf.
Show contextual hints so repeatedly pressing Right cannot accidentally enter
reading. Add regression coverage for EPUB and PDF right-arrow no-op.

Additional controls: q exits the application outside editable inputs. In search
and settings text inputs q remains ordinary text; Ctrl+D remains global panic.
Translate bottom help/footer descriptions throughout existing screens to
Traditional Chinese, including reading and loading, without expanding features.

## Reader return and settings repair

Keep q as application exit outside editable inputs. Esc, Backspace and b return
from reading to the bookshelf; compact Chinese reader help must keep return,
F2 settings and panic discoverable at 40x18 and 80x24. F2 and s open the same
settings screen from reading. Keep Save/Cancel and errors outside scrolling
fields, focus a sensible input immediately, support Ctrl+S save and Esc cancel,
and preserve logical position while applying width/theme changes.

Retain the TOML mode key for compatibility, but label it 空白鍵動作 in settings:
page = 翻一頁, scroll = 捲動一行. Mode affects Space only. Left/Right continue
paging and Up/Down continue moving one line in both modes.

If panic_key is ctrl+s, panic retains priority. Suppress the settings save shortcut
and its hint; advertise Tab to the Save button followed by Enter instead.
