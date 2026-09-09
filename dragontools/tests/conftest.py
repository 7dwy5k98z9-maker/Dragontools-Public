from __future__ import annotations

import importlib.util

import pytest

from dragontools.tests.ci_requirements import (
    env_flag,
    external_media_environment,
    missing_qt_dependencies,
)


def pytest_addoption(parser):
    """Register qt_api also in deliberate headless Core runs.

    pytest-qt registers this ini option itself when installed. In a reduced
    headless environment we register only the configuration key; Qt-dependent
    tests are still skipped explicitly and no fake qtbot fixture is provided.
    """
    if importlib.util.find_spec("pytestqt") is None:
        parser.addini("qt_api", "Qt backend used by pytest-qt", default="pyqt6")


def pytest_sessionstart(session):
    """Turn optional local skips into hard CI requirements when requested."""
    if env_flag("DRAGONTOOLS_REQUIRE_QT_TESTS"):
        missing = missing_qt_dependencies()
        if missing:
            raise pytest.UsageError(
                "DRAGONTOOLS_REQUIRE_QT_TESTS=1, aber folgende Qt-Testabhängigkeiten "
                f"fehlen: {', '.join(missing)}"
            )

    if env_flag("DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION"):
        missing = external_media_environment().missing
        if missing:
            raise pytest.UsageError(
                "DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION=1, aber folgende reale "
                f"Tool-Voraussetzungen fehlen: {', '.join(missing)}"
            )


def pytest_collection_modifyitems(config, items):
    """Skip only the explicit real DV/HDR suite when its environment is absent."""
    media_env = external_media_environment()
    if not media_env.missing:
        return
    reason = "Reale DV/HDR-Integration nicht konfiguriert: " + ", ".join(media_env.missing)
    marker = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker("dv_hdr_integration") is not None:
            item.add_marker(marker)
