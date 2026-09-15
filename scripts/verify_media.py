"""Real inference smoke checks on generated recordings, not an accuracy benchmark."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dataclasses import asdict
import gc
import json
import threading
import time
from course_transcriber.media import MediaSession, gpu_memory
from course_transcriber.types import Settings


def main():
    root = Path(__file__).resolve().parent.parent
    output = root / 'tmp' / 'media-verification.json'
    report = {'fixture': 'Windows System.Speech synthetic course introduction; not representative course accuracy',
              'gpu': gpu_memory(), 'checks': []}
    for mode, device in [('fast', 'auto'), ('quality', 'auto'), ('fast', 'cpu')]:
        settings = Settings(mode=mode, device=device, offline=True, glossary='local transcription, source filename')
        session = MediaSession(settings, lambda text: print(text, flush=True))
        load_start = time.perf_counter()
        session.load()
        load_seconds = time.perf_counter() - load_start
        model_id = id(session.model)
        paths = sorted((root / 'tmp/fixtures/media').glob('*')) if (mode, device) == ('fast', 'auto') else [root / 'tmp/fixtures/media/lesson.wav']
        for path in paths:
            started = time.perf_counter()
            try:
                result = session.transcribe(path, threading.Event())
                check = {'mode': mode, 'requested_device': device, 'file': path.name, 'load_seconds': load_seconds,
                         'inference_seconds': time.perf_counter() - started, 'model_reused': id(session.model) == model_id,
                         'metadata': result.metadata, 'text': result.text, 'segments': len(result.segments),
                         'passed': bool(result.text.strip()) and 'course' in result.text.lower()}
            except Exception as exc:
                check = {'mode': mode, 'requested_device': device, 'file': path.name, 'passed': False, 'error': str(exc)}
            report['checks'].append(check)
            output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(check), flush=True)
        session.pipeline = session.model = None
        del session
        gc.collect()
    assert all(check['passed'] for check in report['checks']), 'An inference smoke check failed'
    assert all(check['metadata']['device'] == 'cuda' for check in report['checks'] if check['requested_device'] == 'auto'), 'GPU did not run'
    print('All media smoke checks passed.', flush=True)


if __name__ == '__main__':
    main()
