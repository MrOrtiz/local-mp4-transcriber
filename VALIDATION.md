# Validation record

Date: 2026-09-14 (Asia/Dubai). This is a tested initial release, not a claim of perfect transcription or document extraction.

## Environment

- Windows 11, build 26200, x64.
- Python 3.12.9, Tkinter available.
- NVIDIA GeForce RTX 3060, **12,288 MB total VRAM**, about 10,800 MB free before inference; NVIDIA driver 591.86.
- faster-whisper 1.2.1, CTranslate2 4.6.0, PyAV 16.0.1, PyMuPDF 1.26.5, python-docx 1.2.0, EbookLib 0.19.
- Project-local CUDA 12 cuBLAS 12.8.4.1 and cuDNN 9.10.2.21. English tessdata_fast at a pinned commit. Calibre 9.14.0 Portable.
- Both large-v3 and large-v3-turbo snapshots downloaded and exercised with `offline=True`.

## Automated suite

`python -m pytest -q`: **42 passed** after the output-filename update, no skips in the configured development environment. Five upstream PyMuPDF/SWIG deprecation warnings were emitted. `python -m pip check`: **No broken requirements found**.

Tests cover:

- Recursive/nonrecursive discovery, case-insensitive extensions, natural lesson order, unsupported-file reporting, generated output exclusion, Windows junction exclusion.
- Same-stem different-extension collisions, nested source structure, originals unchanged, output-folder ownership and unsafe-folder rejection.
- Unchanged-source skips, output checksum verification, settings invalidation, tampered-artifact recovery, removed-source exclusion from new combined text.
- Individual failure continuation and retry, simulated source mutation during extraction, cancellation/restart, incomplete-state recovery, interrupted multi-artifact writes remaining `.partial`, session locks, malicious path escape in a saved manifest.
- UTF-8/BOM/UTF-16 text and Markdown preservation; DOCX headings and interleaved paragraph/table order; selectable PDF page references; scanned/mixed PDF OCR; missing OCR diagnosis; protected PDF rejection.
- EPUB spine ordering with deliberately reversed archive order, retained inline text, protected EPUB rejection.
- Real Calibre EPUB→MOBI→EPUB conversion and chapter extraction; corrupt MOBI failure; missing Calibre diagnosis.
- SRT timestamp rounding, mocked media output creation/session reuse, simulated GPU OOM batch reduction and CPU retry.
- Readable transcript paragraph joining without changing recognized words or timestamped segments.
- Actual Tkinter widgets and spawned Windows worker: start, file progress, completed status, unchanged-file restart, cancellation. These are automated desktop workflow tests, not a broad manual usability/accessibility review.
- Safe HTML escaping and current-result links in the output index.

The OOM tests simulate exceptions. No real out-of-VRAM event, power failure, or forced native-library crash was induced.

One test run reported a Tk file-initialization error while creating a second Tcl/Tk interpreter, although the referenced system file existed. The isolated desktop rerun passed. The final desktop test reuses one application window for start/restart/cancel, matching production, and passed in the final suite. A broader manual desktop review remains outstanding.

## Real media inference

Generated a 20.306-second course introduction using Windows System.Speech, then encoded it with PyAV into WAV, FLAC, MP3, M4A, MP4, MKV, and MOV. MP4/MKV/MOV include a simple video stream. This validates codecs, routing, local inference, and outputs on controlled fixtures; it does not establish accuracy on real courses.

| Check | Actual result |
| --- | --- |
| Fast / large-v3-turbo / CUDA float16 / batch 8 | All seven required formats produced non-empty relevant speech text |
| Quality / large-v3 / CUDA float16 / batch 8 | WAV produced relevant text and six timestamped segments |
| Fast / CPU int8 / batch 1 | WAV produced relevant text |
| Auto with CUDA runtime absent | Real CPU int8 fallback succeeded in the fresh environment using the already-downloaded model cache |
| Model reuse | Same loaded model object across all seven Fast GPU files |
| Full folder run with SRT | Seven completed files, metadata, readable text, timestamps, SRT, review notes, combined text |
| Corrupt MP4 followed by TXT | Media failed with decoder error; next document completed; combined text reported one omission |

Observed smoke-test times, **not throughput promises**:

| Case | Initial model load | Decode/VAD/inference for ~20 seconds of synthetic speech |
| --- | ---: | ---: |
| Fast GPU | 4.05 s | 0.51–1.19 s across seven formats |
| Quality GPU | 5.70 s | 1.66 s for WAV |
| Fast CPU | 4.12 s | 13.29 s for WAV |

These are single-process, single-run timings on short cached-model fixtures. Startup, disk/network downloads, longer context, silence, accents, music, CPU contention, GPU contention, and different hardware change results. Initial raw results and recognized text are in [docs/media-smoke-results.json](docs/media-smoke-results.json); subsequent readable-text formatting joins adjacent segments without changing words. The separate missing-runtime fallback record is [docs/automatic-cpu-fallback.json](docs/automatic-cpu-fallback.json). No WER/CER or course-accuracy score is claimed. No real course recording/reference transcript pair was provided.

## TS support update

Added `.ts` MPEG transport streams to media discovery, including uppercase `.TS`. Automated checks cover discovery, media routing, same-stem output separation, timestamp/SRT creation, and real AAC transport-stream decoding through faster-whisper's decoder.

A generated 20-second MPEG-TS fixture with H.264 video and AAC speech was transcribed through the full folder pipeline using Fast mode on the RTX 3060. Readable text, timestamped text, SRT, metadata, review notes, and combined text were produced. The source hash was unchanged, and the next run skipped the completed file. Evidence: [docs/ts-smoke-results.json](docs/ts-smoke-results.json). No dependency or settings-fingerprint change was required, so adding TS support does not invalidate existing successful outputs. Other transport-stream codecs and damaged/live-stream captures remain unverified.

## Real document pipeline

An end-to-end folder run processed TXT, Markdown, DOCX, EPUB, a three-page selectable/scanned/mixed PDF, and an unprotected MOBI. All six completed. Rerunning verified and skipped unchanged files. The PDF's mixed page was rendered and visually inspected against its extraction fixture; native heading and scanned body were recovered in the expected order. Local artifacts remain under `tmp/document-output` and `tmp/media-output`; they are not included in the release ZIP.

## Setup and package checks

Pinned Python dependencies were installed and checked on this Windows system. Actual model, OCR and CUDA downloads completed; NVIDIA archive checksums were verified. The MOBI resource installer was exercised against the local Calibre installation. Calibre's portable path-length restriction was handled using the project's Windows short path.

The release ZIP was extracted into a separate folder and its setup script successfully created a fresh virtual environment, installed the locked dependencies, and ran diagnostics. Before optional resource downloads, its test run reported **32 passed, 3 skipped** (the expected OCR and real-Calibre tests). That fresh environment also performed actual automatic CPU fallback when CUDA DLLs were missing, reading the already-downloaded model cache. A clean install on a second computer remains unverified.

The release contains source, desktop launcher, setup/resource scripts, the full Python dependency lock, tests, and documentation. It excludes virtual environments, downloaded models/DLLs/Calibre, fixture media, reference checkout, and user settings. ZIP integrity and required-file inventory are verified by `scripts/package_release.py`. This is a source distribution with a desktop launcher, not a signed standalone EXE/MSI.

## Remaining limits

- RTX 4000-series laptop hardware, low-VRAM GPUs, multiple GPUs, Quality-mode CPU performance, and long recordings have not been measured on actual hardware/material.
- AVI/WEBM/OGG/AAC/WMA/M4V are accepted but were not part of the real codec fixtures.
- No real-course accuracy benchmark, noisy/poor recordings, multi-hour endurance run, manual subtitle timing audit, or real DRM-protected MOBI fixture was tested.
- PDF OCR/layout is approximate. Complex tables, columns, math, low-resolution scans, handwritten notes, overlapping OCR layers, and heavily formatted ebooks need human review.
- DOCX embedded-image text and several ancillary document parts are not extracted; these omissions are disclosed in output warnings and README.
- Subtitle segments follow model segmentation; they are not edited into broadcast-length cues.
- Cancel/restart resumes at file boundaries. Decoded audio can consume substantial RAM. Historical revisions/caches are retained.
- Power-loss durability depends on the filesystem; flushed files, atomic replacement, checksums, and completion markers reduce risk but do not substitute for a backup.
- Fresh-machine setup, DPI/accessibility variations, and antivirus/SmartScreen behavior have not been broadly tested.

No course-material upload or paid API call was performed during validation.

## Source-filename output update (2026-09-15)

Readable text now uses the source stem, with separately named timestamp, subtitle, metadata, and review-note files. Artifact roles replace filename-based lookup when assembling combined text. Six added tests cover spaces, Unicode, multiple dots, source names that previously collided with sidecars, legacy document/media migration without running their processors, preserved old revision hashes, updated index/combined references, and idempotent restart. The full suite passed (42 tests). The release ZIP was rebuilt. No GPU inference changes were made or needed retesting for this update.
