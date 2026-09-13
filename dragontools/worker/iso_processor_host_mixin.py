from __future__ import annotations


class ISOProcessorHostMixin:
    """Public host contract consumed by :class:`ISOInputProcessor`.

    The methods intentionally resolve the legacy private hooks dynamically so
    existing callers/tests that replace those hooks at runtime remain
    compatible while the processor never crosses an object's private API.
    """

    @property
    def last_scan_error(self) -> str | None:
        return self._last_scan_error

    @property
    def last_ffmpeg_fallback_error(self) -> str | None:
        return self._last_ffmpeg_fallback_error

    def reset_scan_error(self) -> None:
        self._last_scan_error = None

    def log_message(self, message: str, level: str = "info") -> None:
        self._log(message, level)

    def start_file_log(self, path: str, total: int, iso_type: str) -> None:
        self._logger.file_start(
            self._current_idx,
            total,
            path,
            "iso",
            None,
            "makemkvcon",
            iso_type,
            q_label="Quelle",
        )

    def detect_iso_type(self, path: str) -> str:
        return self._detect_iso_type(path)

    def makemkv_available(self) -> bool:
        return self._makemkv_available()

    def scan_titles(self, path: str) -> list[dict]:
        return self._scan_titles(path)

    def scan_ffmpeg_fallback_titles(self, path: str) -> list[dict]:
        return self._scan_ffmpeg_fallback_titles(path)

    def extract_titles(self, path: str, title_ids: list[int], output_dir: str) -> bool:
        return self._extract_titles(path, title_ids, output_dir)

    def extract_with_ffmpeg_fallback(self, path: str, output_dir: str) -> bool:
        return self._extract_with_ffmpeg_fallback(path, output_dir)
