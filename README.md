# Local MP4 Transcriber

Simple local script to extract audio from an MP4 file with ffmpeg and transcribe it with faster-whisper.

## Usage

pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12
sudo apt install ffmpeg

```bash
python transcribe_mp4.py "video.mp4"

Optional:
python transcribe_mp4.py "video.mp4" --keep-audio

Outputs:
video.txt
video.srt

## Requires
- Python
- ffmpeg
- faster-whisper
- CUDA libraries if using GPU


No need to connect your local folder to Git at all. Just copy the file into GitHub through the website.
