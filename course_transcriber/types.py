from dataclasses import dataclass, field, asdict
from pathlib import Path
import hashlib
import json

MEDIA = {'.mp4', '.mkv', '.mov', '.mp3', '.m4a', '.wav', '.flac', '.avi', '.webm', '.ogg', '.aac', '.wma', '.m4v', '.ts'}
DOCUMENTS = {'.pdf', '.docx', '.txt', '.md', '.markdown', '.epub', '.mobi'}
MARKER = '.course-transcriber.json'


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled('Cancelled; restart to retry unfinished files.')


@dataclass(frozen=True)
class Settings:
    recursive: bool = True
    mode: str = 'quality'
    device: str = 'auto'
    language: str = 'en'
    glossary: str = ''
    srt: bool = False
    combined: bool = True
    offline: bool = False
    ocr_language: str = 'eng'
    tessdata: str = ''
    ebook_convert: str = ''

    def fingerprint(self):
        from . import __version__
        return hashlib.sha256(json.dumps({'version': __version__, **asdict(self)}, sort_keys=True).encode()).hexdigest()


@dataclass
class Result:
    text: str
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)


def file_hash(path: Path, cancel=None):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            if cancel is not None:
                check_cancel(cancel)
            h.update(chunk)
    return h.hexdigest()
