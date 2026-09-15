import importlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from .media import gpu_memory, cuda_runtime
from .documents import tessdata_path, converter_path


def diagnose(tessdata='', ebook_convert='', ocr_language='eng'):
    report = {'python': sys.version, 'platform': platform.platform(), 'dependencies': {}}
    for package, module in [('faster-whisper', 'faster_whisper'), ('ctranslate2', 'ctranslate2'),
                            ('av', 'av'), ('PyMuPDF', 'pymupdf'), ('python-docx', 'docx'),
                            ('EbookLib', 'ebooklib'), ('beautifulsoup4', 'bs4'), ('tkinter', 'tkinter')]:
        try:
            importlib.import_module(module)
            report['dependencies'][package] = 'available' if package == 'tkinter' else importlib.metadata.version(package)
        except Exception as exc:
            report['dependencies'][package] = f'FAILED: {exc}'
    report['gpus'] = gpu_memory()
    report['cuda_runtime'] = cuda_runtime()[1]
    data = tessdata_path(tessdata)
    report['ocr'] = str(data) if data and all((Path(data) / (lang + '.traineddata')).is_file() for lang in ocr_language.split('+')) else 'Missing requested OCR data. Run install-ocr.cmd for English.'
    try:
        report['mobi'] = converter_path(ebook_convert) or 'Missing Calibre ebook-convert (only MOBI needs this).'
    except RuntimeError as exc:
        report['mobi'] = str(exc)
    report['notes'] = ['GPU detection is not an inference test.', 'Media decode uses bundled PyAV/FFmpeg.',
                       'No material uploads or paid APIs. Model downloads contact Hugging Face unless Offline is selected.']
    return report


if __name__ == '__main__':
    print(json.dumps(diagnose(), indent=2))
