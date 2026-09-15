import argparse
import json
import multiprocessing as mp
from pathlib import Path
import threading
from .types import Settings


def main():
    import sys
    for stream in [sys.stdout, sys.stderr]:
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Local course media and document extraction')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mode', choices=['quality', 'fast'], default='quality')
    parser.add_argument('--device', choices=['auto', 'cpu'], default='auto')
    parser.add_argument('--language', default='en')
    parser.add_argument('--glossary', type=Path)
    parser.add_argument('--no-subfolders', action='store_true')
    parser.add_argument('--no-combined', action='store_true')
    parser.add_argument('--srt', action='store_true')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--tessdata', default='')
    parser.add_argument('--ocr-language', default='eng')
    parser.add_argument('--ebook-convert', default='')
    parser.add_argument('--diagnostics', action='store_true')
    args = parser.parse_args()
    if args.diagnostics:
        from .diagnostics import diagnose
        report = diagnose(args.tessdata, args.ebook_convert, args.ocr_language)
        print(json.dumps(report, indent=2))
        raise SystemExit(1 if any(str(value).startswith('FAILED:') for value in report['dependencies'].values()) else 0)
    if args.input is None and args.output is None:
        from .gui import main as gui_main
        gui_main()
        return
    if args.input is None or args.output is None:
        parser.error('--input and --output must be supplied together')
    from .engine import run_session
    glossary = args.glossary.read_text(encoding='utf-8-sig') if args.glossary else ''
    if len(glossary) > 1000:
        parser.error('Glossary must contain at most 1,000 characters.')
    settings = Settings(recursive=not args.no_subfolders, mode=args.mode, device=args.device,
                        language=args.language, glossary=glossary, srt=args.srt, combined=not args.no_combined,
                        offline=args.offline, tessdata=args.tessdata, ocr_language=args.ocr_language,
                        ebook_convert=args.ebook_convert)
    cancel = threading.Event()
    import signal
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    try:
        state = run_session(args.input, args.output, settings, cancel,
                            lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    except Exception as exc:
        parser.exit(1, f'Error: {exc}\n')
    raise SystemExit(0 if state['status'] == 'finished' else 2)


if __name__ == '__main__':
    mp.freeze_support()
    main()
