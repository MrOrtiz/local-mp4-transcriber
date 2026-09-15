"""Explicit one-time downloads. Nothing from input folders is read or uploaded."""
import argparse
import hashlib
from pathlib import Path
import shutil
import urllib.request
import zipfile
import subprocess
import ctypes

ROOT = Path(__file__).resolve().parent.parent
CUDA = [
    ('https://developer.download.nvidia.com/compute/cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.8.4.1-archive.zip',
     '57a470112cec7e112c95253dde8b3c7184d795dbd92b0bde77a4cb7f8c94c8aa'),
    ('https://developer.download.nvidia.com/compute/cudnn/redist/cudnn/windows-x86_64/cudnn-windows-x86_64-9.10.2.21_cuda12-archive.zip',
     'c1a4567d822ebda7373fa1f19255dff4942302de741f830160b6c7d1fb31af23'),
]
OCR = ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/eng.traineddata',
       '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2')
MOBI = ('https://github.com/kovidgoyal/calibre/releases/download/v9.14.0/calibre-portable-installer-9.14.0.exe',
        'f784391870cbad568d49b19e13429632ba71dd7f77c427c9e899f5397730dfa8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, expected):
    folder = ROOT / 'tools' / 'downloads'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / url.rsplit('/', 1)[-1]
    if target.exists() and digest(target) == expected:
        return target
    partial = target.with_suffix(target.suffix + '.part')
    print('Downloading ' + url, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as output:
        total = 0
        while chunk := response.read(4 * 1024 * 1024):
            output.write(chunk)
            total += len(chunk)
            if total % (64 * 1024 * 1024) == 0:
                print(f'  {total // (1024 * 1024)} MB', flush=True)
    if digest(partial) != expected:
        raise RuntimeError('Download checksum mismatch: ' + str(partial))
    partial.replace(target)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('resource', choices=['gpu', 'ocr', 'mobi'])
    args = parser.parse_args()
    if args.resource == 'ocr':
        source = download(*OCR)
        folder = ROOT / 'tools' / 'tessdata'
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, folder / 'eng.traineddata')
        print('English OCR data installed. PyMuPDF bundles the Tesseract OCR engine.')
    elif args.resource == 'mobi':
        source = download(*MOBI)
        target = str(ROOT / 'tools')
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(target, buffer, len(buffer)):
            target = buffer.value
        if len(target + '\\Calibre Portable') > 58:
            raise RuntimeError('Calibre Portable requires a shorter installation path. Install Calibre normally '
                               'from https://calibre-ebook.com/download_windows and set ebook-convert in Options.')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        subprocess.run([str(source), target], check=True, timeout=180, startupinfo=startup)
        if not (ROOT / 'tools/Calibre Portable/Calibre/ebook-convert.exe').is_file():
            raise RuntimeError('Calibre installer did not create ebook-convert. Use the standard Calibre installer.')
        print('Calibre 9.14.0 installed locally for MOBI conversion.')
    else:
        folder = ROOT / 'tools' / 'cuda'
        folder.mkdir(parents=True, exist_ok=True)
        for url, sha in CUDA:
            source = download(url, sha)
            with zipfile.ZipFile(source) as archive:
                for entry in archive.infolist():
                    name = Path(entry.filename).name
                    if name.lower().endswith('.dll') or 'license' in name.lower():
                        target = folder / name
                        if 'license' in name.lower():
                            target = folder / (source.stem + '-' + name)
                        with archive.open(entry) as incoming, target.open('wb') as output:
                            shutil.copyfileobj(incoming, output)
        print('Pinned NVIDIA runtime DLLs installed inside tools/cuda. System PATH unchanged.')


if __name__ == '__main__':
    main()
