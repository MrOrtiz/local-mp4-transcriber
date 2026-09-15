"""Package source + launcher, excluding environments, caches, fixtures and user data."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    archive = destination / 'course-transcriber-0.1.0-windows.zip'
    files = []
    for name in ['README.md', 'VALIDATION.md', 'LICENSE', 'requirements.in', 'requirements.lock.txt', 'pytest.ini',
                 'launch.cmd', 'setup.cmd', 'install-gpu.cmd', 'install-ocr.cmd', 'install-mobi.cmd']:
        path = ROOT / name
        if not path.is_file():
            raise RuntimeError('Required release file missing: ' + name)
        files.append(path)
    for folder in ['course_transcriber', 'scripts', 'tests', 'docs']:
        files.extend(path for path in (ROOT / folder).rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix in {'.py', '.ps1', '.md', '.json'})
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(files):
            output.write(path, Path('course-transcriber') / path.relative_to(ROOT))
    with zipfile.ZipFile(archive) as output:
        assert output.testzip() is None
        assert not any('/tools/' in name or '/.venv/' in name or '/tmp/' in name for name in output.namelist())
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(checksum + '  ' + archive.name + '\n', encoding='ascii')
    print(f'{archive}\n{len(files)} files; {archive.stat().st_size:,} bytes\nSHA256 {checksum}')


if __name__ == '__main__':
    main()
