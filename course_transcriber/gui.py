from dataclasses import asdict
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .engine import worker, validate_folders, atomic_json
from .types import Settings

PREFERENCES = Path(__file__).resolve().parent.parent / '.user-settings.json'


class App:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.context = mp.get_context('spawn')
        self.events = None
        self.cancel_event = None
        self.cancel_time = None
        self.final_seen = False
        self.closing = False
        self.rows = {}
        root.title('Course Transcriber — Local text extraction')
        root.geometry('980x760')
        root.minsize(800, 620)
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Title.TLabel', font=('Segoe UI', 19, 'bold'))
        style.configure('TLabel', font=('Segoe UI', 10))
        self.vars = {'input': tk.StringVar(), 'output': tk.StringVar(), 'glossary_file': tk.StringVar()}
        for key, value in asdict(Settings()).items():
            if key != 'glossary':
                self.vars[key] = tk.BooleanVar(value=value) if isinstance(value, bool) else tk.StringVar(value=value)
        try:
            for key, value in json.loads(PREFERENCES.read_text(encoding='utf-8')).items():
                if key in self.vars:
                    self.vars[key].set(value)
        except (OSError, ValueError):
            pass
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Course Transcriber', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Turn course folders into readable text. Processing stays on this computer.').pack(anchor='w', pady=(3, 15))
        folders = ttk.Frame(outer)
        folders.pack(fill='x')
        folders.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate([('input', 'Course folder'), ('output', 'Output folder')]):
            ttk.Label(folders, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=5)
            ttk.Entry(folders, textvariable=self.vars[key]).grid(row=row, column=1, sticky='ew')
            ttk.Button(folders, text='Browse…', command=lambda k=key: self.browse(k)).grid(row=row, column=2, padx=(8, 0))
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=12)
        ttk.Label(controls, text='Mode').pack(side='left')
        ttk.Combobox(controls, textvariable=self.vars['mode'], values=['quality', 'fast'], state='readonly', width=10).pack(side='left', padx=8)
        ttk.Label(controls, text='Device').pack(side='left', padx=(15, 0))
        ttk.Combobox(controls, textvariable=self.vars['device'], values=['auto', 'cpu'], state='readonly', width=8).pack(side='left', padx=8)
        ttk.Button(controls, text='Options…', command=self.options).pack(side='right')
        flags = ttk.Frame(outer)
        flags.pack(fill='x')
        for key, label in [('recursive', 'Include subfolders'), ('combined', 'Combined course text'), ('srt', 'SRT subtitles'), ('offline', 'Offline / cached models only')]:
            ttk.Checkbutton(flags, text=label, variable=self.vars[key]).pack(side='left', padx=(0, 15))
        ttk.Label(outer, text='Quality: large-v3  •  Fast: large-v3-turbo  •  First use downloads the selected model.').pack(anchor='w', pady=(8, 12))
        buttons = ttk.Frame(outer)
        buttons.pack(fill='x')
        self.start_button = ttk.Button(buttons, text='Start processing', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(buttons, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        ttk.Button(buttons, text='Open output', command=self.open_output).pack(side='left')
        self.diag_button = ttk.Button(buttons, text='Dependency diagnostics', command=self.diagnostics)
        self.diag_button.pack(side='right')
        self.status = tk.StringVar(value='Ready. Choose an empty output folder, or one previously created for this course.')
        ttk.Label(outer, textvariable=self.status, wraplength=900).pack(anchor='w', pady=(14, 6))
        self.progress = ttk.Progressbar(outer, mode='determinate')
        self.progress.pack(fill='x', pady=(0, 10))
        table = ttk.Frame(outer)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('source', 'status', 'detail'), show='headings', height=9)
        for key, label, width in [('source', 'Source', 370), ('status', 'Status', 110), ('detail', 'Details', 350)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=80)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        ttk.Label(outer, text='Session log — extraction warnings are also saved beside each result.').pack(anchor='w', pady=(10, 4))
        self.log = tk.Text(outer, height=7, wrap='word', state='disabled', font=('Consolas', 9))
        self.log.pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(150, self.poll)

    def browse(self, key):
        value = filedialog.askdirectory(title='Choose ' + key + ' folder', mustexist=key == 'input')
        if value:
            self.vars[key].set(value)

    def options(self):
        window = tk.Toplevel(self.root)
        window.title('Extraction options')
        window.transient(self.root)
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate([('language', 'Speech language (en or auto)'),
                                           ('glossary_file', 'Optional glossary TXT file'),
                                           ('ocr_language', 'OCR languages (eng, eng+spa…)'),
                                           ('tessdata', 'Tesseract tessdata folder'),
                                           ('ebook_convert', 'Calibre ebook-convert executable')]):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=6, padx=(0, 10))
            ttk.Entry(frame, textvariable=self.vars[key], width=55).grid(row=row, column=1, sticky='ew')
            if key in {'glossary_file', 'tessdata', 'ebook_convert'}:
                def choose(k=key):
                    value = filedialog.askdirectory() if k == 'tessdata' else filedialog.askopenfilename()
                    if value:
                        self.vars[k].set(value)
                ttk.Button(frame, text='Browse…', command=choose).grid(row=row, column=2, padx=6)
        ttk.Label(frame, text='Use a short glossary of names and technical terms (up to 1,000 characters).\n'
                  'Changes apply to the next session. OCR and document layout require review.').grid(row=5, column=0, columnspan=3, sticky='w', pady=14)
        ttk.Button(frame, text='Done', command=window.destroy).grid(row=6, column=2)

    def append_log(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 1500:
            self.log.delete('1.0', '200.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self):
        if self.process is not None:
            return
        try:
            if not self.vars['input'].get().strip() or not self.vars['output'].get().strip():
                raise ValueError('Choose both input and output folders.')
            source, destination = validate_folders(self.vars['input'].get(), self.vars['output'].get())
            values = {key: variable.get() for key, variable in self.vars.items() if key in Settings.__dataclass_fields__}
            glossary = self.vars['glossary_file'].get().strip()
            values['glossary'] = Path(glossary).read_text(encoding='utf-8-sig') if glossary else ''
            if len(values['glossary']) > 1000:
                raise ValueError('Glossary is too long. Use up to 1,000 characters of key terms.')
            if not values['language'] or not values['ocr_language']:
                raise ValueError('Speech and OCR language fields cannot be empty.')
            settings = Settings(**values)
            atomic_json(PREFERENCES, {key: variable.get() for key, variable in self.vars.items()})
        except Exception as exc:
            messagebox.showerror('Cannot start', str(exc))
            return
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.events = self.context.Queue()
        self.cancel_event = self.context.Event()
        self.final_seen, self.cancel_time = False, None
        self.process = self.context.Process(target=worker, args=(str(source), str(destination), asdict(settings), self.cancel_event, self.events))
        self.process.start()
        self.start_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.status.set('Discovering course materials…')
        self.progress.configure(value=0)
        self.append_log(f'Started: {source}')

    def cancel(self):
        if self.process is not None and self.cancel_time is None:
            self.cancel_event.set()
            self.cancel_time = time.monotonic()
            self.status.set('Cancelling… finishing the current operation; forced stop after 10 seconds if needed.')
            self.cancel_button.configure(state='disabled')

    def handle_event(self, event):
        kind = event['type']
        if kind == 'detail':
            if self.cancel_time is None:
                self.status.set(event['message'])
            self.append_log(event['message'])
        elif kind == 'discovered':
            self.progress.configure(maximum=max(1, event['total']))
            self.append_log(f"Found {event['total']} supported files; {event['excluded']} excluded/unsupported.")
        elif kind in {'file', 'complete', 'skipped', 'failed', 'unsupported'}:
            source = event['source']
            detail = event.get('message', event.get('reason', ''))
            if kind == 'complete':
                detail = f"{event['warnings']} review notes; see the .warnings.txt output"
            status = 'processing' if kind == 'file' else kind
            if kind == 'file' and self.cancel_time is None:
                self.status.set(f"Processing {event['index']}/{event['total']}: {source}")
            if source not in self.rows:
                self.rows[source] = self.tree.insert('', 'end', values=(source, status, detail))
            else:
                self.tree.item(self.rows[source], values=(source, status, detail))
            self.tree.see(self.rows[source])
            if kind in {'complete', 'skipped', 'failed'}:
                self.progress.configure(value=float(self.progress['value']) + 1)
                self.append_log(f'{status}: {source} {detail}')
        elif kind == 'done':
            self.final_seen = True
            text = f"{event['status']}: {event['completed']} completed, {event['skipped']} skipped, {event['failed']} failed, {event['unsupported']} excluded."
            self.status.set(text)
            self.append_log(text)
            if event.get('combined'):
                self.append_log('Combined text: ' + event['combined'])
        elif kind == 'fatal':
            self.final_seen = True
            self.status.set('Failed: ' + event['message'])
            self.append_log('ERROR: ' + event['message'])

    def poll(self):
        if self.process is not None:
            try:
                for _ in range(150):
                    self.handle_event(self.events.get_nowait())
            except queue.Empty:
                pass
            if self.cancel_time and time.monotonic() - self.cancel_time > 10 and self.process.is_alive():
                self.process.terminate()
            if not self.process.is_alive():
                self.process.join()
                # A worker may exit immediately after enqueueing its final event.
                try:
                    while True:
                        self.handle_event(self.events.get_nowait())
                except queue.Empty:
                    pass
                if not self.final_seen:
                    self.status.set('Stopped. Unfinished files will retry on restart. See log for details.')
                    self.append_log(f'Worker exited ({self.process.exitcode}). A native dependency may have failed; run diagnostics or select CPU.')
                self.process.close()
                self.process = None
                self.events.close()
                self.start_button.configure(state='normal')
                self.cancel_button.configure(state='disabled')
                if self.closing:
                    self.root.destroy()
                    return
        self.root.after(150, self.poll)

    def diagnostics(self):
        self.diag_button.configure(state='disabled')
        results = queue.Queue()
        command = [sys.executable, '-m', 'course_transcriber', '--diagnostics',
                   '--tessdata', self.vars['tessdata'].get(), '--ebook-convert', self.vars['ebook_convert'].get(),
                   '--ocr-language', self.vars['ocr_language'].get()]
        def run():
            try:
                proc = subprocess.run(command, capture_output=True,
                                      text=True, encoding='utf-8', errors='replace', timeout=45,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                results.put(proc.stdout + proc.stderr)
            except Exception as exc:
                results.put(str(exc))
        def display():
            try:
                text = results.get_nowait()
            except queue.Empty:
                self.root.after(150, display)
                return
            self.diag_button.configure(state='normal')
            window = tk.Toplevel(self.root)
            window.title('Dependency diagnostics')
            box = tk.Text(window, width=105, height=30, wrap='word')
            box.pack(fill='both', expand=True)
            box.insert('1.0', text)
            box.configure(state='disabled')
        threading.Thread(target=run, daemon=True).start()
        self.root.after(150, display)

    def open_output(self):
        path = Path(self.vars['output'].get())
        if path.is_dir() and self.vars['output'].get():
            os.startfile(path)

    def close(self):
        if self.process is not None:
            self.closing = True
            self.cancel()
        else:
            self.root.destroy()


def main():
    mp.freeze_support()
    root = tk.Tk()
    App(root)
    root.mainloop()
