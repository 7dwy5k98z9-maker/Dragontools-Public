"""Prepared NFOs carry an identity; cleanup cannot consume media sources."""
from pathlib import Path
from defusedxml import ElementTree as SafeET
from ..core.media_library_nfo_parser import MAX_NFO_BYTES
from .hdr_metadata_file_ownership import metadata_output_conflicts_with_sources


def file_identity(path):
    stat=Path(path).stat()
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns


def validate_prepared_nfo(prepared,video, *, require_target=False):
    video=Path(video);stage=Path(prepared.staging_path);target=video.with_suffix('.nfo')
    if not video.is_file():
        raise ValueError('NFO-Veröffentlichung benötigt eine installierte Mediendatei.')
    if require_target and Path(prepared.target_path).resolve() != target.resolve():
        raise ValueError('Vorbereitete NFO gehört zu einer anderen Ziel-Mediendatei.')
    if stage.is_symlink() or metadata_output_conflicts_with_sources(stage,video,target):
        raise ValueError('NFO-Vorbereitung verweist auf eine Quelle oder die finale NFO.')
    if prepared.staging_identity is not None and file_identity(stage)!=prepared.staging_identity:
        raise ValueError('Vorbereitete NFO wurde nach der Erstellung ausgetauscht.')
    with stage.open('rb') as handle:
        body=handle.read(MAX_NFO_BYTES+1)
    if len(body)>MAX_NFO_BYTES:
        raise ValueError('Vorbereitete NFO überschreitet das Größenlimit.')
    root=SafeET.fromstring(body,forbid_dtd=True,forbid_entities=True,forbid_external=True)
    if root.tag not in {'movie','episodedetails'}:
        raise ValueError('Vorbereitung enthält keine Film-/Episoden-NFO.')


def discard_owned_nfo(prepared):
    if prepared is None or not prepared.staging_path or prepared.staging_identity is None:
        return
    path=Path(prepared.staging_path)
    try:
        target = Path(prepared.target_path)
        # Only the exclusive preparation namespace is eligible for cleanup,
        # even if a caller supplies an identity belonging to a media source.
        owned_name = path.name.startswith('.') and '.__nfo_during__' in path.name and path.suffix == '.nfo'
        if owned_name and path != target and not path.is_symlink() and file_identity(path)==prepared.staging_identity:
            path.unlink()
    except OSError:
        pass
