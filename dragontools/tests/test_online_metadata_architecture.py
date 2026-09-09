from __future__ import annotations

import ast
from pathlib import Path

import dragontools.core.online_metadata as metadata


def test_online_metadata_facade_preserves_public_api() -> None:
    expected = {
        "METADATA_PROVIDERS",
        "METADATA_SINGLE_PROVIDERS",
        "TMDB_API_BASE",
        "TMDB_TIMEOUT_S",
        "TVDB_API_BASE",
        "TVDB_TIMEOUT_S",
        "OnlineMetadataError",
        "OnlineMetadataAuthError",
        "OnlineMetadataConfig",
        "ParsedMovieQuery",
        "ParsedSeriesQuery",
        "MovieMetadataSuggestion",
        "SeriesMetadataSuggestion",
        "EpisodeMetadataSuggestion",
        "metadata_series_folder_title",
        "config_from_settings",
        "metadata_provider_configured",
        "parse_movie_query",
        "parse_series_query",
        "clean_tmdb_collection_name",
        "default_metadata_cache_dir",
        "clear_default_metadata_cache",
        "default_episode_title",
        "normalize_episode_metadata_title",
        "TmdbClient",
        "TheTvdbClient",
        "CompositeMetadataClient",
        "client_from_settings",
        "client_from_config",
        "client_from_settings_for",
        "suggest_movie_metadata_for_file",
        "suggest_series_metadata_for_name",
        "suggest_episode_metadata_for_file",
        "format_movie_suggestion",
        "format_series_suggestion",
    }
    assert set(metadata.__all__) == expected
    for name in expected:
        assert hasattr(metadata, name), name


def test_online_metadata_facade_contains_no_business_logic() -> None:
    source = Path(metadata.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def test_online_metadata_implementation_is_split_by_responsibility() -> None:
    core = Path(metadata.__file__).parent
    expected_modules = {
        "online_metadata_common.py",
        "online_metadata_types.py",
        "online_metadata_config.py",
        "online_metadata_parsing.py",
        "online_metadata_cache_paths.py",
        "online_metadata_payload.py",
        "online_metadata_tmdb.py",
        "online_metadata_tmdb_resolver.py",
        "online_metadata_tmdb_suggestions.py",
        "online_metadata_tmdb_transport.py",
        "online_metadata_tvdb.py",
        "online_metadata_tvdb_helpers.py",
        "online_metadata_service.py",
    }
    modules = {path.name: path for path in core.glob("online_metadata_*.py")}
    assert expected_modules <= set(modules)
    assert len(Path(metadata.__file__).read_text(encoding="utf-8").splitlines()) < 120
    assert max(len(modules[name].read_text(encoding="utf-8").splitlines()) for name in expected_modules) < 550


def test_provider_clients_never_fallback_to_source_stem_as_episode_title() -> None:
    core = Path(metadata.__file__).parent
    provider_implementations = (
        "online_metadata_tmdb_resolver.py",
        "online_metadata_tmdb_suggestions.py",
        "online_metadata_tvdb_resolver.py",
    )
    for name in provider_implementations:
        source = (core / name).read_text(encoding="utf-8")
        assert 'or Path(path).stem' not in source
        assert "normalize_episode_metadata_title" in source


def test_tmdb_client_is_a_thin_composition_facade() -> None:
    core = Path(metadata.__file__).parent
    facade = core / "online_metadata_tmdb.py"
    resolver = core / "online_metadata_tmdb_resolver.py"
    suggestions = core / "online_metadata_tmdb_suggestions.py"
    transport = core / "online_metadata_tmdb_transport.py"

    assert len(facade.read_text(encoding="utf-8").splitlines()) < 100
    assert len(resolver.read_text(encoding="utf-8").splitlines()) < 400
    assert len(suggestions.read_text(encoding="utf-8").splitlines()) < 260
    assert len(transport.read_text(encoding="utf-8").splitlines()) < 120

    tree = ast.parse(facade.read_text(encoding="utf-8"))
    client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TmdbClient"
    )
    methods = [node.name for node in client.body if isinstance(node, ast.FunctionDef)]
    assert methods == ["__init__"]
