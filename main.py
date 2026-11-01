#!/usr/bin/env python3
"""
YouTube Video Downloader — Python Streaming Example
Demonstrates chunked/streaming I/O while downloading a YouTube video.

YouTube only serves combined video+audio in a single stream at 360p. For
anything higher it serves separate video-only and audio-only streams, so
this script downloads each one with chunked streaming, muxes them into a
single file with ffmpeg (no re-encode), and then verifies with ffprobe that
the audio and video tracks line up.

Requirements:
    pip install yt-dlp requests
    ffmpeg + ffprobe on PATH

Usage:
    python main.py <YouTube URL>
    python main.py --convert <YouTube URL>
    python main.py --max-height 720 <YouTube URL>
"""

import argparse
import json
import os
import subprocess
import sys
import time
import requests
import yt_dlp

# Sync tolerances for the post-mux verification step.
START_OFFSET_TOLERANCE_S = 0.10   # audio vs video start_time
DURATION_DELTA_TOLERANCE_S = 0.50  # audio vs video total duration


def format_size(bytes_total: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_total < 1024:
            return f"{bytes_total:.1f} {unit}"
        bytes_total /= 1024
    return f"{bytes_total:.1f} TB"


def draw_progress_bar(downloaded: int, total: int, bar_width: int = 40) -> str:
    """Render a simple ASCII progress bar."""
    if total <= 0:
        return "[???]"
    ratio = min(downloaded / total, 1.0)
    filled = int(bar_width * ratio)
    bar = "█" * filled + "░" * (bar_width - filled)
    percent = ratio * 100
    return f"[{bar}] {percent:5.1f}%"


def stream_download(
    url: str,
    output_path: str,
    headers: dict = None,
    chunk_size: int = 1024 * 64,
    range_size: int = 10 * 1024 * 1024,
) -> None:
    """
    Download a file from `url` to `output_path` using chunked streaming.

    This is the core streaming demonstration:
      - `stream=True` tells requests NOT to download the body immediately.
      - We iterate over `response.iter_content(chunk_size)` to pull data
        in small pieces, writing each chunk to disk as it arrives.
      - Memory usage stays ~constant regardless of file size.

    The file is requested in `range_size` pieces via HTTP Range headers
    (default 10 MB, the same size yt-dlp uses). YouTube heavily throttles
    a single long-lived request for a video-only stream, but serves each
    bounded range at full speed. If the server ignores the Range header
    and answers 200, the whole body is streamed in one pass.
    """
    headers = dict(headers or {})
    downloaded = 0
    total_bytes = 0
    start_time = time.time()

    print(f"\n  Saving to: {output_path}")

    with requests.Session() as session, open(output_path, "wb") as f:
        while True:
            req_headers = dict(headers)
            req_headers["Range"] = f"bytes={downloaded}-{downloaded + range_size - 1}"
            response = session.get(url, stream=True, timeout=30, headers=req_headers)
            response.raise_for_status()

            ranged = response.status_code == 206
            if ranged:
                # Content-Range: bytes <first>-<last>/<total>
                content_range = response.headers.get("Content-Range", "")
                if not total_bytes and "/" in content_range:
                    total_bytes = int(content_range.rsplit("/", 1)[1])
            else:
                total_bytes = int(response.headers.get("Content-Length", 0))

            if downloaded == 0:
                print(f"  Total size: {format_size(total_bytes) if total_bytes else 'unknown'}\n")

            received = 0
            # ── STREAMING CORE ──────────────────────────────────────────────
            # iter_content yields raw bytes in `chunk_size` pieces.
            # The generator pauses at each `yield`, letting us process/write
            # before fetching the next chunk from the network buffer.
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:          # filter out keep-alive empty chunks
                    continue
                f.write(chunk)         # flush chunk to disk immediately
                downloaded += len(chunk)
                received += len(chunk)
            # ────────────────────────────────────────────────────────────────

                # Live progress display
                elapsed = time.time() - start_time
                speed = downloaded / elapsed if elapsed > 0 else 0
                bar = draw_progress_bar(downloaded, total_bytes)
                print(
                    f"\r  {bar}  {format_size(downloaded):>10}"
                    f"  {format_size(int(speed))}/s",
                    end="",
                    flush=True,
                )

            # Stop when the server didn't honour the range (whole body already
            # streamed), when we've reached the known end, or when a range
            # came back empty (unknown total; nothing more to fetch).
            if not ranged or (total_bytes and downloaded >= total_bytes) or received == 0:
                break

    elapsed = time.time() - start_time
    avg_speed = downloaded / elapsed if elapsed > 0 else 0
    print(f"\n\n  ✓ Done! {format_size(downloaded)} in {elapsed:.1f}s "
          f"(avg {format_size(int(avg_speed))}/s)\n")


def run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg quietly, raising CalledProcessError with stderr attached on failure."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, result.args, stderr=result.stderr)


def mux_streams(video_path: str, audio_path: str, output_path: str) -> None:
    """
    Combine a video-only and an audio-only file into one container.

    `-c copy` remuxes without re-encoding, so this is fast and lossless.
    Both inputs come from the same YouTube upload, so their timelines
    already match; we just need them in the same file.
    """
    print(f"\n  Muxing video + audio → {output_path}")
    run_ffmpeg([
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
        "-movflags", "+faststart",
        output_path,
    ])


def convert_to_mp4(input_path: str) -> str:
    output_path = os.path.splitext(input_path)[0] + "_converted.mp4"
    print(f"\n  Converting to H.264/AAC MP4…")
    run_ffmpeg([
        "-i", input_path,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ])
    os.remove(input_path)
    return output_path


def probe(path: str) -> dict:
    """Return ffprobe's JSON description of a media file."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,start_time,duration,nb_frames,avg_frame_rate"
                             ":format=duration",
            "-of", "json",
            path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def verify_sync(path: str) -> bool:
    """
    Check that the muxed file has exactly one video and one audio track and
    that their timelines agree:
      - both tracks start at (nearly) the same timestamp, and
      - both tracks run for (nearly) the same length.

    A start-time offset is the classic "lips don't match" symptom; a large
    duration mismatch means one track ends early or was truncated.
    Returns True if everything is within tolerance.
    """
    print("\n  Verifying A/V sync with ffprobe…")
    info = probe(path)
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]

    ok = True
    if len(video) != 1 or len(audio) != 1:
        print(f"  ✗ Expected 1 video + 1 audio track, found {len(video)} video / {len(audio)} audio")
        return False

    v, a = video[0], audio[0]
    container_duration = float(info.get("format", {}).get("duration", 0) or 0)
    v_start = float(v.get("start_time", 0) or 0)
    a_start = float(a.get("start_time", 0) or 0)
    v_dur = float(v.get("duration", 0) or container_duration)
    a_dur = float(a.get("duration", 0) or container_duration)

    start_offset = abs(v_start - a_start)
    duration_delta = abs(v_dur - a_dur)

    print(f"  Video : {v.get('codec_name')} {v.get('width')}x{v.get('height')} "
          f"start={v_start:.3f}s dur={v_dur:.3f}s")
    print(f"  Audio : {a.get('codec_name')} start={a_start:.3f}s dur={a_dur:.3f}s")

    if start_offset > START_OFFSET_TOLERANCE_S:
        print(f"  ✗ Start-time offset {start_offset:.3f}s exceeds {START_OFFSET_TOLERANCE_S}s")
        ok = False
    else:
        print(f"  ✓ Start-time offset {start_offset:.3f}s (≤ {START_OFFSET_TOLERANCE_S}s)")

    if duration_delta > DURATION_DELTA_TOLERANCE_S:
        print(f"  ✗ Duration mismatch {duration_delta:.3f}s exceeds {DURATION_DELTA_TOLERANCE_S}s")
        ok = False
    else:
        print(f"  ✓ Duration mismatch {duration_delta:.3f}s (≤ {DURATION_DELTA_TOLERANCE_S}s)")

    return ok


def _stream_entry(f: dict, kind: str) -> dict:
    """Pull the fields we need out of a yt-dlp format dict."""
    return {
        "url": f["url"],
        "headers": f.get("http_headers", {}),
        "ext": f.get("ext", "bin"),
        "kind": kind,
        # YouTube rejects the URL with 403 if fetched before this unix time.
        "available_at": int(f.get("available_at") or 0),
        # yt-dlp's suggested Range size for this format, if any.
        "range_size": int((f.get("downloader_options") or {}).get("http_chunk_size") or 0),
    }


def wait_until_available(streams: list[dict]) -> None:
    """
    YouTube stamps each stream URL with an `available_at` time and returns
    403 Forbidden for requests made before it (yt-dlp does the same wait,
    reported as "Sleeping N seconds as required by the site").
    """
    wait = max(s["available_at"] for s in streams) - int(time.time())
    if wait > 0:
        print(f"\n  Waiting {wait}s before download, as required by the site…")
        time.sleep(wait)


def resolve_streams(youtube_url: str, max_height: int) -> tuple[str, list[dict]]:
    """
    Use yt-dlp to resolve the YouTube URL into direct media stream URLs.

    Returns (title, streams) where each stream is a dict with keys
    url, headers, ext, kind ("video", "audio", or "muxed").

    Format preference:
      1. best H.264 (avc1) video-only up to max_height + best AAC audio (m4a)
         → remuxes cleanly into .mp4 and plays everywhere (QuickTime included)
      2. any mp4 video-only (e.g. AV1) up to max_height + AAC audio
      3. any best video-only up to max_height + any best audio → .mkv
      4. a single combined stream (360p fallback)
    """
    fmt = (
        f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={max_height}]+bestaudio"
        f"/best[height<={max_height}]/best"
    )
    ydl_opts = {
        "format": fmt,
        "quiet": False,
        "no_warnings": False,
        "skip_download": True,
        "js_runtimes": {"node": {}},
        "remote_components": {"ejs:github"},
    }

    print("\n  Resolving stream URLs via yt-dlp…")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)

    title = info.get("title", "video").replace("/", "-")
    duration = info.get("duration", 0) or 0
    print(f"  Title   : {info.get('title')}")
    print(f"  Duration: {duration // 60}m {duration % 60}s")

    requested = info.get("requested_formats")
    streams = []
    if requested:
        for f in requested:
            kind = "video" if f.get("vcodec") not in (None, "none") else "audio"
            streams.append(_stream_entry(f, kind))
            print(f"  {kind.capitalize():<8}: {f.get('format')}")
    else:
        streams.append(_stream_entry(info, "muxed"))
        print(f"  Format  : {info.get('format')} (single combined stream)")

    return title, streams


def _download_stream(stream: dict, output_path: str) -> None:
    kwargs = {}
    if stream.get("range_size"):
        kwargs["range_size"] = stream["range_size"]
    stream_download(stream["url"], output_path, stream["headers"], **kwargs)


def download(youtube_url: str, max_height: int) -> str:
    """Download, mux if needed, verify, and return the final filename."""
    title, streams = resolve_streams(youtube_url, max_height)

    wait_until_available(streams)

    if len(streams) == 1:
        filename = f"{title}.{streams[0]['ext']}"
        _download_stream(streams[0], filename)
        return filename

    video = next(s for s in streams if s["kind"] == "video")
    audio = next(s for s in streams if s["kind"] == "audio")

    # mp4 + m4a remux cleanly into mp4; anything else goes into mkv,
    # which accepts any codec combination.
    out_ext = "mp4" if (video["ext"] == "mp4" and audio["ext"] in ("m4a", "mp4")) else "mkv"
    filename = f"{title}.{out_ext}"
    video_tmp = f"{title}.video.{video['ext']}.part"
    audio_tmp = f"{title}.audio.{audio['ext']}.part"

    try:
        print("\n  [1/2] Video stream")
        _download_stream(video, video_tmp)
        print("  [2/2] Audio stream")
        _download_stream(audio, audio_tmp)
        mux_streams(video_tmp, audio_tmp, filename)
    finally:
        for tmp in (video_tmp, audio_tmp):
            if os.path.exists(tmp):
                os.remove(tmp)

    if not verify_sync(filename):
        raise RuntimeError("A/V sync verification failed; see details above")

    return filename


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Streaming Downloader")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--convert", action="store_true", help="Re-encode to H.264/AAC MP4 after download")
    parser.add_argument("--max-height", type=int, default=1080, help="Maximum video height (default: 1080)")
    args = parser.parse_args()

    print("=" * 60)
    print("  YouTube Streaming Downloader")
    print("=" * 60)

    try:
        filename = download(args.url, args.max_height)
        if args.convert:
            filename = convert_to_mp4(filename)
        print(f"\n  File saved as: {filename}")
    except yt_dlp.utils.DownloadError as e:
        print(f"\n  yt-dlp error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"\n  Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\n  ffmpeg/ffprobe failed:\n{e.stderr or ''}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"\n  {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  Download cancelled.")
        sys.exit(0)

    print("=" * 60)


if __name__ == "__main__":
    main()
