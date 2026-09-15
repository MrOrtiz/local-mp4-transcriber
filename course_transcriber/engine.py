"""Content-addressed completion tracking with immutable output revisions."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
import html
from urllib.parse import quote

from .types import MEDIA, DOCUMENTS, MARKER, Settings, Cancelled, check_cancel, file_hash
from .documents import extract_document
from .media import MediaSession, srt_time


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_index(output, state, current):
    """A readable entry point points only to committed results in the current run."""
    links = []
    for key, entry in current:
        artifacts = ' · '.join(f'<a href="{quote(item["path"], safe="/")}">{html.escape(Path(item["path"]).name)}</a>'
                               for item in entry['artifacts'])
        links.append(f'<tr><td>{html.escape(key)}</td><td>{artifacts}</td></tr>')
    combined = f'<p><a href="{quote(state["combined"], safe="/")}">Open combined course text</a></p>' if state.get('combined') else ''
    page = ('<!doctype html><meta charset="utf-8"><title>Course extraction results</title>'
            '<style>body{font:16px system-ui;margin:40px;max-width:1200px;color:#172536}'
            'table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}'
            'a{color:#125aab}p{line-height:1.6}</style><h1>Course extraction results</h1>'
            f'<p>Status: <strong>{html.escape(state["status"])}</strong> · Run: {html.escape(state["run_id"])}</p>'
            '<p>This index lists committed results from this run. Refresh after processing finishes. '
            'If processing was interrupted, restart the application; a “running” status is not completion.</p>'
            f'{combined}<p><a href="report.json">Run report and failures</a> · <a href="state.json">Completion state</a></p>'
            '<table><tr><th>Source</th><th>Outputs</th></tr>' + ''.join(links) + '</table>'
            '<p>Review warnings alongside the text. No summaries or paraphrases were generated.</p>')
    temporary = output / ('index.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(page, encoding='utf-8')
    os.replace(temporary, output / 'index.html')


def is_link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def discover(root, output, recursive=True, cancel=None):
    root, output = root.resolve(), output.resolve()
    files, excluded = [], []
    def onerror(error):
        excluded.append({'source': str(error.filename), 'reason': str(error)})
    for folder, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        if cancel is not None:
            check_cancel(cancel)
        base = Path(folder)
        if base == output or (base != root and (base / MARKER).exists()):
            dirs[:] = []
            continue
        dirs[:] = [name for name in dirs if not is_link(base / name)
                   and (base / name).resolve() != output
                   and not ((base / name) / MARKER).exists()]
        for name in names:
            path = base / name
            if is_link(path):
                excluded.append({'source': str(path.relative_to(root)), 'reason': 'Symbolic link excluded.'})
            elif path.suffix.lower() in MEDIA | DOCUMENTS:
                files.append(path)
            else:
                excluded.append({'source': str(path.relative_to(root)), 'reason': f'Unsupported format: {path.suffix or "no extension"}'})
        if not recursive:
            dirs[:] = []
    def natural(path):
        return [(0, int(x)) if x.isdigit() else (1, x.casefold())
                for x in re.split(r'(\d+)', str(path.relative_to(root)))]
    return sorted(files, key=natural), excluded


class OutputLock:
    def __init__(self, output):
        self.path = output / '.session.lock'
        self.stream = None

    def __enter__(self):
        try:
            self.stream = self.path.open('a+b')
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b'0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if self.stream is not None:
                self.stream.close()
            raise RuntimeError('Another session is using this output folder.') from exc
        return self

    def __exit__(self, *_):
        self.stream.close()  # OS releases the lock, including after a process crash.


def validate_folders(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir():
        raise ValueError('Input folder does not exist.')
    if root == output or output in root.parents:
        raise ValueError('Output must differ from input and cannot be an ancestor of input.')
    if (root / MARKER).exists() or any((p / MARKER).exists() for p in root.parents):
        raise ValueError('Input is inside an application output folder.')
    if any((p / MARKER).exists() for p in output.parents):
        raise ValueError('Choose the existing output root, not a folder inside it.')
    marker = output / MARKER
    if marker.exists():
        saved = json.loads(marker.read_text(encoding='utf-8'))
        if saved.get('app') != 'course-transcriber' or saved.get('input') != str(root):
            raise ValueError('Output folder belongs to a different input course. Choose an empty folder.')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty output folder to protect existing files.')
    return root, output


def safe_child(output, relative):
    path = output / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(output.resolve()) or resolved == output.resolve():
        raise ValueError('Unsafe output path in completion data.')
    for ancestor in [path, *path.parents]:
        if ancestor == output:
            break
        if is_link(ancestor):
            raise ValueError('Links/junctions are not allowed in generated output paths.')
    return path


def valid_entry(output, entry, source_hash, settings_hash):
    if entry.get('status') != 'complete' or entry.get('source_hash') != source_hash or entry.get('settings_hash') != settings_hash:
        return False
    try:
        artifacts = entry['artifacts']
        return bool(artifacts) and all(file_hash(safe_child(output, item['path'])) == item['sha256'] for item in artifacts)
    except (OSError, ValueError, KeyError):
        return False


def item_directory(relative):
    # Extension remains part of identity: lesson.mp4 and lesson.pdf never collide.
    import hashlib
    digest = hashlib.sha256(relative.as_posix().encode('utf-8')).hexdigest()[:16]
    label = relative.name[:70]
    return Path('lessons') / relative.parent / f'{label}--{digest}'


LEGACY_ROLES = {'text.txt': 'text', 'timestamped.txt': 'timestamped', 'subtitles.srt': 'subtitles',
                'metadata.json': 'metadata', 'warnings.txt': 'warnings'}


def artifact_role(item):
    return item.get('role') or LEGACY_ROLES.get(Path(item['path']).name)


def output_names(relative):
    stem = relative.stem
    return {'text': f'{stem}.txt', 'timestamped': f'{stem}.timestamped.txt',
            'subtitles': f'{stem}.srt', 'metadata': f'{stem}.metadata.json',
            'warnings': f'{stem}.warnings.txt'}


def publish_artifacts(output, relative, contents, cancel, expected=None):
    revision = item_directory(relative) / ('rev-' + uuid.uuid4().hex[:12])
    destination = safe_child(output, revision.with_name(revision.name + '.partial'))
    destination.mkdir(parents=True, exist_ok=False)
    artifacts = []
    names = output_names(relative)
    for role, content in contents.items():
        check_cancel(cancel)
        name = names[role]
        path = destination / name
        with path.open('xb') as stream:
            if isinstance(content, Path):
                with content.open('rb') as source:
                    while chunk := source.read(1024 * 1024):
                        check_cancel(cancel)
                        stream.write(chunk)
            else:
                stream.write(content.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        digest = file_hash(path)
        if expected is not None and digest != expected[role]:
            raise RuntimeError('Existing output changed while updating its filename; retry the session.')
        artifacts.append({'role': role, 'path': (revision / name).as_posix(), 'sha256': digest})
    check_cancel(cancel)
    destination.rename(safe_child(output, revision))
    return artifacts


def update_output_names(output, relative, entry, cancel):
    names = output_names(relative)
    if all(item.get('role') in names and Path(item['path']).name == names[item['role']]
           for item in entry['artifacts']):
        return entry
    contents = {artifact_role(item): safe_child(output, item['path']) for item in entry['artifacts']}
    expected = {artifact_role(item): item['sha256'] for item in entry['artifacts']}
    if None in contents or 'text' not in contents:
        raise ValueError('Unrecognized output artifacts in completion data.')
    artifacts = publish_artifacts(output, relative, contents, cancel, expected)
    return {**entry, 'artifacts': artifacts}


def write_result(output, relative, result, settings, cancel):
    metadata = {'original_filename': relative.name, 'relative_source': relative.as_posix(),
                'relative_course_folder': relative.parent.as_posix(), **result.metadata}
    header = '\n'.join(f'{key}: {value}' for key, value in metadata.items())
    contents = {'text': header + '\n\n--- Source content ---\n\n' + result.text + '\n',
                'metadata': json.dumps(metadata, ensure_ascii=False, indent=2),
                'warnings': '\n'.join(dict.fromkeys(result.warnings)) or 'No heuristic problems flagged; this does not guarantee accuracy.'}
    if relative.suffix.lower() in MEDIA:
        contents['timestamped'] = header + '\n\n' + '\n'.join(
            f"[{srt_time(s['start'])} --> {srt_time(s['end'])}] {s['text']}" for s in result.segments)
        if settings.srt:
            contents['subtitles'] = '\n\n'.join(
                f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}"
                for i, s in enumerate(result.segments, 1)) + '\n'
    return publish_artifacts(output, relative, contents, cancel)


def run_session(root, output, settings, cancel, emit, document_processor=extract_document, media_factory=MediaSession):
    root, output = validate_folders(root, output)
    output.mkdir(parents=True, exist_ok=True)
    with OutputLock(output):
        # First ownership marker is written under the session lock.
        if not (output / MARKER).exists():
            atomic_json(output / MARKER, {'app': 'course-transcriber', 'input': str(root), 'created': now()})
        state_path = output / 'state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'files': {}}
        run_id = uuid.uuid4().hex[:12]
        state.update(status='running', started=now(), run_id=run_id, settings=asdict(settings), combined=None)
        atomic_json(state_path, state)
        atomic_json(output / 'report.json', {'run_id': run_id, 'status': 'running', 'combined': None})
        write_index(output, state, [])
        progress = lambda message: emit({'type': 'detail', 'message': message})
        counts = {'completed': 0, 'skipped': 0, 'failed': 0, 'unsupported': 0}
        current = []
        files, excluded = [], []
        try:
            files, excluded = discover(root, output, settings.recursive, cancel)
            counts['unsupported'] = len(excluded)
            emit({'type': 'discovered', 'total': len(files), 'excluded': len(excluded)})
            for item in excluded:
                emit({'type': 'unsupported', **item})
            media = media_factory(settings, progress)
            settings_hash = settings.fingerprint()
            for index, path in enumerate(files, 1):
                check_cancel(cancel)
                relative = path.relative_to(root)
                key = relative.as_posix()
                emit({'type': 'file', 'source': key, 'index': index, 'total': len(files)})
                old = state['files'].get(key, {})
                try:
                    digest = file_hash(path, cancel)
                    if valid_entry(output, old, digest, settings_hash):
                        updated = update_output_names(output, relative, old, cancel)
                        if updated is not old:
                            state['files'][key] = updated
                            atomic_json(state_path, state)
                            progress(f'{key}: updated output filenames; transcription/extraction reused.')
                        old = updated
                        counts['skipped'] += 1
                        current.append((key, old))
                        emit({'type': 'skipped', 'source': key})
                        continue
                    entry = {'status': 'running', 'source_hash': digest, 'settings_hash': settings_hash, 'started': now()}
                    state['files'][key] = entry
                    atomic_json(state_path, state)
                    result = media.transcribe(path, cancel) if path.suffix.lower() in MEDIA else document_processor(path, settings, cancel, progress)
                    if not result.text.strip():
                        result.warnings.append('No source text recovered; the file may be empty or require manual review.')
                    check_cancel(cancel)
                    if file_hash(path, cancel) != digest:
                        raise RuntimeError('Source changed during processing; retry after the file stops changing.')
                    artifacts = write_result(output, relative, result, settings, cancel)
                    check_cancel(cancel)
                    entry.update(status='complete', finished=now(), artifacts=artifacts, warning_count=len(set(result.warnings)))
                    atomic_json(state_path, state)
                    counts['completed'] += 1
                    current.append((key, entry))
                    emit({'type': 'complete', 'source': key, 'warnings': entry['warning_count']})
                except Cancelled:
                    if key in state['files'] and state['files'][key].get('status') == 'running':
                        state['files'][key]['status'] = 'cancelled'
                    raise
                except Exception as exc:
                    state['files'][key] = {'status': 'failed', 'error': str(exc), 'finished': now()}
                    atomic_json(state_path, state)
                    counts['failed'] += 1
                    emit({'type': 'failed', 'source': key, 'message': str(exc)})
            check_cancel(cancel)
            if settings.combined:
                combined_relative = Path('runs') / run_id / 'combined.txt'
                combined = safe_child(output, combined_relative)
                combined.parent.mkdir(parents=True, exist_ok=False)
                partial_combined = combined.with_suffix('.txt.partial')
                with partial_combined.open('x', encoding='utf-8', newline='\n') as stream:
                    stream.write(f'Course: {root.name}\nRun: {run_id}\nIncluded lessons: {len(current)}/{len(files)}\n'
                                 f'Failures: {counts["failed"]}; unsupported/excluded: {len(excluded)}\n'
                                 'Only successful files from this run are included. See report.json for omissions.\n\n')
                    for key, entry in current:
                        check_cancel(cancel)
                        text = next(item for item in entry['artifacts'] if artifact_role(item) == 'text')
                        stream.write(f'\n{"=" * 72}\nLESSON: {key}\nOUTPUT: {text["path"]}\n{"=" * 72}\n\n')
                        with safe_child(output, text['path']).open(encoding='utf-8') as lesson:
                            while chunk := lesson.read(1024 * 1024):
                                check_cancel(cancel)
                                stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                check_cancel(cancel)
                partial_combined.rename(combined)
                state['combined'] = combined_relative.as_posix()
            state['status'] = 'finished_with_errors' if counts['failed'] else 'finished'
        except Cancelled:
            state['status'] = 'cancelled'
        except Exception:
            state['status'] = 'failed'
            raise
        finally:
            state['finished'] = now()
            state['counts'] = counts
            atomic_json(state_path, state)
            report = {'run_id': run_id, 'status': state['status'], 'counts': counts, 'excluded': excluded,
                      'files': {path.relative_to(root).as_posix(): state['files'].get(path.relative_to(root).as_posix()) for path in files},
                      'combined': state['combined']}
            atomic_json(output / 'report.json', report)
            write_index(output, state, current)
            emit({'type': 'done', 'status': state['status'], **counts, 'combined': state.get('combined')})
        return state


def worker(root, output, settings_dict, cancel, queue):
    try:
        run_session(root, output, Settings(**settings_dict), cancel, queue.put)
    except Exception as exc:
        queue.put({'type': 'fatal', 'message': str(exc)})
