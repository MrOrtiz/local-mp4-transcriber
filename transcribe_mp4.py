import argparse
import subprocess
from pathlib import Path
from faster_whisper import WhisperModel


def srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours = millis // 3_600_000
    millis %= 3_600_000
    minutes = millis // 60_000
    millis %= 60_000
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def extract_audio(input_file: Path, audio_file: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-map", "0:a:0",
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "flac",
        str(audio_file),
    ]

    print(f"Extracting audio to: {audio_file}")
    subprocess.run(cmd, check=True)


def transcribe(audio_file: Path, txt_file: Path, srt_file: Path) -> None:
    print("Loading Whisper model...")

    model = WhisperModel(
        "large-v3",
        device="cuda",
        compute_type="float16",
    )

    print("Transcribing...")

    segments, info = model.transcribe(
        str(audio_file),
        beam_size=5,
        vad_filter=True,
    )

    print(f"Detected language: {info.language} probability: {info.language_probability:.2f}")
    print(f"Writing TXT: {txt_file}")
    print(f"Writing SRT: {srt_file}")

    with open(txt_file, "w", encoding="utf-8") as txt, open(srt_file, "w", encoding="utf-8") as srt:
        for i, segment in enumerate(segments, start=1):
            text = segment.text.strip()

            print(f"[{segment.start:.2f} - {segment.end:.2f}] {text}")

            txt.write(f"[{segment.start:.2f} - {segment.end:.2f}] {text}\n")
            txt.flush()

            srt.write(f"{i}\n")
            srt.write(f"{srt_time(segment.start)} --> {srt_time(segment.end)}\n")
            srt.write(f"{text}\n\n")
            srt.flush()

    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract audio from MP4 and transcribe it.")
    parser.add_argument("input", help="Path to MP4 file")
    parser.add_argument("--keep-audio", action="store_true", help="Keep extracted FLAC audio file")

    args = parser.parse_args()

    input_file = Path(args.input).expanduser().resolve()

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    output_stem = input_file.with_suffix("")
    audio_file = output_stem.with_suffix(".flac")
    txt_file = output_stem.with_suffix(".txt")
    srt_file = output_stem.with_suffix(".srt")

    extract_audio(input_file, audio_file)
    transcribe(audio_file, txt_file, srt_file)

    if not args.keep_audio:
        print(f"Removing temporary audio file: {audio_file}")
        audio_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
