# yt-downloader

A command-line YouTube video downloader that streams video data in chunks, keeping memory usage low regardless of file size. This app is for expermiental purpose only, as well as downloading any content you personally own. I'm sure YouTube doesn't want you downloading any video willy nilly. That'd just be silly... 

## How it works

YouTube only serves combined video+audio in a single stream at 360p. Anything higher comes as separate video-only and audio-only streams, so:

1. **yt-dlp** resolves the YouTube URL to direct stream URLs, preferring H.264 video (up to 1080p) + AAC audio
2. **requests** downloads each stream in 64KB chunks, writing each to disk as it arrives. Streams are requested in 10MB HTTP Range pieces, because YouTube throttles a single long request for a video-only stream to a crawl
3. **ffmpeg** muxes the two streams into one `.mp4` without re-encoding
4. **ffprobe** verifies A/V sync: exactly one video and one audio track, start times within 0.1s, durations within 0.5s. The script exits non-zero if the check fails
5. Optionally, **ffmpeg** re-encodes the result to H.264/AAC MP4 (`--convert`)

If no H.264 1080p stream exists, it falls back to any mp4 video, then to any video (saved as `.mkv`), and finally to the single 360p stream.

## Requirements

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [requests](https://docs.python-requests.org/)
- ffmpeg + ffprobe (muxing and sync verification)
- node or deno (yt-dlp uses it to solve YouTube's JS challenges)

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

# Download and re-encode to H.264/AAC MP4
python main.py --convert <YouTube URL>

# Cap the resolution (default 1080)
python main.py --max-height 720 <YouTube URL>
```

### Example

```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

The file is saved in the current directory using the video's title as the filename.
