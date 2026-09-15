# Course Transcriber for Windows

A local desktop application that converts course folders into UTF-8 text for NotebookLM, Gemini, or other analysis tools. It extracts source content without automatic summaries, paraphrases, or uploads.

## Launch on this computer

Double-click **launch.cmd** in the original development folder. That folder has Python dependencies, both Whisper models, English OCR data, the NVIDIA runtime, and local Calibre configured. **A freshly extracted release ZIP needs the setup steps below**; downloads and virtual environments are deliberately excluded from the ZIP.

1. Choose the course input folder.
2. Choose an **empty output folder**, or the output folder previously created for the same course. It may be inside the input folder; the app excludes it automatically.
3. Select Quality or Fast. Leave Device on Auto for NVIDIA GPU detection, or choose CPU.
4. Set subfolders, combined text, and optional subtitles. Use Options for a glossary or language settings.
5. Start processing. Completed, skipped, failed, and unsupported files appear separately.
6. Open the output folder and double-click **index.html**. It links to the current run's text, timestamps, subtitles, metadata, review notes, and combined text.

The launcher starts a Python/Tkinter desktop app; this release is **not a standalone executable**. Keep the project folder intact. Do not move an existing `.venv`; run setup again in a newly extracted project folder.

## Reproducible setup on another Windows machine

Use Windows 10/11 x64 and **Python 3.12 x64**, including Tcl/Tk and the Python launcher. Validation used Python 3.12.9. Install Python from [python.org](https://www.python.org/downloads/windows/).

Extract the release ZIP into a dedicated folder, then:

1. Run `setup.cmd`. It creates `.venv`, installs every dependency version from `requirements.lock.txt`, runs `pip check`, and prints diagnostics. Internet is required for these downloads. Missing optional GPU/OCR/MOBI dependencies are reported; they do not block text-only use.
2. For NVIDIA acceleration, run `install-gpu.cmd`. It downloads roughly **1.25 GB** of pinned NVIDIA CUDA 12 cuBLAS/cuDNN 9 archives, verifies SHA-256 checksums, and extracts DLLs into `tools/cuda`. It does not change system PATH or install a GPU driver. Have a current compatible NVIDIA driver and Microsoft Visual C++ x64 runtime installed. Diagnostics distinguish GPU detection from DLL availability; actual inference remains the final check.
3. For scanned or mixed PDFs, run `install-ocr.cmd`. It downloads pinned English language data (about 4 MB). PyMuPDF includes the OCR engine; no standalone Tesseract executable is required for this setup. Alternatively, select a Tesseract `tessdata` folder in Options. Other OCR languages require their own `.traineddata` files and language codes, such as `eng+spa`.
4. For MOBI, run `install-mobi.cmd`. It downloads pinned **Calibre 9.14.0 Portable** (about 210 MB), verifies its checksum, and installs under `tools/Calibre Portable`. Calibre Portable has a short-path restriction; the script uses Windows short paths when available. If that is unavailable, install [Calibre for Windows](https://calibre-ebook.com/download_windows), then select its `ebook-convert.exe` in Options. Standard `C:\Program Files\Calibre2` installs are auto-detected.
5. Run `launch.cmd`.

The first audio/video run downloads the selected model from Hugging Face into `tools/models`. Quality uses **large-v3** (roughly 3 GB); Fast uses **large-v3-turbo** (roughly 1.6 GB). Exact model revisions are pinned in `course_transcriber/media.py`. Leave at least 12 GB free for dependencies, caches, and temporary setup archives, plus room for source/output material. Windows model caching may use additional space without symlink support.

After these downloads, select **Offline / cached models only** to prohibit model network requests. Document processing is local. No paid API, account, or automatic upload is required. Download archives remain in `tools/downloads`; they can be removed manually after setup if space is needed. The application never removes source files.

### Command-line use

From the project folder in PowerShell:

```powershell
.venv/Scripts/python -m course_transcriber --diagnostics
.venv/Scripts/python -m course_transcriber --input "D:\Courses\Example" --output "D:\Extracted\Example" --mode fast --offline --srt
.venv/Scripts/python -m course_transcriber --help
```

Quality is the default. `--device cpu` selects CPU int8. `--language en` is the default; `--language auto` enables speech-language detection. `--glossary terms.txt` supplies a short UTF-8 recognition prompt (up to 1,000 characters). Use a list of names/terms, not a replacement transcript. Whisper may only use part of a prompt; a glossary does not guarantee correct terms. A changed glossary or extraction setting invalidates previous completion matches.

Ctrl+C requests cancellation in the CLI. The GUI requests cancellation at page/segment/file boundaries and force-stops its worker after 10 seconds if a native operation or download remains blocked. Restart reprocesses the unfinished file from its beginning; it does not resume mid-lesson.

## Formats and extraction behavior

| Format | Processing | Practical limits |
| --- | --- | --- |
| MP4, MKV, MOV, MP3, M4A, WAV, FLAC, TS (MPEG transport stream) | Local faster-whisper with direct PyAV decoding | First audio stream; captions/slides/video images are not extracted |
| AVI, WEBM, OGG, AAC, WMA, M4V | Same media decoder | Accepted, but not exercised in the current integration fixtures; codec support varies |
| PDF | Selectable text per page; local OCR when a page contains images or unrecognized vector content | Mixed image/text pages are processed; columns, formulas, tables, poor scans, and overlapping OCR layers need review |
| DOCX | Headings, body paragraphs, tables in document order | Headers, footers, footnotes, text boxes, tracked revisions, and text embedded in images may be omitted; no reliable page count without Word layout |
| TXT, MD, Markdown | Preserve text and Markdown syntax; UTF-8/UTF-16 handling with fallback encoding detection | Inferred encodings are flagged for review; binary text is rejected |
| EPUB | Spine chapter order, headings, text, image alt text | Complex CSS/layout, images, or unusual spine structures need review; no fixed page count |
| Unprotected MOBI | Local Calibre conversion to temporary EPUB, then the EPUB processor | DRM is unsupported; conversion may alter chapter layout |

Other extensions are reported as unsupported. Password-protected/restricted PDFs and recognized encrypted EPUB content fail clearly. Invalid/encrypted DOCX and failed MOBI conversions report diagnostic errors. The app does not unlock DRM or invent missing content. Complex tables/layouts are not perfectly extracted. Existing PDF OCR layers are generally retained; their errors cannot always be detected.

## GPU behavior

The application queries NVIDIA GPU **total and currently free VRAM**, choosing the device with the most free memory. It never infers memory from a model name. Auto uses float16 with at least 7,000 MB free, otherwise int8/float16. Initial batches are conservative heuristics:

| Free VRAM before model loading | Batch |
| --- | --- |
| 10,000 MB or more | 8 |
| 7,000–9,999 MB | 4 |
| 5,000–6,999 MB | 2 |
| Below 5,000 MB | 1 |

The selected model loads once per session and is reused across media files. Recoverable GPU memory failures halve the batch and retry the file. If batch 1 still fails, or a CUDA runtime error occurs, the app reloads on CPU int8 and retries. This deliberate fallback is the exception to loading once. Missing NVIDIA libraries trigger CPU fallback with a diagnostic note. Native DLL crashes can terminate the worker; choose CPU and restart if that happens.

Quality uses beam size 5; Fast uses beam size 1. Both use voice activity detection. Quiet speech can be missed; review uncertain passages. Suspected repetition, compression, or recognition problems go to `<source>.warnings.txt`, separate from source text. These flags are heuristics, not calibrated certainty or guarantees of correctness.

PyAV avoids intermediate audio files, but decoded audio/features consume RAM. Very long recordings may exhaust system RAM, including on GPU. Long-course throughput and memory pressure require testing on your real material. An RTX 4000-series laptop was not available for testing.

## Output and restart safety

Each output folder is owned by one input folder using `.course-transcriber.json`. Existing non-empty unrelated folders are rejected. Output cannot equal or contain the input folder. Generated roots are excluded during discovery, including previous application outputs nested in the source. Symlinks/junctions are not followed. Originals are opened read-only.

```text
output/
  index.html                       # Current results, human-readable links
  report.json                      # Latest run, failures and exclusions
  state.json                       # Completion/settings/checksum records
  lessons/
    relative/course/folder/
      lesson.mp4--<identity hash>/
        rev-<revision>/
          lesson.txt                # Metadata header + readable source content
          lesson.timestamped.txt    # Audio/video only
          lesson.srt                # Optional, audio/video only
          lesson.metadata.json
          lesson.warnings.txt
  runs/<run-id>/combined.txt        # Optional combined successful lessons
```

The full original extension and a relative-path hash prevent `lesson.mp4`, `lesson.pdf`, and similarly named lessons from colliding. Source folder structure is preserved below `lessons`. Every source is SHA-256 hashed; the app skips it only when its source hash, processing-settings fingerprint, complete state, and all output hashes still match. This full-content verification adds disk I/O even on skipped runs.

Reprocessing writes a new immutable revision. Files are flushed before publishing the revision directory, and completion state is atomically replaced last. Interrupted writes remain in clearly named `.partial` directories/files. A `running`, `failed`, or `cancelled` record is not completion. The next run retries it. OS file locks prevent two sessions from sharing an output folder and release automatically after a crash.

Use **index.html** for the current run. Older revisions are retained and never silently overwritten. Previous successful revisions may exist even when a newer attempt failed; the current index/report distinguishes them. Combined text contains only current-run successful or verified unchanged lessons, with explicit boundaries and relative source references. Its header reports failures/exclusions; it does not pretend omitted lessons were extracted. Source deletion removes a lesson from subsequent combined outputs but does not delete its historical outputs.

Keep output folders writable and avoid external modifications during a run. Very deep paths can exceed Windows path limits; use short course/output roots or enable Windows long-path support. Hard process termination or power failure may leave `.partial` files and unpublished revisions; these are not reused. Output revisions and model caches are retained, so disk use grows.

Outputs use the original filename stem: `Lesson 1.mp4` becomes `Lesson 1.txt`, with `Lesson 1.timestamped.txt` and optional `Lesson 1.srt`. On your next run, verified existing outputs named `text.txt` are copied into a new revision with source-based filenames, without repeating extraction or transcription. The index and combined-text references update automatically; older revisions remain available. Restart the app before running the same input/output folders again.

## Validation and development

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pip check
powershell -NoProfile -File scripts/make_speech.ps1
.venv/Scripts/python scripts/make_fixtures.py
.venv/Scripts/python scripts/verify_media.py
.venv/Scripts/python scripts/package_release.py
```

`verify_media.py` requires the downloaded models and GPU runtime and intentionally asserts actual CUDA use. It also runs CPU int8. Fixtures are generated locally and contain no user course material. Tests requiring OCR or Calibre skip when those dependencies are absent; the validated environment had both installed.

See [VALIDATION.md](VALIDATION.md) for exact tests, observed timings, and unverified behavior. See [docs/library-notes.md](docs/library-notes.md) for verified official APIs and dependency notes.

## Repository review and attribution

Reviewed [MrOrtiz/local-mp4-transcriber](https://github.com/MrOrtiz/local-mp4-transcriber) at commit `27ad632901e315df91c65198c0ceba0f58afe6a1`. The original single-file script converted MP4 to a source-adjacent FLAC, used hard-coded CUDA/large-v3, and wrote source-adjacent TXT/SRT. Its timestamp formatting was adapted; the processor architecture, desktop UI, document support, storage, and recovery were replaced. The original MIT notice is retained in `LICENSE`. Third-party dependencies retain their own licenses, including PyMuPDF, EbookLib, Calibre, model weights, and NVIDIA runtime components.

The inspected reference checkout is retained under `reference/` locally and excluded from Git and release packaging.
