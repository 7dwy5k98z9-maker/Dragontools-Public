"""Own source-rendered caches until the verified video has been installed."""
from pathlib import Path
import re
import shutil
import uuid

from .postprocess_models import PreparedTrickplay, PostProcessRunResult
from .trickplay_commit import commit_generated_root, commit_missing_variant
from .trickplay_concurrency import trickplay_target_lock
from .trickplay_paths import normalize_trickplay_conflict_mode, trickplay_root_for_video, trickplay_sprite_dir_for_video, trickplay_result_status


def _identity(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino


def _owned(prepared):
    stage, target = Path(prepared.staging_root), Path(prepared.target_root)
    pattern = re.escape('.' + target.stem + '.__source_trickplay__') + r'[0-9a-f]{32}\.trickplay'
    return (stage.parent.resolve() == target.parent.resolve()
        and re.fullmatch(pattern, stage.name) is not None
        and not stage.is_symlink() and stage.is_dir()
        and _identity(stage) == prepared.identity)


def discard_source_trickplay(result):
    prepared = getattr(result, 'prepared_trickplay', None)
    if prepared is None:
        return
    try:
        if _owned(prepared):
            shutil.rmtree(prepared.staging_root)
    except OSError:
        pass


def prepare_source_trickplay(generator, *, source, output, settings):
    output = Path(output)
    temporary_video = output.with_name(f'.{output.stem}.__source_trickplay__{uuid.uuid4().hex}{output.suffix}')
    root = generator.generate(source, settings, target_video_path=temporary_video)
    if root is None:
        return PostProcessRunResult([], [{'kind':'trickplay','status':'error','path':'',
            'message':'Quellbasierte Vorschaubilder konnten nicht vorbereitet werden.'}])
    prepared = PreparedTrickplay(str(root), str(trickplay_root_for_video(output)), settings, _identity(root))
    return PostProcessRunResult([], [{'kind':'trickplay','status':'prepared','path':'','message':''}], prepared)


def install_source_trickplay(result, *, output, worker, info, warn):
    prepared = result.prepared_trickplay
    try:
        output = Path(output)
        final_root = trickplay_root_for_video(output)
        if not output.is_file() or final_root.resolve() != Path(prepared.target_root).resolve():
            raise ValueError('Vorschaubilder benötigen die installierte Ziel-Mediendatei.')
        if not _owned(prepared):
            raise ValueError('Vorbereiteter Vorschaubild-Ordner wurde ausgetauscht.')
        abort = lambda: bool(getattr(worker, 'abort_requested', False))
        with trickplay_target_lock(final_root, abort_check=abort):
            if abort():
                raise RuntimeError('Trickplay abgebrochen.')
            settings = prepared.settings
            final_sprite = trickplay_sprite_dir_for_video(output, settings)
            partial_root = Path(prepared.staging_root)
            mode = normalize_trickplay_conflict_mode(settings)
            status = trickplay_result_status(mode, root_exists=final_root.exists(), variant_exists=final_sprite.exists())
            if mode == 'skip' and final_root.exists():
                root = commit_missing_variant(partial_root=partial_root,
                    partial_sprite_dir=partial_root/final_sprite.name, final_root=final_root,
                    final_sprite_dir=final_sprite, info=info, warn=warn)
            else:
                root = commit_generated_root(partial_root=partial_root, final_root=final_root,
                    final_sprite_dir=final_sprite, conflict_mode=mode, info=info, warn=warn)
        if root is None:
            raise RuntimeError('Vorbereitete Vorschaubilder konnten nicht installiert werden.')
        return PostProcessRunResult([str(root)], [{'kind':'trickplay','status':status,'path':str(root),'message':''}])
    except (OSError, RuntimeError, ValueError) as exc:
        warn(f'Trickplay konnte nicht installiert werden: {exc}')
        return PostProcessRunResult([], [{'kind':'trickplay','status':'error','path':'','message':str(exc)}])
    finally:
        discard_source_trickplay(result)
