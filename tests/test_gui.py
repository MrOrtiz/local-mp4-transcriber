"""Exercise actual Tk widgets and the spawned Windows worker without manual clicks."""
import json
import time
import tkinter as tk
import pytest
from course_transcriber import gui


def pump(root, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        root.update()
        time.sleep(.02)
        if time.monotonic() > deadline:
            raise AssertionError('GUI worker timed out')


def test_gui_start_progress_restart_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(gui, 'PREFERENCES', tmp_path / 'preferences.json')
    errors = []
    monkeypatch.setattr(gui.messagebox, 'showerror', lambda *args: errors.append(args))
    root = tk.Tk(); root.withdraw()
    app = gui.App(root)
    source = tmp_path / 'source'; source.mkdir()
    (source / 'lesson.txt').write_text('Desktop workflow fixture.', encoding='utf-8')
    output = tmp_path / 'output'
    app.vars['input'].set(str(source)); app.vars['output'].set(str(output))
    try:
        app.start()
        pump(root, lambda: app.process is None)
        assert not errors
        assert '1 completed' in app.status.get()
        assert app.tree.item(app.rows['lesson.txt'])['values'][1] == 'complete'
        assert float(app.progress['value']) == 1
        app.start()
        pump(root, lambda: app.process is None)
        assert '1 skipped' in app.status.get()
        assert json.loads((output / 'state.json').read_text())['status'] == 'finished'
        # The production app keeps one Tcl/Tk interpreter across processing sessions.
        for i in range(100):
            (source / f'{i}.txt').write_text('Cancellation fixture')
        app.start(); app.cancel()
        pump(root, lambda: app.process is None)
        assert 'cancelled' in app.status.get().lower() or 'Stopped' in app.status.get()
    finally:
        if app.process is not None:
            app.process.terminate(); app.process.join()
        root.destroy()
