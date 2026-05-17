#!/usr/bin/env python3
"""
YouTube Video Downloader — Python Streaming Example
Demonstrates chunked/streaming I/O while downloading a YouTube video.

Requirements:
    pip install yt-dlp requests

Usage:
    python main.py <YouTube URL>
    python main.py --convert <YouTube URL>
"""

import argparse
import os
import subprocess
import sys
import time
import requests
import yt_dlp


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


def stream_download(url: str, output_path: str, headers: dict = None, chunk_size: int = 1024 * 64) -> None:
    """
    Download a file from `url` to `output_path` using chunked streaming.

    This is the core streaming demonstration:
      - `stream=True` tells requests NOT to download the body immediately.
      - We iterate over `response.iter_content(chunk_size)` to pull data
        in small pieces, writing each chunk to disk as it arrives.
      - Memory usage stays ~constant regardless of file size.
    """
    response = requests.get(url, stream=True, timeout=30, headers=headers)
    response.raise_for_status()

    total_bytes = int(response.headers.get("Content-Length", 0))
    downloaded = 0
    start_time = time.time()

    print(f"\n  Saving to: {output_path}")
    print(f"  Total size: {format_size(total_bytes) if total_bytes else 'unknown'}\n")

    with open(output_path, "wb") as f:
        # ── STREAMING CORE ──────────────────────────────────────────────────
        # iter_content yields raw bytes in `chunk_size` pieces.
        # The generator pauses at each `yield`, letting us process/write
        # before fetching the next chunk from the network buffer.
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:          # filter out keep-alive empty chunks
                continue
            f.write(chunk)         # flush chunk to disk immediately
            downloaded += len(chunk)
        # ────────────────────────────────────────────────────────────────────

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

    elapsed = time.time() - start_time
    avg_speed = downloaded / elapsed if elapsed > 0 else 0
    print(f"\n\n  ✓ Done! {format_size(downloaded)} in {elapsed:.1f}s "
          f"(avg {format_size(int(avg_speed))}/s)\n")


def convert_to_mp4(input_path: str) -> str:
    output_path = os.path.splitext(input_path)[0] + "_converted.mp4"
    print(f"\n  Converting to H.264/AAC MP4…")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(input_path)
    return output_path


def get_best_stream_url(youtube_url: str) -> tuple[str, str, dict]:
    """
    Use yt-dlp to resolve the YouTube URL into a direct media stream URL.
    Returns (direct_url, suggested_filename).
    """
    ydl_opts = {
        "format": "best[height<=1080][protocol!=m3u8][protocol!=m3u8_native]/best[protocol!=m3u8][protocol!=m3u8_native]/best",
        "quiet": False,
        "no_warnings": False,
        "skip_download": True,
        "js_runtimes": {"node": {}},
        "remote_components": {"ejs:github"},
    }

    print("\n  Resolving stream URL via yt-dlp…")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)

    title = info.get("title", "video").replace("/", "-")
    ext = info.get("ext", "mp4")
    filename = f"{title}.{ext}"

    url = info["url"]
    headers = info.get("http_headers", {})

    print(f"  Title   : {info.get('title')}")
    print(f"  Duration: {info.get('duration', 0) // 60}m {info.get('duration', 0) % 60}s")
    print(f"  Format  : {info.get('format')}")

    return url, filename, headers


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Streaming Downloader")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--convert", action="store_true", help="Convert to H.264/AAC MP4 after download")
    args = parser.parse_args()

    print("=" * 60)
    print("  YouTube Streaming Downloader")
    print("=" * 60)

    try:
        direct_url, filename, headers = get_best_stream_url(args.url)
        stream_download(direct_url, filename, headers)
        if args.convert:
            filename = convert_to_mp4(filename)
        print(f"  File saved as: {filename}")
    except yt_dlp.utils.DownloadError as e:
        print(f"\n  yt-dlp error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"\n  Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        print("\n  ffmpeg conversion failed.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  Download cancelled.")
        sys.exit(0)

    print("=" * 60)


if __name__ == "__main__":
    main()