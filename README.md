# yt-downloader

A command-line YouTube video downloader that streams video data in chunks, keeping memory usage low regardless of file size.

## How it works

1. **yt-dlp** resolves the YouTube URL to a direct media stream URL (up to 1080p, non-HLS)
2. **requests** downloads the stream in 64KB chunks, writing each to disk as it arrives
3. Optionally, **ffmpeg** re-encodes the result to H.264/AAC MP4

## Requirements

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [requests](https://docs.python-requests.org/)
- ffmpeg (only needed for `--convert`)

Install Python dependencies:

```bash
pip install yt-dlp requests
```

Install ffmpeg (macOS):

```bash
brew install ffmpeg
```

## Usage

```bash
# Download a video
python main.py <YouTube URL>

# Download and convert to H.264/AAC MP4
python main.py --convert <YouTube URL>
```

### Example

```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

The file is saved in the current directory using the video's title as the filename.
