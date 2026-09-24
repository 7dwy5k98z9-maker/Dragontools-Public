# -*- coding: utf-8 -*-
"""Transparent protection for sensitive QSettings values on Windows.

Dragon Tools stores API keys/tokens encrypted with Windows DPAPI when the
backing store is a real PyQt6 QSettings instance. Legacy plaintext values stay
readable and are migrated automatically the next time the settings are saved.
Tests and non-Windows helper stores intentionally keep their previous behavior.
"""
from __future__ import annotations

import base64
import ctypes
import logging
import os
from ctypes import wintypes

_LOG = logging.getLogger(__name__)
_PREFIX = "dpapi:v1:"


class SecretProtectionError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, object]:
    if not data:
        return _DATA_BLOB(0, None), None
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi_protect(text: str) -> str:
    if os.name != "nt":
        return text
    raw = text.encode("utf-8")
    in_blob, in_buffer = _blob(raw)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    _ = in_buffer  # keep input memory alive for the API call
    if not ok:
        raise SecretProtectionError(f"CryptProtectData fehlgeschlagen (WinError {ctypes.get_last_error()}).")
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
    return _PREFIX + base64.b64encode(protected).decode("ascii")


def _dpapi_unprotect(stored: str) -> str:
    if not stored.startswith(_PREFIX):
        return stored
    if os.name != "nt":
        raise SecretProtectionError("DPAPI-Wert kann nur unter Windows entschlüsselt werden.")
    try:
        protected = base64.b64decode(stored[len(_PREFIX):], validate=True)
    except Exception as exc:
        raise SecretProtectionError("Ungültiger DPAPI-Secretwert.") from exc
    in_blob, in_buffer = _blob(protected)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    _ = in_buffer
    if not ok:
        raise SecretProtectionError(f"CryptUnprotectData fehlgeschlagen (WinError {ctypes.get_last_error()}).")
    try:
        raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretProtectionError("Entschlüsselter DPAPI-Wert ist kein gültiges UTF-8.") from exc


def _is_real_qsettings(settings) -> bool:
    cls = type(settings)
    return cls.__name__ == "QSettings" and str(cls.__module__).startswith("PyQt6.")


def protect_secret_for_storage(value: str, *, enabled: bool) -> str:
    text = str(value or "")
    if not text or not enabled:
        return text
    return _dpapi_protect(text)


def decode_secret_from_storage(value: str) -> str:
    text = str(value or "")
    if not text.startswith(_PREFIX):
        return text
    return _dpapi_unprotect(text)


def read_secret(settings, key: str, default: str = "") -> str:
    try:
        raw = settings.value(key, default, type=str)
    except TypeError:
        # Lightweight QSettings-compatible stores used by tests and headless
        # helpers do not necessarily implement Qt's optional ``type=`` keyword
        # or a default-value positional argument.
        raw = settings.value(key)
        if raw is None:
            raw = default
    text = str(raw or "")
    if not text.startswith(_PREFIX):
        return text
    try:
        return decode_secret_from_storage(text)
    except SecretProtectionError:
        _LOG.warning("Geschützte Einstellung konnte nicht entschlüsselt werden: %s", key, exc_info=True)
        return str(default or "")


def write_secret(settings, key: str, value: str) -> None:
    text = str(value or "")
    protect = os.name == "nt" and _is_real_qsettings(settings)
    try:
        stored = protect_secret_for_storage(text, enabled=protect)
    except SecretProtectionError:
        # Do not silently fall back to plaintext on Windows if DPAPI itself fails.
        _LOG.exception("Einstellung konnte nicht sicher gespeichert werden: %s", key)
        raise
    settings.setValue(key, stored)


def is_protected_secret_value(value: object) -> bool:
    return str(value or "").startswith(_PREFIX)
