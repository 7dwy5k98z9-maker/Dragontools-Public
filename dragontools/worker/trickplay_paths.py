from __future__ import annotations

from pathlib import Path

from .trickplay_models import TrickplaySettings


def trickplay_root_for_video(video_path: str | Path) -> Path:
    video = Path(video_path)
    return video.with_name(f"{video.stem}.trickplay")


def trickplay_sprite_dir_for_video(video_path: str | Path, settings: TrickplaySettings) -> Path:
    return trickplay_root_for_video(video_path) / f"{int(settings.width)} - {settings.tile_label}"


def has_valid_trickplay_sprites(path: str | Path) -> bool:
    directory = Path(path)
    if not directory.is_dir():
        return False
    try:
        return any(
            image.is_file() and image.stat().st_size > 0
            for image in directory.glob("*.jpg")
        )
    except OSError:
        return False


def normalize_trickplay_conflict_mode(settings: TrickplaySettings) -> str:
    mode = str(getattr(settings, "conflict_mode", "") or "").strip().lower()
    if mode in {"skip", "overwrite", "backup"}:
        return mode
    return "skip" if bool(getattr(settings, "only_missing", True)) else "overwrite"


def trickplay_result_status(mode, *, root_exists, variant_exists):
    if mode == 'skip' and variant_exists:
        return 'skipped'
    if mode == 'skip' and root_exists:
        return 'created_variant'
    if mode == 'backup' and root_exists:
        return 'backed_up'
    if mode == 'overwrite' and root_exists:
        return 'replaced'
    return 'created'


def unique_trickplay_backup_path(path: Path) -> Path:
    candidate = path.with_name(f"{path.name}.bak")
    if not candidate.exists():
        return candidate
    for idx in range(1, 1000):
        numbered = path.with_name(f"{path.name}.bak_{idx:02d}")
        if not numbered.exists():
            return numbered
    raise RuntimeError(f"Kein freier Backup-Ordner gefunden: {path.name}")
