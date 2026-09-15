from dataclasses import replace
import json
from pathlib import Path
import threading
import pytest

from course_transcriber.engine import discover, run_session, validate_folders, OutputLock, item_directory
from course_transcriber.types import Settings, Result, MARKER, file_hash, Cancelled


@pytest.fixture
def folders(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    return root, tmp_path / 'output'


def run(root, output, settings=Settings(), **kwargs):
    return run_session(root, output, settings, kwargs.pop('cancel', threading.Event()),
                       kwargs.pop('emit', lambda _: None), **kwargs)


def text_path(output, entry):
    return output / next(a['path'] for a in entry['artifacts'] if a.get('role') == 'text')


def test_discovery_recursion_exclusion_and_natural_sort(folders):
    root, _ = folders
    output = root / 'generated'
    output.mkdir()
    (output / 'never.txt').write_text('generated')
    nested = root / 'module'
    nested.mkdir()
    for name in ['10.MP4', '2.pdf', '1.txt', '11.ts', '12.TS', 'unsupported.xyz']:
        (root / name).touch()
    (nested / '3.docx').touch()
    older = root / 'older-output'
    older.mkdir()
    (older / MARKER).write_text('{}')
    (older / 'skip.txt').touch()
    paths, unsupported = discover(root, output)
    assert [p.name for p in paths] == ['1.txt', '2.pdf', '10.MP4', '11.ts', '12.TS', '3.docx']
    assert len(unsupported) == 1
    assert len(discover(root, output, False)[0]) == 5


def test_collisions_originals_and_output_exclusion(folders):
    root, _ = folders
    output = root / 'exports'
    (root / 'lesson.txt').write_text('Original text')
    (root / 'lesson.md').write_text('# Original markdown')
    nested = root / 'unit'; nested.mkdir()
    (nested / 'lesson.txt').write_text('Nested content')
    before = {p: file_hash(p) for p in root.rglob('*') if p.is_file()}
    state = run(root, output)
    assert state['counts']['completed'] == 3
    artifacts = [a['path'] for e in state['files'].values() for a in e['artifacts']]
    assert len(artifacts) == len(set(artifacts))
    assert all(file_hash(p) == digest for p, digest in before.items())
    assert run(root, output)['counts']['skipped'] == 3
    assert 'unit' in str(item_directory(Path('unit/lesson.txt')))


def test_hash_settings_and_output_tamper_reprocess(folders):
    root, output = folders
    path = root / 'lesson.txt'; path.write_text('One')
    first = run(root, output)
    artifact = text_path(output, first['files']['lesson.txt'])
    artifact.write_text('tampered')
    second = run(root, output)
    assert second['counts']['completed'] == 1
    assert artifact.read_text() == 'tampered'  # Immutable previous revisions.
    path.write_text('Two')
    third = run(root, output)
    assert third['counts']['completed'] == 1
    assert 'Two' in text_path(output, third['files']['lesson.txt']).read_text()
    assert run(root, output, replace(Settings(), srt=True))['counts']['completed'] == 1


def test_failure_recovery_and_combined_omissions(folders):
    root, output = folders
    (root / '1.txt').write_text('Good')
    (root / '2.txt').write_text('Retry me')
    def failing(path, *args):
        if path.name == '2.txt':
            raise RuntimeError('fixture error')
        return Result('Good')
    state = run(root, output, document_processor=failing)
    assert state['status'] == 'finished_with_errors'
    assert state['counts']['completed'] == state['counts']['failed'] == 1
    combined = (output / state['combined']).read_text()
    assert 'LESSON: 1.txt' in combined and 'LESSON: 2.txt' not in combined
    recovered = run(root, output)
    assert recovered['counts']['skipped'] == recovered['counts']['completed'] == 1


def test_cancel_and_safe_restart(folders):
    root, output = folders
    (root / '1.txt').write_text('One')
    (root / '2.txt').write_text('Two')
    cancel = threading.Event()
    def emit(event):
        if event['type'] == 'complete':
            cancel.set()
    state = run(root, output, cancel=cancel, emit=emit)
    assert state['status'] == 'cancelled'
    assert state['combined'] is None
    restarted = run(root, output)
    assert restarted['counts']['skipped'] == restarted['counts']['completed'] == 1


def test_incomplete_state_never_skipped(folders):
    root, output = folders
    (root / '1.txt').write_text('One')
    state = run(root, output)
    state['files']['1.txt']['status'] = 'running'
    (output / 'state.json').write_text(json.dumps(state))
    assert run(root, output)['counts']['completed'] == 1


def test_changed_source_during_processing_fails(folders):
    root, output = folders
    (root / '1.txt').write_text('One')
    def mutate(path, *_):
        path.write_text('Changed by simulated external editor')
        return Result('stale')
    state = run(root, output, document_processor=mutate)
    assert state['files']['1.txt']['status'] == 'failed'
    assert 'changed during' in state['files']['1.txt']['error']


def test_unsafe_folder_choices(folders):
    root, output = folders
    with pytest.raises(ValueError):
        validate_folders(root, root)
    with pytest.raises(ValueError):
        validate_folders(root, root.parent)
    output.mkdir(); (output / 'existing.txt').write_text('Do not touch')
    with pytest.raises(ValueError):
        run(root, output)
    assert (output / 'existing.txt').read_text() == 'Do not touch'


def test_other_course_output_rejected(folders):
    root, output = folders
    run(root, output)
    other = root.parent / 'other'; other.mkdir()
    with pytest.raises(ValueError):
        run(other, output)
    with pytest.raises(ValueError):
        validate_folders(output, other)


def test_concurrent_output_lock(folders):
    _, output = folders
    output.mkdir()
    with OutputLock(output):
        with pytest.raises(RuntimeError, match='Another session'):
            with OutputLock(output):
                pass


def test_removed_source_not_in_new_combined(folders):
    root, output = folders
    (root / 'old.txt').write_text('Old lesson')
    run(root, output)
    (root / 'old.txt').unlink()
    state = run(root, output)
    assert 'LESSON: old.txt' not in (output / state['combined']).read_text()


def test_media_outputs_and_model_session_reuse(folders):
    root, output = folders
    (root / 'same.mp4').touch(); (root / 'same.mkv').touch()
    (root / 'same.ts').touch(); (root / 'uppercase.TS').touch()
    instances = []
    class FakeMedia:
        def __init__(self, *_):
            instances.append(self)
        def transcribe(self, path, cancel):
            return Result('Hello world.', {'duration_seconds': 2, 'language': 'en'},
                          segments=[{'start': 0, 'end': 2, 'text': 'Hello world.'}])
    state = run(root, output, replace(Settings(), srt=True), media_factory=FakeMedia)
    assert len(instances) == 1
    assert state['counts']['completed'] == 4
    for entry in state['files'].values():
        assert len(entry['artifacts']) == 5
        subtitle = next(a for a in entry['artifacts'] if a['path'].endswith('.srt'))
        assert '00:00:00,000 --> 00:00:02,000' in (output / subtitle['path']).read_text()


def test_path_escape_in_manifest_never_read_or_reused(folders):
    root, output = folders
    (root / 'one.txt').write_text('One')
    state = run(root, output)
    state['files']['one.txt']['artifacts'][0]['path'] = '../source/one.txt'
    (output / 'state.json').write_text(json.dumps(state))
    assert run(root, output)['counts']['completed'] == 1


def test_interrupted_writes_are_partial_and_retry(folders, monkeypatch):
    from course_transcriber import engine
    root, output = folders
    (root / 'lesson.txt').write_text('Preserved original')
    original_write = engine.write_result
    def interrupted(output, relative, result, settings, cancel):
        # Cancel after the first artifact was flushed, while later artifacts remain unwritten.
        original_hash = engine.file_hash
        def cancel_after_hash(path, *args):
            value = original_hash(path, *args)
            if path.name == 'lesson.txt':
                cancel.set()
            return value
        with monkeypatch.context() as context:
            context.setattr(engine, 'file_hash', cancel_after_hash)
            return original_write(output, relative, result, settings, cancel)
    with monkeypatch.context() as context:
        context.setattr(engine, 'write_result', interrupted)
        state = run(root, output)
    assert state['status'] == 'cancelled'
    assert state['files']['lesson.txt']['status'] == 'cancelled'
    assert list(output.rglob('*.partial'))
    assert run(root, output)['counts']['completed'] == 1
    assert (root / 'lesson.txt').read_text() == 'Preserved original'


def test_windows_junction_not_followed(folders):
    import os
    if os.name != 'nt':
        pytest.skip('Windows junction test')
    import _winapi
    root, output = folders
    target = root.parent / 'elsewhere'; target.mkdir()
    (target / 'private.txt').write_text('Outside input tree')
    junction = root / 'link'
    _winapi.CreateJunction(str(target), str(junction))
    try:
        assert discover(root, output)[0] == []
    finally:
        junction.rmdir()  # Removes only the junction, never its target contents.


def test_index_escapes_source_names(folders):
    root, output = folders
    (root / 'A&B.txt').write_text('Literal source')
    state = run(root, output)
    index = (output / 'index.html').read_text(encoding='utf-8')
    assert 'A&amp;B.txt' in index
    assert 'A%26B.txt' in index
    assert state['combined'] in index


@pytest.mark.parametrize('name', ['Lesson 1.md', 'warnings.txt', 'timestamped.md', 'Café.part.2.txt'])
def test_source_named_text_and_sidecars(folders, name):
    root, output = folders
    source = root / name
    source.write_text('Exact source content', encoding='utf-8')
    state = run(root, output)
    entry = state['files'][name]
    assert text_path(output, entry).name == source.stem + '.txt'
    assert 'Exact source content' in text_path(output, entry).read_text(encoding='utf-8')
    assert len({a['path'].casefold() for a in entry['artifacts']}) == 3
    assert source.read_text(encoding='utf-8') == 'Exact source content'


def make_legacy(output, state):
    from course_transcriber.engine import LEGACY_ROLES
    names = {role: name for name, role in LEGACY_ROLES.items()}
    for entry in state['files'].values():
        for artifact in entry['artifacts']:
            path = output / artifact['path']
            legacy = path.with_name(names[artifact.pop('role')])
            if path != legacy:
                path.rename(legacy)
            artifact['path'] = legacy.relative_to(output).as_posix()
    (output / 'state.json').write_text(json.dumps(state), encoding='utf-8')


def test_legacy_outputs_renamed_without_reprocessing(folders):
    root, output = folders
    (root / 'Lesson One.md').write_text('Existing lesson content')
    state = run(root, output)
    make_legacy(output, state)
    legacy_paths = {output / a['path']: a['sha256'] for a in state['files']['Lesson One.md']['artifacts']}
    def never_process(*_):
        raise AssertionError('Existing content must not be extracted again')
    updated = run(root, output, document_processor=never_process)
    assert updated['counts']['skipped'] == 1 and updated['counts']['failed'] == 0
    path = text_path(output, updated['files']['Lesson One.md'])
    assert path.name == 'Lesson One.txt'
    assert all(file_hash(old) == digest for old, digest in legacy_paths.items())
    assert 'Existing lesson content' in (output / updated['combined']).read_text()
    assert 'Lesson%20One.txt' in (output / 'index.html').read_text(encoding='utf-8')
    assert run(root, output, document_processor=never_process)['files']['Lesson One.md']['artifacts'] == updated['files']['Lesson One.md']['artifacts']


def test_legacy_media_names_reused(folders):
    root, output = folders
    (root / 'Lesson 2.mp4').touch()
    class Media:
        def __init__(self, *_):
            pass
        def transcribe(self, *_):
            return Result('Saved speech', segments=[{'start': 0, 'end': 1, 'text': 'Saved speech'}])
    settings = replace(Settings(), srt=True)
    state = run(root, output, settings, media_factory=Media)
    make_legacy(output, state)
    class NeverMedia(Media):
        def transcribe(self, *_):
            raise AssertionError('Must reuse the existing transcript')
    state = run(root, output, settings, media_factory=NeverMedia)
    assert state['counts']['skipped'] == 1
    names = {Path(a['path']).name for a in state['files']['Lesson 2.mp4']['artifacts']}
    assert names == {'Lesson 2.txt', 'Lesson 2.timestamped.txt', 'Lesson 2.srt', 'Lesson 2.metadata.json', 'Lesson 2.warnings.txt'}
