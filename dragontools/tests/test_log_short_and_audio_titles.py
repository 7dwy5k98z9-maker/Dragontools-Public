from pathlib import Path

from dragontools.core.audio_titles import build_audio_title
from dragontools.core.logger import DragonLogger


def test_audio_title_transcoded_full():
    assert build_audio_title(language="deu", codec="eac3", channels=6, bitrate_bps=640000) == "Deutsch EAC3 5.1 640kbps"


def test_audio_title_copy_without_bitrate_language_only():
    assert build_audio_title(language="eng", codec="truehd", channels=8, bitrate_bps=0) == "Englisch"


def test_short_and_long_log_are_split(tmp_path: Path):
    gui = []
    logger = DragonLogger(tmp_path, gui_callback=gui.append)
    logger.info("interne Detailmeldung")
    logger.info("Quelle: HEVC | 3840×2160 | HDR10+")
    logger.info("  📄 Exportiere 2 externe Untertiteldatei(en) (zusätzliche Sidecar-Regel) …")
    logger.info("  📄 Sidecar OK: Film.de.ass")
    logger.pipeline("hdr10+", "mkv", False, True)
    logger.error("Testfehler")
    assert logger.log_file is not None
    assert logger.long_log_file is not None
    short = logger.log_file.read_text(encoding="utf-8")
    long = logger.long_log_file.read_text(encoding="utf-8")
    assert "interne Detailmeldung" not in short
    assert "interne Detailmeldung" in long
    assert "Quelle: HEVC" in short
    assert "Exportiere 2 externe Untertiteldatei" in short
    assert "Sidecar OK: Film.de.ass" in short
    assert "Pipeline: HDR10+" in short
    assert "Testfehler" in short
    assert all("interne Detailmeldung" not in line for line in gui)
