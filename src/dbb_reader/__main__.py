import argparse
from pathlib import Path

from .config import load_config
from .library import scan_library


def main():
    parser = argparse.ArgumentParser(description="Read a local EPUB library in your terminal.")
    parser.add_argument("--library", type=Path, help="Override the configured library directory")
    parser.add_argument("--config", type=Path, help="Use an alternate TOML configuration")
    parser.add_argument("--list", action="store_true", help="List metadata without starting the TUI")
    args = parser.parse_args()
    config, warning = load_config(args.config)
    if args.library:
        from dataclasses import replace
        config = replace(config, library=str(args.library.expanduser().resolve()))
    if args.list:
        if warning:
            parser.exit(2, warning + "\n")
        try:
            for entry in scan_library(Path(config.library)):
                print(f"{entry.category}\t{entry.title}\t{entry.author}\t{'EPUB' if entry.supported else 'PDF (unsupported)'}")
        except ValueError as exc:
            parser.exit(2, str(exc) + "\n")
    else:
        # Imported lazily so metadata tools work without initializing the TUI.
        from .app import ReaderApp
        ReaderApp(config, config_file=args.config, warning=warning).run(mouse=False)


if __name__ == "__main__":
    main()
