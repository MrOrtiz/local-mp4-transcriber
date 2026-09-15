import ctypes
import gc
import os
from pathlib import Path
import subprocess

from .types import Result, check_cancel, Cancelled

_dll_handles = []
MODEL_REVISIONS = {
    'large-v3': 'edaa852ec7e145841d8ffdb056a99866b5f0a478',
    'large-v3-turbo': '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf',
}
MODEL_CACHE = Path(__file__).resolve().parent.parent / 'tools' / 'models'


def model_path(name, offline=False):
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    from faster_whisper.utils import download_model
    return download_model(name, revision=MODEL_REVISIONS[name], cache_dir=str(MODEL_CACHE),
                          local_files_only=offline, use_auth_token=False)


def prepare_dlls():
    """Optional local CUDA runtime, plus DLL directories explicitly on PATH."""
    if os.name != 'nt':
        return
    local = Path(__file__).resolve().parent.parent / 'tools' / 'cuda'
    paths = [local] + [Path(p) for p in os.environ.get('PATH', '').split(os.pathsep) if p]
    if local.is_dir():
        os.environ['PATH'] = str(local) + os.pathsep + os.environ.get('PATH', '')
    for path in paths:
        if path.is_dir():
            try:
                _dll_handles.append(os.add_dll_directory(str(path)))
            except OSError:
                pass


def gpu_memory():
    try:
        process = subprocess.run(['nvidia-smi', '--query-gpu=index,name,memory.total,memory.free',
                                  '--format=csv,noheader,nounits'], capture_output=True, text=True,
                                 timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        cards = []
        for line in process.stdout.splitlines():
            idx, name, total, free = [v.strip() for v in line.split(',')]
            cards.append({'index': int(idx), 'name': name, 'total_mb': int(total), 'free_mb': int(free)})
        return sorted(cards, key=lambda card: card['free_mb'], reverse=True)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def batch_for_memory(free_mb):
    # Conservative heuristic, not a promise that another GPU process won't consume memory.
    return 8 if free_mb >= 10000 else 4 if free_mb >= 7000 else 2 if free_mb >= 5000 else 1


def cuda_runtime():
    prepare_dlls()
    if os.name != 'nt':
        return True, 'CUDA runtime checked when loading model.'
    try:
        for name in ['cublas64_12.dll', 'cudnn64_9.dll']:
            ctypes.WinDLL(name)
        return True, 'CUDA 12 cuBLAS and cuDNN 9 found.'
    except OSError as exc:
        return False, f'Missing/unloadable CUDA 12 cuBLAS or cuDNN 9: {exc}. CPU fallback is available.'


def srt_time(seconds):
    # Adapted from MrOrtiz/local-mp4-transcriber (MIT).
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{millis:03}'


def readable_text(rows):
    """Join recognition segments without changing words; paragraph breaks follow pauses."""
    paragraphs, words, length, previous = [], [], 0, None
    for row in rows:
        text = row['text'].strip()
        if not text:
            continue
        boundary = previous is not None and (row['start'] - previous['end'] >= 2
                   or (length >= 900 and previous['text'].rstrip().endswith(('.', '?', '!'))))
        if words and boundary:
            paragraphs.append(' '.join(words))
            words, length = [], 0
        words.append(text)
        length += len(text) + 1
        previous = row
    if words:
        paragraphs.append(' '.join(words))
    return '\n\n'.join(paragraphs)


class MediaSession:
    def __init__(self, settings, progress):
        self.settings, self.progress = settings, progress
        self.model = self.pipeline = None
        self.device, self.compute, self.batch, self.index = 'cpu', 'int8', 1, 0
        self.notices = []

    def load(self, force_cpu=False):
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
        from faster_whisper import WhisperModel, BatchedInferencePipeline
        if self.model is not None and not force_cpu:
            return
        if force_cpu:
            self.pipeline = self.model = None
            gc.collect()
        cards = gpu_memory() if not force_cpu and self.settings.device != 'cpu' else []
        ok, detail = cuda_runtime() if cards else (False, 'No NVIDIA GPU selected or detected.')
        if cards and ok:
            card = cards[0]
            self.device, self.index = 'cuda', card['index']
            self.compute = 'float16' if card['free_mb'] >= 7000 else 'int8_float16'
            self.batch = batch_for_memory(card['free_mb'])
            self.progress(f"GPU: {card['name']}, {card['free_mb']}/{card['total_mb']} MB free; batch {self.batch}.")
        else:
            self.device, self.compute, self.batch = 'cpu', 'int8', 1
            self.notices.append(detail)
            self.progress(detail)
        name = 'large-v3' if self.settings.mode == 'quality' else 'large-v3-turbo'
        self.progress(f'Loading {name} on {self.device} ({self.compute}); first use may download the model.')
        try:
            location = model_path(name, self.settings.offline)
            self.model = WhisperModel(location, device=self.device, device_index=self.index,
                                      compute_type=self.compute, local_files_only=self.settings.offline)
        except Exception as exc:
            if self.device == 'cuda':
                self.notices.append(f'GPU model loading failed: {exc}; using CPU int8.')
                self.progress(self.notices[-1])
                return self.load(force_cpu=True)
            raise RuntimeError(f'Model load failed: {exc}. Download once with Offline unchecked; '
                               'check disk space, connection, and dependency diagnostics.') from exc
        self.pipeline = BatchedInferencePipeline(model=self.model)

    def transcribe(self, path, cancel):
        check_cancel(cancel)
        self.load()
        while True:
            try:
                return self._transcribe(path, cancel)
            except Cancelled:
                raise
            except Exception as exc:
                detail = str(exc).lower()
                oom = any(word in detail for word in ['out of memory', 'cuda_error_out_of_memory'])
                if self.device == 'cuda' and oom and self.batch > 1:
                    self.batch = max(1, self.batch // 2)
                    self.notices.append(f'GPU memory pressure; retrying file with batch {self.batch}.')
                    self.progress(self.notices[-1])
                    gc.collect()
                    continue
                if self.device == 'cuda' and any(word in detail for word in ['cuda', 'cudnn', 'cublas', 'out of memory']):
                    self.notices.append(f'GPU transcription failed: {exc}; retrying on CPU.')
                    self.progress(self.notices[-1])
                    self.load(force_cpu=True)
                    continue
                raise

    def _transcribe(self, path, cancel):
        check_cancel(cancel)
        options = dict(language=None if self.settings.language == 'auto' else self.settings.language,
                       beam_size=5 if self.settings.mode == 'quality' else 1,
                       vad_filter=True, initial_prompt=self.settings.glossary or None,
                       condition_on_previous_text=False, without_timestamps=False)
        # PyAV decodes source directly. No intermediate audio file is written.
        if self.batch > 1:
            segments, info = self.pipeline.transcribe(str(path), batch_size=self.batch, **options)
        else:
            segments, info = self.model.transcribe(str(path), **options)
        rows, warnings = [], list(self.notices)
        previous = None
        for segment in segments:
            check_cancel(cancel)
            text = segment.text.strip()
            rows.append({'start': segment.start, 'end': segment.end, 'text': text})
            if segment.avg_logprob < -1 or segment.compression_ratio > 2.4 or segment.no_speech_prob > .6:
                warnings.append(f'{srt_time(segment.start)}: recognition heuristic flagged this segment; listen to the source.')
            if text and text == previous:
                warnings.append(f'{srt_time(segment.start)}: repeated segment; may be genuine repetition or a recognition error.')
            previous = text
            self.progress(f'{path.name}: {segment.end:.0f}/{info.duration:.0f} seconds')
        if not rows:
            warnings.append('No speech recovered. Check the selected/first audio stream and recording.')
        warnings.append('Recognition flags are heuristics, not a correctness guarantee. First audio stream only; VAD may omit quiet speech.')
        return Result(readable_text(rows),
                      {'language': info.language, 'duration_seconds': info.duration, 'device': self.device,
                       'compute_type': self.compute, 'batch_size': self.batch,
                       'model_revision': MODEL_REVISIONS['large-v3' if self.settings.mode == 'quality' else 'large-v3-turbo'],
                       'model': 'large-v3' if self.settings.mode == 'quality' else 'large-v3-turbo'}, warnings, rows)
