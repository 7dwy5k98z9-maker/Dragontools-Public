from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> tuple[Path, str]:
    path = PACKAGE_ROOT / relative
    return path, path.read_text(encoding="utf-8")


def _decision_complexity(node: ast.AST) -> int:
    """Small AST-based cyclomatic approximation; formatting/data tables do not count."""
    decision_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.IfExp, ast.comprehension, ast.Match)
    score = 1
    for child in ast.walk(node):
        if isinstance(child, decision_nodes):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += max(0, len(child.values) - 1)
    return score


def test_release_validation_package_stays_cohesive_instead_of_line_bounded():
    path, source = _source("core/release_validation_package.py")
    tree = ast.parse(source, filename=str(path))
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    # This module owns package/release-text validation only. A long smoke-module
    # tuple is data, not another responsibility and therefore must not fail on LOC.
    assert len(functions) <= 8
    assert max(_decision_complexity(node) for node in functions) <= 16

    internal_imports = {
        str(node.module or "")
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and int(node.level or 0) > 0
    }
    assert internal_imports <= {
        "release_packaging",
        "release_validation_common",
        "release_validation_smoke_modules",
        "release_validation_privacy",
    }


def test_refactored_core_services_remain_qt_free():
    for relative in (
        "core/audio_video_match_models.py",
        "core/audio_sync_planner.py",
        "core/batch_preflight_storage.py",
        "rules/subtitle_rule_config.py",
        "core/audio_video_match_utils.py",
        "core/audio_video_frame_analysis.py",
        "core/audio_video_time_mapping.py",
        "core/audio_video_match_services.py",
        "core/movie_renamer_models.py",
        "core/movie_renamer_parsing.py",
        "core/movie_renamer_candidates.py",
        "core/movie_renamer_candidate_resolvers.py",
        "core/movie_renamer_candidate_mapping.py",
        "core/movie_renamer_candidate_scoring.py",
        "core/movie_renamer_candidate_order.py",
        "core/movie_renamer_episode_refresh.py",
        "core/release_validation_common.py",
        "core/release_validation_environment.py",
        "core/release_validation_package.py",
        "core/release_validation_privacy.py",
        "core/batch_preflight_formatting.py",
        "core/batch_preflight_decisions.py",
        "core/batch_preflight_rows.py",
        "core/batch_preflight_report.py",
        "core/media_library_classification.py",
        "core/media_library_scope.py",
        "core/media_library_query.py",
        "core/media_library_search_service.py",
        "core/media_analyzer.py",
        "core/media_analyzer_io.py",
        "core/media_analyzer_streams.py",
        "core/media_analyzer_video_streams.py",
        "core/media_analyzer_audio_streams.py",
        "core/media_analyzer_subtitle_streams.py",
        "core/move_journal.py",
        "core/move_journal_contracts.py",
        "core/move_journal_resume.py",
        "core/move_journal_storage.py",
        "core/move_journal_utils.py",
        "core/online_metadata_tvdb.py",
        "core/online_metadata_tvdb_resolver.py",
        "core/online_metadata_tvdb_suggestions.py",
        "core/online_metadata_tvdb_transport.py",
        "core/logger.py",
        "core/logger_paths.py",
        "core/logger_verbose.py",
        "core/logger_messages.py",
        "rules/audio_rule_basics.py",
        "rules/audio_rule_migration.py",
        "rules/audio_rule_repository.py",
        "rules/audio_transcode_policy.py",
        "rules/audio_selection.py",
        "rules/subtitle_plan_models.py",
        "rules/subtitle_selection.py",
        "rules/subtitle_keep_policy.py",
        "rules/subtitle_burn_policy.py",
        "rules/subtitle_storage.py",
        "core/paths.py",
        "core/path_syntax.py",
        "core/path_defaults.py",
        "core/online_metadata_common.py",
        "core/online_metadata_types.py",
        "core/online_metadata_config.py",
        "core/online_metadata_parsing.py",
        "core/online_metadata_cache_paths.py",
        "core/online_metadata_payload.py",
        "rules/move_rules.py",
        "rules/move_rule_config.py",
        "rules/move_series_detection.py",
        "rules/move_path_helpers.py",
        "rules/move_series_directories.py",
    ):
        path, source = _source(relative)
        tree = ast.parse(source, filename=str(path))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            str(node.module or "")
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert not any(name.startswith(("PyQt", "PySide")) for name in imports), relative


def test_audio_video_matcher_keeps_compatibility_facade():
    from dragontools.core import audio_video_matcher as facade
    from dragontools.core.audio_sync_planner import AudioSyncPlanner
    from dragontools.core.audio_video_match_models import CutRegion, TimeMappingResult

    assert facade.AudioSyncPlanner is AudioSyncPlanner
    assert facade.CutRegion is CutRegion
    assert facade.TimeMappingResult is TimeMappingResult


def test_subtitle_rules_keeps_migration_and_constant_facade():
    from dragontools.rules import subtitle_rules as facade
    from dragontools.rules.subtitle_rule_config import (
        DEFAULT_PREFERRED_SUBTITLE_FORMATS,
        migrate_subtitle_rules,
    )

    assert facade.migrate_subtitle_rules is migrate_subtitle_rules
    assert facade.DEFAULT_PREFERRED_SUBTITLE_FORMATS is DEFAULT_PREFERRED_SUBTITLE_FORMATS


def test_audio_rules_keeps_public_compatibility_facade():
    from dragontools.rules import audio_rules as facade
    from dragontools.rules.audio_rule_migration import migrate_audio_rules
    from dragontools.rules.audio_selection import choose_audio_streams
    from dragontools.rules.audio_transcode_policy import audio_requires_transcode

    assert facade.migrate_audio_rules is migrate_audio_rules
    assert facade.choose_audio_streams is choose_audio_streams
    assert facade.audio_requires_transcode is audio_requires_transcode


def test_round2_compatibility_facades():
    from dragontools.core import batch_preflight as batch_facade
    from dragontools.core import media_library_search as search_facade
    from dragontools.core import logger as logger_facade
    from dragontools.core.batch_preflight_rows import build_batch_preflight_rows
    from dragontools.core.batch_preflight_report import format_batch_preflight_report
    from dragontools.core.media_library_search_service import search_library
    from dragontools.core.logger_verbose import VerboseLogger
    from dragontools.core.logger_messages import DragonLoggerMessageMixin

    assert batch_facade.build_batch_preflight_rows is build_batch_preflight_rows
    assert batch_facade.format_batch_preflight_report is format_batch_preflight_report
    assert search_facade.search_library.__name__ == search_library.__name__
    assert logger_facade.VerboseLogger is VerboseLogger
    assert issubclass(logger_facade.DragonLogger, DragonLoggerMessageMixin)


def test_round2_gui_modules_are_composed_from_small_helpers():
    checks = {
        "gui/quality_tester_widget.py": ("QualityTesterWidget", "QualityTesterExecutionMixin"),
        "gui/convert_widget_override_dialog.py": ("ConvertWidgetOverrideDialogHelper", "ConvertOverrideGroupBuilderMixin"),
    }
    for relative, (class_name, base_name) in checks.items():
        path, source = _source(relative)
        tree = ast.parse(source, filename=str(path))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        base_names = {base.id for base in cls.bases if isinstance(base, ast.Name)}
        assert base_name in base_names, relative


def test_round3_compatibility_facades():
    from dragontools.core import media_analyzer as analyzer
    from dragontools.core import move_journal as journal
    from dragontools.core.online_metadata_tvdb import TheTvdbClient
    from dragontools.core.media_analyzer_streams import _build_video_streams
    from dragontools.core.move_journal_resume import build_move_resume_plan
    from dragontools.core.online_metadata_tvdb_resolver import TvdbResolverMixin

    assert analyzer._build_video_streams is _build_video_streams
    assert journal.build_move_resume_plan is build_move_resume_plan
    assert issubclass(TheTvdbClient, TvdbResolverMixin)


def test_block11_candidate_and_stream_facades_reexport_split_helpers():
    from dragontools.core import media_analyzer_streams as stream_facade
    from dragontools.core import movie_renamer_candidates as candidate_facade
    from dragontools.core.media_analyzer_video_streams import _build_video_streams
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    from dragontools.core.media_analyzer_subtitle_streams import _build_subtitle_streams
    from dragontools.core.movie_renamer_candidate_resolvers import _resolve_series_results
    from dragontools.core.movie_renamer_candidate_mapping import _series_candidate_from_result
    from dragontools.core.movie_renamer_candidate_order import _limit_candidates_with_provider_coverage

    assert stream_facade._build_video_streams is _build_video_streams
    assert stream_facade._build_audio_streams is _build_audio_streams
    assert stream_facade._build_subtitle_streams is _build_subtitle_streams
    assert candidate_facade._resolve_series_results is _resolve_series_results
    assert candidate_facade._series_candidate_from_result is _series_candidate_from_result
    assert candidate_facade._limit_candidates_with_provider_coverage is _limit_candidates_with_provider_coverage


def test_round3_gui_modules_are_composed_from_small_helpers():
    checks = {
        "gui/rules_audio_tab.py": ("_AudioTab", "AudioTabChannelRulesMixin"),
        "gui/convert_widget_layout.py": ("ConvertWidgetLayoutBuilder", "ConvertWidgetLayoutOptionsMixin"),
        "gui/convert_widget_file_queue.py": ("ConvertWidgetFileQueueHelper", "ConvertWidgetQueueAddMixin"),
    }
    for relative, (class_name, base_name) in checks.items():
        path, source = _source(relative)
        tree = ast.parse(source, filename=str(path))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        base_names = {base.id for base in cls.bases if isinstance(base, ast.Name)}
        assert base_name in base_names, relative


def test_round4_compatibility_facades():
    from dragontools.core import paths as paths_facade
    from dragontools.core import online_metadata_common as metadata_facade
    from dragontools.core.path_syntax import normalize_user_path
    from dragontools.core.path_defaults import default_target_path
    from dragontools.core.online_metadata_types import OnlineMetadataConfig
    from dragontools.core.online_metadata_parsing import parse_series_query
    from dragontools.rules import move_rules as move_facade
    from dragontools.rules.move_series_detection import parse_series_match_details

    assert paths_facade.normalize_user_path is normalize_user_path
    assert paths_facade.default_target_path is default_target_path
    assert metadata_facade.OnlineMetadataConfig is OnlineMetadataConfig
    assert metadata_facade.parse_series_query is parse_series_query
    assert move_facade.parse_series_match_details is parse_series_match_details


def test_round4_gui_facades_reexport_split_components_without_importing_qt():
    checks = {
        "gui/preflight_widgets.py": {
            "preflight_series_widget": {"SeriesGroupWidget"},
            "preflight_film_widget": {"FilmWidget"},
        },
        "gui/subtitle_widget.py": {
            "subtitle_widget_workers": {"_SubWorker", "_ExtractWorker", "_InjectWorker", "_ConvertWorker"},
            "subtitle_widget_files": {"_FileDropList", "_parse_exts"},
        },
    }
    for relative, expected_by_module in checks.items():
        path, source = _source(relative)
        tree = ast.parse(source, filename=str(path))
        imported = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                module = str(node.module or "")
                imported[module] = {alias.name for alias in node.names}
        for module_suffix, expected_names in expected_by_module.items():
            matches = [names for module, names in imported.items() if module.endswith(module_suffix)]
            assert matches, f"{relative}: Import aus {module_suffix} fehlt"
            assert expected_names <= matches[0]
