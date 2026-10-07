"""Persist HDR recovery artifacts before permitting intermediate cleanup."""
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from .hdrplus_runtime_models import HDRPlusPipelineOutcome


def _create_staging(source, output):
    archive_root = staging = None
    root_errors = []
    roots: list[Path] = []
    for candidate_root in (source.parent / "Archiv", output.parent / "Archiv"):
        try:
            key = candidate_root.resolve(strict=False)
        except OSError:
            key = candidate_root.absolute()
        if any(existing == key for existing in roots):
            continue
        roots.append(key)

    for candidate_root in roots:
        try:
            candidate_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".hdr10plus_failed_", dir=candidate_root))
            archive_root = candidate_root
            break
        except OSError as exc:
            root_errors.append(f"{candidate_root}: {exc}")

    return archive_root, staging, root_errors


def _artifact_candidates(paths, output, extra_paths, include_output):
    candidates: list[tuple[Path, str]] = [
        (paths.encoded_hevc, "encoded.hevc"),
        (paths.stream_donor, "streams.mkv"),
        (paths.injected_hevc, "injected.hevc"),
        (paths.metadata_json, "hdr10plus.json"),
        (paths.metadata_fallback_hevc, "source_metadata.hevc"),
    ]
    if include_output:
        candidates.insert(0, (output, f"failed_output{output.suffix}"))
    for extra in extra_paths:
        if extra is not None:
            candidates.append((Path(extra), f"candidate{Path(extra).suffix}"))
    # Include prepared tracks and verification evidence as well as the main
    # media artifacts, so a complete archive really permits workspace cleanup.
    candidates.extend((p, p.name) for p in paths.root.rglob('*') if p.is_file())
    return candidates


def preserve_hdrplus_failure(context, paths, stage, *, extra_paths=(), force_preserve_output=False, include_output=True, log):
    output = Path(context.output_path)
    source = Path(context.input_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    staging: Path | None = None
    copied: list[Path] = []
    archive_root: Path | None = None
    root_errors: list[str] = []
    try:
        # Bevorzugt wie bisher das Archiv neben der Quelle. Falls dieser
        # Pfad schreibgeschützt ist (z. B. Read-only Import-Mount), fällt
        # DragonTools auf das Output-Verzeichnis zurück. Dort konnte der
        # Pipeline-Tempordner bereits erfolgreich angelegt werden, sodass
        # die Chance hoch ist, die teuren Encode-/JSON-Artefakte trotzdem
        # retten zu können.
        archive_root, staging, root_errors = _create_staging(source, output)

        if archive_root is None or staging is None:
            raise OSError("Kein beschreibbares HDR10+-Archivverzeichnis: " + "; ".join(root_errors))

        final_dir = archive_root / f"{output.stem or source.stem}__HDR10PLUS_FAILED__{stamp}"

        candidates = _artifact_candidates(paths, output, extra_paths, include_output)

        seen_sources: set[str] = set()
        for source_path, archive_name in candidates:
            try:
                key = str(source_path.resolve(strict=False))
            except OSError:
                key = str(source_path.absolute())
            if key in seen_sources or not source_path.is_file():
                continue
            seen_sources.add(key)
            target = staging / archive_name
            # Namenskollisionen (z.B. mehrere candidate.*) deterministisch vermeiden.
            if target.exists():
                target = staging / f"{target.stem}_{len(copied) + 1}{target.suffix}"
            shutil.copy2(source_path, target)
            copied.append(target)

        status = {
            "stage": stage,
            "input": str(source),
            "output": str(output),
            "container": context.container,
            "generate_hdr10plus": bool(context.generate_hdr10plus),
            "artifacts": [p.name for p in copied],
        }
        (staging / "recovery.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        copied.append(staging / "recovery.json")

        os.replace(staging, final_dir)
        if paths.workspace is not None:
            paths.workspace.mark_persisted()
        archived_paths = tuple(str(final_dir / p.name) for p in copied)
        log(f"HDR10+: Fehlerartefakte gesichert -> {final_dir}", "warn")
        return HDRPlusPipelineOutcome(
            False,
            failure_archive_path=str(final_dir),
            failure_artifact_paths=archived_paths,
            preserve_failed_output=bool(force_preserve_output),
        )
    except Exception as exc:
        log(f"⚠️ HDR10+: Fehlerartefakte konnten nicht vollständig archiviert werden: {exc}", "warn")
        persistent: tuple[str, ...] = tuple(str(p) for p in paths.root.rglob("*") if p.is_file())
        if staging is not None and staging.exists():
            # Staging liegt absichtlich bereits ausserhalb des kurzlebigen
            # Pipeline-Tempdirs. Bei einem Commit-/Copy-Fehler wird es nicht
            # gelöscht: teilweise kopierte Diagnoseartefakte sind wertvoller
            # als ein "sauberes" Cleanup mit Datenverlust.
            persistent += tuple(str(p) for p in staging.iterdir() if p.is_file())
        return HDRPlusPipelineOutcome(
            False,
            failure_artifact_paths=persistent,
            preserve_failed_output=bool(force_preserve_output or output.exists()),
        )
