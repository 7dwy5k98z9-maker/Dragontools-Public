from __future__ import annotations


def test_audit_log_writes_event_to_configured_log_root(tmp_path):
    from dragontools.core.audit_log import append_audit_event

    path = append_audit_event("Profil gespeichert", "Testprofil", log_root=tmp_path)

    assert path is not None
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Profil gespeichert" in text
    assert "Testprofil" in text


def test_audit_summary_masks_sensitive_values():
    from dragontools.core.audit_log import summarize_changes
    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY

    count, text = summarize_changes(
        {SET_KEY_METADATA_TMDB_API_KEY: "alt"},
        {SET_KEY_METADATA_TMDB_API_KEY: "neu"},
    )

    assert count == 1
    assert "metadata/tmdb/api_key" in text
    assert "alt" not in text
    assert "neu" not in text
    assert "*** -> ***" in text
