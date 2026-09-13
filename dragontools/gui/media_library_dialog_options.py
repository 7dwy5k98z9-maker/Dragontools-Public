# -*- coding: utf-8 -*-
"""Search choices displayed by the media-library dialog."""
from __future__ import annotations

SEARCH_MODES = [
    ("Alle Einträge", "all"),
    ("Audio", "audio"),
    ("HDR / Dynamikumfang", "dynamic_range"),
    ("Auflösung", "resolution"),
    ("Video-Codec", "video_codec"),
    ("Dateigröße", "file_size"),
    ("Laufzeitprüfung", "duration"),
    ("Abweichungen", "deviation"),
    ("NFO / NFO-Prüfung", "nfo"),
    ("Metadaten", "metadata"),
]

SEARCH_SCOPES = [
    ("Alle Bereiche", "all"),
    ("Filme", "movies"),
    ("Anime", "anime"),
    ("TV", "tv"),
    ("Serien gesamt", "series"),
    ("Sonstige", "other"),
]

SEARCH_ITEM_TYPES = [
    ("Alle Typen", "all"),
    ("Nur Videodateien", "videos"),
    ("Filme", "movies"),
    ("Serien", "series"),
    ("Staffeln", "seasons"),
    ("Episoden", "episodes"),
    ("Ordner", "folders"),
]

SEARCH_OPTIONS = {
    "all": [("Alle Einträge", "all")],
    "audio": [
        ("Mit deutscher Audiospur", "has_german_audio"),
        ("Ohne deutsche Audiospur", "no_german_audio"),
        ("Mit mehreren Audiospuren", "multiple_audio"),
        ("Stereo / 2.0", "audio_stereo"),
        ("5.1 / 6 Kanäle", "audio_51"),
        ("7.1 / 8+ Kanäle", "audio_71"),
        ("AAC", "audio_codec_aac"),
        ("AC3", "audio_codec_ac3"),
        ("EAC3", "audio_codec_eac3"),
        ("TrueHD", "audio_codec_truehd"),
        ("DTS", "audio_codec_dts"),
        ("FLAC", "audio_codec_flac"),
        ("Audio-Codec unbekannt", "audio_codec_unknown"),
    ],
    "dynamic_range": [
        ("SDR", "sdr"),
        ("HDR", "hdr"),
        ("HDR10+", "hdr10plus"),
        ("Dolby Vision", "dv"),
        ("HDR/SDR unbekannt", "dynamic_range_unknown"),
    ],
    "resolution": [
        ("Kleiner als HD", "resolution_sd"),
        ("HD / 720p", "resolution_hd"),
        ("Full HD / 1080p", "resolution_fhd"),
        ("QHD / 1440p", "resolution_qhd"),
        ("4K / UHD", "resolution_uhd"),
        ("Auflösung unbekannt", "resolution_unknown"),
    ],
    "video_codec": [
        ("H.264 / AVC", "h264"),
        ("H.265 / HEVC", "hevc"),
        ("AV1", "av1"),
        ("Video-Codec unbekannt", "video_codec_unknown"),
    ],
    "file_size": [
        ("Kleiner als 1 GiB", "size_under_1gb"),
        ("1 bis unter 2 GiB", "size_1_2gb"),
        ("2 bis unter 5 GiB", "size_2_5gb"),
        ("5 bis unter 10 GiB", "size_5_10gb"),
        ("10 bis unter 20 GiB", "size_10_20gb"),
        ("20 GiB oder größer", "size_over_20gb"),
        ("Dateigröße unbekannt", "size_unknown"),
    ],
    "duration": [
        ("Länger als 5 Stunden", "duration_over_5h"),
        ("Kürzer als 1 Minute", "duration_under_1min"),
        ("Laufzeit unbekannt", "duration_unknown"),
    ],
    "deviation": [
        ("Deutsche Audiospur", "deviation_german_audio"),
        ("Auflösung", "deviation_resolution"),
        ("Video-Codec", "deviation_video_codec"),
        ("HDR / SDR", "deviation_dynamic_range"),
        ("Audio-Codec", "deviation_audio_codec"),
        ("Audiokanäle", "deviation_audio_channels"),
        ("Anzahl Audiospuren", "deviation_audio_track_count"),
    ],
    "nfo": [
        ("NFO vorhanden", "nfo_present"),
        ("NFO fehlt", "nfo_missing"),
        ("NFO-Speicherpfad nicht erreichbar", "nfo_unreachable"),
        ("NFO ungültig / nicht lesbar", "nfo_invalid"),
        ("NFO noch nicht geprüft", "nfo_unknown"),
        ("NFO mit Abweichungen", "nfo_has_issues"),
        ("NFO mit Fehlern", "nfo_errors"),
        ("NFO mit Warnungen", "nfo_warnings"),
        ("Provider-ID stimmt nicht", "nfo_provider_mismatch"),
    ],
    "metadata": [
        ("Unvollständige / fehlende Metadaten", "metadata_incomplete"),
        ("Videoeigenschaften unbekannt", "video_properties_unknown"),
        ("Doppelte aktive SxxExx", "duplicate_active_sxxexx"),
    ],
}
