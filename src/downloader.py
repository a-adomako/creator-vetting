"""
downloader.py — Parallel reel video downloader.

Downloads Instagram reel videos from signed CDN URLs returned by Apify.
These URLs are directly accessible without Instagram authentication.

Videos are saved to a temp directory and should be deleted after processing.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = 60          # seconds per video
_CHUNK_SIZE = 1024 * 256        # 256 KB chunks
_MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB safety cap per video


def download_video(url: str, dest_path: Path) -> bool:
    """
    Download a single video from a URL to dest_path.

    Returns True on success, False on any error.
    Streams the download to avoid loading the whole file into memory.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT, headers=headers) as resp:
            resp.raise_for_status()

            content_length = int(resp.headers.get("content-length", 0))
            if content_length > _MAX_VIDEO_BYTES:
                logger.warning("Video too large (%d MB) — skipping %s", content_length // 1024 // 1024, url[:80])
                return False

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > _MAX_VIDEO_BYTES:
                        logger.warning("Video exceeded size cap mid-download — aborting")
                        return False

        return True

    except requests.RequestException as e:
        logger.warning("Download failed for %s: %s", url[:80], e)
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return False
    except OSError as e:
        logger.error("File write error for %s: %s", dest_path, e)
        return False


class VideoDownloader:
    """
    Downloads multiple reel videos in parallel using a thread pool.
    """

    def __init__(self, temp_dir: Path, max_workers: int = 4):
        self._temp_dir = temp_dir
        self._max_workers = max_workers

    def download_reels(
        self,
        video_urls: list[str],
        username: str,
    ) -> list[Path]:
        """
        Download a list of video URLs for a creator.

        Returns a list of Paths for successfully downloaded videos.
        Files are named <username>_<uuid>.mp4 inside temp_dir.
        """
        if not video_urls:
            return []

        tasks: list[tuple[str, Path]] = []
        for url in video_urls:
            filename = f"{username}_{uuid.uuid4().hex[:8]}.mp4"
            dest = self._temp_dir / filename
            tasks.append((url, dest))

        downloaded: list[Path] = []

        if len(tasks) == 1 or self._max_workers == 1:
            # Single-threaded for small batches
            for url, dest in tasks:
                if download_video(url, dest):
                    downloaded.append(dest)
        else:
            with ThreadPoolExecutor(max_workers=min(self._max_workers, len(tasks))) as pool:
                future_to_path = {
                    pool.submit(download_video, url, dest): dest
                    for url, dest in tasks
                }
                for future in as_completed(future_to_path):
                    dest = future_to_path[future]
                    try:
                        if future.result():
                            downloaded.append(dest)
                    except Exception as e:
                        logger.warning("Download task error: %s", e)

        logger.debug("@%s: downloaded %d/%d reels", username, len(downloaded), len(tasks))
        return downloaded

    @staticmethod
    def cleanup(paths: list[Path]) -> None:
        """Delete video files after processing. Called in finally blocks."""
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("Could not delete temp file %s: %s", path, e)
