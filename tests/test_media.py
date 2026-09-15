from course_transcriber.media import batch_for_memory, srt_time, MediaSession, readable_text
from course_transcriber.types import Settings, Result
from dataclasses import replace
import threading


def test_batch_memory_not_gpu_model_name():
    assert [batch_for_memory(mb) for mb in [3000, 5500, 7500, 11000]] == [1, 2, 4, 8]


def test_srt_rounding():
    assert srt_time(59.9996) == '00:01:00,000'
    assert srt_time(3661.123) == '01:01:01,123'


def test_readable_transcript_joins_split_sentences_without_rewording():
    rows = [{'start': 0, 'end': 2, 'text': 'Extract text from'},
            {'start': 2, 'end': 3, 'text': 'documents.'},
            {'start': 6, 'end': 8, 'text': 'Keep originals unchanged.'}]
    assert readable_text(rows) == 'Extract text from documents.\n\nKeep originals unchanged.'
    assert rows[0]['text'] == 'Extract text from'


def test_oom_retry_then_cpu(monkeypatch):
    session = MediaSession(Settings(), lambda _: None)
    session.device, session.batch = 'cuda', 4
    loads, attempts = [], []
    def load(force_cpu=False):
        loads.append(force_cpu)
        if force_cpu:
            session.device = 'cpu'
    def transcribe(*_):
        attempts.append((session.device, session.batch))
        if session.device == 'cuda':
            raise RuntimeError('CUDA out of memory')
        return Result('Recovered')
    monkeypatch.setattr(session, 'load', load)
    monkeypatch.setattr(session, '_transcribe', transcribe)
    assert session.transcribe('unused', threading.Event()).text == 'Recovered'
    assert attempts == [('cuda', 4), ('cuda', 2), ('cuda', 1), ('cpu', 1)]
    assert loads == [False, True]


def test_mpeg_transport_stream_audio_decoding(tmp_path):
    import av
    import numpy as np
    from faster_whisper.audio import decode_audio
    path = tmp_path / 'transport.ts'
    with av.open(str(path), 'w', format='mpegts') as output:
        stream = output.add_stream('aac', rate=48000)
        stream.layout = 'mono'
        samples = (.2 * np.sin(2 * np.pi * 440 * np.arange(48000) / 48000)).astype(np.float32)
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format='fltp', layout='mono')
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    with av.open(str(path)) as source:
        assert source.format.name == 'mpegts'
    decoded = decode_audio(str(path), sampling_rate=16000)
    assert 15000 <= len(decoded) <= 18000
    assert np.max(np.abs(decoded)) > .05
