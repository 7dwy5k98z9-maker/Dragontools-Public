# -*- coding: utf-8 -*-
"""Seitenbasierte Änderungshistorie ohne überladenes Button-Raster."""
from __future__ import annotations

from html import escape
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..core.changelog import ChangelogDocument, ChangelogSection, load_changelog, paginate_blocks
from ..core.paths import EXE_DIR, BASE
from ..core.settings import APP_VERSION
from .ui_helpers import install_persistent_window_geometry


_CHANGELOG_FILES = {
    "v9": (("CHANGELOG.json", "CHANGELOG.txt"), f"Dragon Tools V{APP_VERSION}"),
    "v8": (("CHANGELOGV8.txt",), "Dragon Tools V8 Legacy"),
    "v7": (("CHANGELOGV7.txt",), "Dragon Tools V7 und älter"),
}

_SECTION_ICONS = {
    "Überblick": "📋",
    "V9.8": "🛡️",
    "V9.7": "🚀",
    "V9.5": "📌",
    "Release": "📦",
    "Dokumentation": "📚",
    "Externe Tools": "🛠️",
    "Konverter": "🎬",
    "HDR": "🌈",
    "Audio": "🔊",
    "Untertitel": "💬",
    "Medienanalyse": "🔎",
    "Queue": "📊",
    "Preflight": "✅",
    "Online-Metadaten": "🌐",
    "Jellyfin": "🖼️",
    "Audio-Video-Matcher": "🎧",
    "Qualitätstester": "🧪",
    "ISO": "💿",
    "Regeln": "⚙️",
    "Logging": "📝",
    "GUI": "🎨",
    "Tests": "✅",
    "Mediathek": "🗄️",
}


def _find_changelog(version_key: str = "v9") -> str | None:
    names, _ = _CHANGELOG_FILES.get(version_key, _CHANGELOG_FILES["v9"])
    for name in names:
        for root in (EXE_DIR, BASE):
            for folder in ("Aenderungshistorie", "Änderungshistorie", "."):
                candidate = root / folder / name
                if candidate.exists():
                    return str(candidate)
    return None


def _changelog_title(version_key: str) -> str:
    _, label = _CHANGELOG_FILES.get(version_key, _CHANGELOG_FILES["v9"])
    return f"Änderungshistorie – {label}"


def _icon_for_section(section: ChangelogSection) -> str:
    if section.icon and section.icon != "📌":
        return section.icon
    for prefix, icon in _SECTION_ICONS.items():
        if section.title.startswith(prefix) or prefix in section.title:
            return icon
    return "📌"


def _block_to_html(block: str) -> str:
    lines = str(block or "").splitlines()
    if not lines:
        return ""

    first = lines[0].strip()
    numbered = bool(re.match(r"^(?:V9\.\d+-\d+|\d{1,2}[.)])\s*", first))
    html: list[str] = []
    start = 0
    if numbered:
        html.append(f"<h3>{escape(first)}</h3>")
        start = 1

    bullets: list[str] = []
    paragraphs: list[str] = []
    for raw in lines[start:]:
        text = raw.strip()
        if not text:
            continue
        if text.startswith("-"):
            bullets.append(text[1:].strip())
        else:
            paragraphs.append(text)

    if paragraphs:
        html.append("<p>" + "<br>".join(escape(item) for item in paragraphs) + "</p>")
    if bullets:
        html.append("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in bullets) + "</ul>")
    if not numbered and not paragraphs and not bullets:
        html.append(f"<p>{escape(first)}</p>")
    elif not numbered and first and first not in paragraphs:
        # Der erste Text ist bei normalen Blöcken Teil des Absatzes.
        body = [first, *paragraphs]
        html = ["<p>" + "<br>".join(escape(item) for item in body) + "</p>"]
        if bullets:
            html.append("<ul>" + "".join(f"<li>{escape(item)}</li>" for item in bullets) + "</ul>")
    return "".join(html)


def _page_html(section: ChangelogSection, blocks: tuple[str, ...]) -> str:
    body = "".join(_block_to_html(block) for block in blocks)
    return f"""
    <html><head><style>
      body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; color: #202124; margin: 6px 12px; }}
      h3 {{ font-size: 11.5pt; color: #0b57d0; margin: 8px 0 4px 0; }}
      p {{ margin: 4px 0 8px 0; line-height: 1.18; }}
      ul {{ margin: 2px 0 8px 20px; padding: 0; }}
      li {{ margin: 2px 0; line-height: 1.16; }}
    </style></head><body>{body}</body></html>
    """


class ChangelogDialog(QDialog):
    def __init__(self, parent=None, version_key: str = "v9"):
        super().__init__(parent)
        self._version_key = version_key if version_key in _CHANGELOG_FILES else "v9"
        self._document: ChangelogDocument | None = None
        self._section_pages: list[tuple[tuple[str, ...], ...]] = []
        self._section_index = 0
        self._page_index = 0

        self.setWindowTitle(_changelog_title(self._version_key))
        self.resize(1080, 720)
        self.setMinimumSize(940, 650)
        self._init_ui()
        self._load()
        install_persistent_window_geometry(self, f"changelog_dialog/{self._version_key}")

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("Bereich:"))
        self.section_combo = QComboBox()
        self.section_combo.setMinimumWidth(620)
        self.section_combo.currentIndexChanged.connect(self._section_selected)
        top.addWidget(self.section_combo, 1)

        for label, key in (("V9", "v9"), ("Legacy V8", "v8"), ("Legacy V7", "v7")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, k=key: self._load(k))
            top.addWidget(btn)
        root.addLayout(top)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#d7d7d7;")
        root.addWidget(line)

        header = QHBoxLayout()
        self.section_title = QLabel("")
        self.section_title.setStyleSheet("font-size:17px;font-weight:600;padding:2px 4px;")
        self.section_title.setWordWrap(True)
        header.addWidget(self.section_title, 1)
        root.addLayout(header)

        self.text_view = QTextBrowser()
        self.text_view.setOpenExternalLinks(False)
        self.text_view.setFrameShape(QFrame.Shape.StyledPanel)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setStyleSheet("QTextBrowser { background:#ffffff; border:1px solid #d9d9d9; border-radius:6px; }")
        root.addWidget(self.text_view, 1)

        nav = QHBoxLayout()
        self.prev_section_btn = QPushButton("⏮ Bereich")
        self.prev_section_btn.clicked.connect(self._prev_section)
        self.prev_page_btn = QPushButton("◀ Seite")
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.page_label = QLabel("")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("color:#666;font-weight:500;")
        self.next_page_btn = QPushButton("Seite ▶")
        self.next_page_btn.clicked.connect(self._next_page)
        self.next_section_btn = QPushButton("Bereich ⏭")
        self.next_section_btn.clicked.connect(self._next_section)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("background:#0078d7;color:white;border-radius:4px;padding:5px 16px;")

        nav.addWidget(self.prev_section_btn)
        nav.addWidget(self.prev_page_btn)
        nav.addWidget(self.page_label, 1)
        nav.addWidget(self.next_page_btn)
        nav.addWidget(self.next_section_btn)
        nav.addSpacing(10)
        nav.addWidget(close_btn)
        root.addLayout(nav)

    def _load(self, version_key: str | None = None) -> None:
        if version_key is not None:
            self._version_key = version_key if version_key in _CHANGELOG_FILES else "v9"
        self.setWindowTitle(_changelog_title(self._version_key))
        path = _find_changelog(self._version_key)
        if not path:
            names, _ = _CHANGELOG_FILES[self._version_key]
            self._show_error(f"Keine Änderungshistorie gefunden. Erwartet: {', '.join(names)}")
            return

        try:
            doc = load_changelog(path, title=_changelog_title(self._version_key))
        except Exception as exc:
            self._show_error(f"Änderungshistorie konnte nicht geladen werden:\n{exc}")
            return

        self._document = doc
        self._section_pages = [paginate_blocks(section.blocks) for section in doc.sections]
        self._section_index = 0
        self._page_index = 0

        self.section_combo.blockSignals(True)
        self.section_combo.clear()
        for section in doc.sections:
            icon = _icon_for_section(section)
            self.section_combo.addItem(f"{icon}  {section.title}")
        self.section_combo.setCurrentIndex(0)
        self.section_combo.blockSignals(False)
        self._show_current()

    def _show_error(self, message: str) -> None:
        self._document = None
        self._section_pages = []
        self.section_combo.clear()
        self.section_title.setText("Änderungshistorie")
        self.text_view.setPlainText(message)
        self.page_label.setText("")
        for button in (self.prev_section_btn, self.prev_page_btn, self.next_page_btn, self.next_section_btn):
            button.setEnabled(False)

    def _section_selected(self, index: int) -> None:
        if self._document is None or index < 0 or index >= len(self._document.sections):
            return
        self._section_index = index
        self._page_index = 0
        self._show_current()

    def _show_current(self) -> None:
        if self._document is None or not self._document.sections:
            return
        section = self._document.sections[self._section_index]
        pages = self._section_pages[self._section_index]
        self._page_index = max(0, min(self._page_index, len(pages) - 1))
        icon = _icon_for_section(section)
        self.section_title.setText(f"{icon}  {section.title}")
        self.text_view.setHtml(_page_html(section, pages[self._page_index]))
        self.text_view.verticalScrollBar().setValue(0)

        section_no = self._section_index + 1
        section_total = len(self._document.sections)
        page_no = self._page_index + 1
        page_total = len(pages)
        self.page_label.setText(
            f"Bereich {section_no} von {section_total}  ·  Seite {page_no} von {page_total}"
        )
        self.prev_page_btn.setEnabled(self._page_index > 0)
        self.next_page_btn.setEnabled(self._page_index < page_total - 1)
        self.prev_section_btn.setEnabled(self._section_index > 0)
        self.next_section_btn.setEnabled(self._section_index < section_total - 1)

    def _prev_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._show_current()

    def _next_page(self) -> None:
        pages = self._section_pages[self._section_index] if self._section_pages else ()
        if self._page_index < len(pages) - 1:
            self._page_index += 1
            self._show_current()

    def _prev_section(self) -> None:
        if self._section_index > 0:
            self.section_combo.setCurrentIndex(self._section_index - 1)

    def _next_section(self) -> None:
        if self._document is not None and self._section_index < len(self._document.sections) - 1:
            self.section_combo.setCurrentIndex(self._section_index + 1)
