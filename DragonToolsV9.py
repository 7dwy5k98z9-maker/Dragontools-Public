# -*- coding: utf-8 -*-
"""
DragonToolsV9.py – Einstiegspunkt Dragon Tools V9
Eigenständig, kein Legacy-Code.
Lazy Loading: dragontools/-Module werden erst bei Bedarf importiert.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

from dragontools.core.version import APP_VERSION

FROZEN  = bool(getattr(sys, "frozen", False))
MEIPASS = Path(getattr(sys, "_MEIPASS", "")).resolve() if FROZEN else None
EXE_DIR = Path(sys.executable).parent.resolve() if FROZEN else Path(__file__).parent.resolve()

# sys.path
for _p in (str(EXE_DIR), str(MEIPASS) if MEIPASS else ""):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

# PATH für externe Tools
_tool_dirs = [
    EXE_DIR/"Daten"/"Programme",
    EXE_DIR/"Daten"/"Programme"/"FFmpeg",
    EXE_DIR/"Daten"/"Programme"/"mkvtoolnix",
    EXE_DIR/"Daten"/"Programme"/"MakeMKV",
    EXE_DIR/"Daten"/"Programme"/"GPAC",
    EXE_DIR/"Daten"/"Programme"/"rmts",
    EXE_DIR/"Daten"/"Programme"/"handbrake",
    EXE_DIR/"Daten"/"Programme"/"mediainfo",
    EXE_DIR/"Daten"/"Programme"/"dovi_tool",
    EXE_DIR/"Daten"/"Programme"/"hdr10plus_tool",
    EXE_DIR/"Programme", EXE_DIR/"Programme"/"mkvtoolnix",
    EXE_DIR/"Programme"/"MakeMKV",
    EXE_DIR/"third_party",
    EXE_DIR/"third_party"/"FFmpeg",
    EXE_DIR/"third_party"/"MKVToolNix",
    EXE_DIR/"third_party"/"MakeMKV",
    EXE_DIR/"third_party"/"GPAC",
    EXE_DIR/"third_party"/"HandBrake",
    EXE_DIR/"third_party"/"Mediainfo",
    EXE_DIR/"third_party"/"dovi_tool",
    EXE_DIR/"third_party"/"hdr10plus_tool",
    EXE_DIR/"third_party"/"rmts",
]
if MEIPASS:
    _tool_dirs += [MEIPASS, MEIPASS/"Programme", MEIPASS/"Daten"/"Programme"]
os.environ["PATH"] = os.pathsep.join(
    [str(p) for p in _tool_dirs if p.exists()] + [os.environ.get("PATH", "")]
)


# ══════════════════════════════════════════════════════════════════════════════
#  SPLASH-TEXT  –  frei definierbar, wird mit Feuer/Eis-Effekt gerendert
# ══════════════════════════════════════════════════════════════════════════════
SPLASH_TEXT = f"Dragon Tools V{APP_VERSION} startet"


def _close_pyinstaller_boot_splash() -> None:
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  Pfad-Helfer
# ══════════════════════════════════════════════════════════════════════════════

def _find_icon() -> str:
    for c in (EXE_DIR/"Daten"/"icon"/"Feuerdrache.ico",
              EXE_DIR/"icon"/"Feuerdrache.ico",
              EXE_DIR/"Feuerdrache.ico",
              *([ MEIPASS/"icon"/"Feuerdrache.ico"] if MEIPASS else [])):
        if c.exists():
            return str(c)
    return ""


def _find_splash_image() -> str:
    for c in (EXE_DIR/"Daten"/"Bilder"/"splash_Intro.png",
              EXE_DIR/"Bilder"/"splash_Intro.png",
              EXE_DIR/"splash_Intro.png",
              *([ MEIPASS/"Bilder"/"splash_Intro.png"] if MEIPASS else [])):
        if c.exists():
            return str(c)
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  DragonSplashScreen  –  Feuer × Eis  (reines Qt, kein Tcl/Tk)
# ══════════════════════════════════════════════════════════════════════════════

class DragonSplashScreen:
    """
    Qt-nativer Splash-Screen mit Feuer/Eis-Thema.

    Rendert über dem Bild:
      • Dunkel-transparentes Panel mit Farbverläufen
      • Trennlinie in Feuer→Eis-Gradient
      • Flammen- und Eiskristall-Dekorationen
      • Text mit Glow-Effekt und Feuer/Eis-Gradient
      • Ladebalken mit Feuer/Eis-Gradient und Glanz

    Verwendung:
        splash = DragonSplashScreen(app, text=SPLASH_TEXT, icon=icon_path)
        splash.set_progress(50)          # 0–100
        splash.finish(main_window)       # schließt den Splash
    """

    _PANEL_H    = 92     # Höhe des dunklen Panels (px)
    _BAR_H      = 15     # Höhe des Ladebalkens (px)
    _MARGIN     = 22     # Seitenabstand (px)
    _FONT_SIZE  = 22     # Schriftgröße (pt)

    def __init__(self, app, text: str, icon: str = ""):
        from PyQt6.QtWidgets import QSplashScreen
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtCore import Qt

        self._app  = app
        self._text = text
        self._progress = 0
        self._widget: QSplashScreen | None = None

        img_path = _find_splash_image()
        if not img_path:
            return

        pixmap = QPixmap(img_path)
        if pixmap.isNull():
            return

        # Auf max. 82 % der Bildschirmfläche skalieren
        screen = app.primaryScreen()
        if screen:
            sg = screen.geometry()
            max_w = int(sg.width()  * 0.82)
            max_h = int(sg.height() * 0.82)
            if pixmap.width() > max_w or pixmap.height() > max_h:
                pixmap = pixmap.scaled(
                    max_w, max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

        # Eigene Subklasse inline erstellen, um drawContents zu überschreiben
        outer = self

        class _Splash(QSplashScreen):
            def drawContents(self, painter):
                outer._draw(painter, self.width(), self.height())

        self._widget = _Splash(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        if icon:
            from PyQt6.QtGui import QIcon
            self._widget.setWindowIcon(QIcon(icon))
        self._widget.show()
        app.processEvents()

    # ── Öffentliche API ───────────────────────────────────────────────────────

    def set_progress(self, value: int) -> None:
        """Setzt Fortschritt (0–100) und rendert den Splash sofort neu."""
        self._progress = max(0, min(100, value))
        if self._widget:
            self._widget.repaint()
            self._app.processEvents()

    def finish(self, main_window) -> None:
        """Schließt den Splash sobald das Hauptfenster bereit ist."""
        if self._widget:
            self._widget.finish(main_window)

    # ── Zeichenmethode ────────────────────────────────────────────────────────

    def _draw(self, painter, w: int, h: int) -> None:
        from PyQt6.QtGui import (
            QColor, QFont, QLinearGradient, QPen, QBrush, QPainterPath,
        )
        from PyQt6.QtCore import Qt, QRect, QRectF

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setRenderHint(painter.RenderHint.TextAntialiasing)

        ph = self._PANEL_H
        m  = self._MARGIN

        # ── 1. Dunkles Panel (Gradient: oben transparent → unten halb-opak) ─
        bg = QLinearGradient(0, h - ph, 0, h)
        bg.setColorAt(0.00, QColor(0, 0, 0,   0))
        bg.setColorAt(0.30, QColor(0, 0, 0, 150))
        bg.setColorAt(1.00, QColor(0, 0, 0, 215))
        painter.fillRect(0, h - ph, w, ph, bg)

        # ── 2. Feuer/Eis-Trennlinie ───────────────────────────────────────────
        sep_y = h - ph + 1
        sl = QLinearGradient(0, 0, w, 0)
        sl.setColorAt(0.00, QColor(180,  40,   0, 200))
        sl.setColorAt(0.18, QColor(255, 120,   0, 255))
        sl.setColorAt(0.40, QColor(255, 220, 100, 255))
        sl.setColorAt(0.50, QColor(255, 255, 240, 255))
        sl.setColorAt(0.60, QColor(180, 230, 255, 255))
        sl.setColorAt(0.82, QColor(  0, 160, 255, 255))
        sl.setColorAt(1.00, QColor(  0,  80, 180, 200))
        painter.fillRect(0, sep_y, w, 2, sl)

        # ── 3. Flammen-Dekorationen (linke Seite) ─────────────────────────────
        self._draw_flames(painter, w, sep_y)

        # ── 4. Eiskristall-Dekorationen (rechte Seite) ────────────────────────
        self._draw_crystals(painter, w, sep_y)

        # ── 5. Glow-Text ──────────────────────────────────────────────────────
        font = QFont()
        font.setFamilies(["Segoe UI", "Helvetica Neue", "Arial"])
        font.setPointSize(self._FONT_SIZE)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        painter.setFont(font)

        text_h   = ph - self._BAR_H - 30
        text_y   = h - ph + 10
        text_rect = QRect(m, text_y, w - 2 * m, text_h)
        flags    = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        cx       = w // 2   # Mittelpunkt Farbwechsel

        # Glow-Schichten (Feuer links, Eis rechts)
        glow_spec = [
            (6, 0.06, QColor(255,  80,  0), QColor(  0, 140, 255)),
            (4, 0.10, QColor(255, 110,  0), QColor( 20, 160, 255)),
            (3, 0.17, QColor(255, 140, 20), QColor( 60, 190, 255)),
            (2, 0.28, QColor(255, 170, 40), QColor(110, 210, 255)),
            (1, 0.45, QColor(255, 200, 80), QColor(160, 230, 255)),
        ]
        for radius, opacity, fc, ic in glow_spec:
            for dx in range(-radius, radius + 1, max(1, radius)):
                for dy in range(-radius, radius + 1, max(1, radius)):
                    if dx == 0 and dy == 0:
                        continue
                    tr = text_rect.translated(dx, dy)
                    # Feuer-Seite
                    fc.setAlphaF(opacity)
                    painter.setPen(fc)
                    painter.setClipRect(QRect(0, 0, cx, h))
                    painter.drawText(tr, flags, self._text)
                    # Eis-Seite
                    ic.setAlphaF(opacity)
                    painter.setPen(ic)
                    painter.setClipRect(QRect(cx, 0, w - cx, h))
                    painter.drawText(tr, flags, self._text)

        painter.setClipping(False)

        # Haupt-Text: Feuer→Eis-Gradient
        tg = QLinearGradient(text_rect.left(), 0, text_rect.right(), 0)
        tg.setColorAt(0.00, QColor(255,  70,   0))   # tiefes Feuer-Orange
        tg.setColorAt(0.18, QColor(255, 155,  20))   # helles Orange
        tg.setColorAt(0.40, QColor(255, 240, 160))   # Weißglut links
        tg.setColorAt(0.50, QColor(255, 255, 255))   # Zentrum rein weiß
        tg.setColorAt(0.60, QColor(210, 240, 255))   # Weißglut rechts
        tg.setColorAt(0.82, QColor( 70, 185, 255))   # Eisblau
        tg.setColorAt(1.00, QColor(  0, 110, 210))   # tiefes Blau

        painter.setPen(QPen(QBrush(tg), 1.0))
        painter.drawText(text_rect, flags, self._text)

        # ── 6. Ladebalken ─────────────────────────────────────────────────────
        bar_y = h - self._BAR_H - 9
        bar_w = w - 2 * m
        r     = self._BAR_H // 2   # Rundungsradius

        # Schiene (dunkel, gerundet)
        rail = QPainterPath()
        rail.addRoundedRect(QRectF(m, bar_y, bar_w, self._BAR_H), r, r)
        painter.fillPath(rail, QColor(15, 15, 25, 210))

        fill_w = int(bar_w * self._progress / 100)
        if fill_w >= r * 2:
            # Aktiver Balken: Feuer→Eis
            bg2 = QLinearGradient(m, 0, m + bar_w, 0)
            bg2.setColorAt(0.00, QColor(210,  50,   0))
            bg2.setColorAt(0.22, QColor(255, 130,   0))
            bg2.setColorAt(0.50, QColor(255, 255, 210))
            bg2.setColorAt(0.78, QColor( 70, 195, 255))
            bg2.setColorAt(1.00, QColor(  0,  95, 200))

            fill = QPainterPath()
            fill.addRoundedRect(QRectF(m, bar_y, fill_w, self._BAR_H), r, r)
            painter.fillPath(fill, bg2)

            # Glanzstreifen oben auf dem Balken
            shine = QLinearGradient(m, bar_y, m, bar_y + self._BAR_H // 2)
            shine.setColorAt(0.0, QColor(255, 255, 255, 90))
            shine.setColorAt(1.0, QColor(255, 255, 255,  0))
            shine_path = QPainterPath()
            shine_path.addRoundedRect(
                QRectF(m, bar_y, fill_w, self._BAR_H // 2), r, r
            )
            painter.fillPath(shine_path, shine)

        painter.restore()

    # ── Dekorationen ──────────────────────────────────────────────────────────

    @staticmethod
    def _draw_flames(painter, w: int, sep_y: int) -> None:
        """Kleine Flammen-Silhouetten entlang der Trennlinie (linke Hälfte)."""
        from PyQt6.QtGui import QColor, QPainterPath, QLinearGradient
        from PyQt6.QtCore import QPointF

        positions_x = [int(w * f) for f in (0.04, 0.09, 0.15, 0.21, 0.27, 0.33, 0.38)]
        for i, px in enumerate(positions_x):
            fh = 14 + (i % 3) * 5      # variierende Flammenhöhe
            fw = 8  + (i % 2) * 3      # variierende Breite
            fy = sep_y - fh

            path = QPainterPath()
            path.moveTo(QPointF(px,        sep_y - 1))
            path.cubicTo(
                QPointF(px - fw * 0.6, fy + fh * 0.5),
                QPointF(px + fw * 0.4, fy + fh * 0.2),
                QPointF(px,            fy),
            )
            path.cubicTo(
                QPointF(px - fw * 0.3, fy + fh * 0.3),
                QPointF(px + fw * 0.7, fy + fh * 0.6),
                QPointF(px + fw,       sep_y - 1),
            )
            path.closeSubpath()

            grad = QLinearGradient(px, sep_y, px, fy)
            grad.setColorAt(0.0, QColor(255, 100,   0, 210))
            grad.setColorAt(0.5, QColor(255, 180,   0, 150))
            grad.setColorAt(1.0, QColor(255, 240, 100,   0))
            painter.fillPath(path, grad)

    @staticmethod
    def _draw_crystals(painter, w: int, sep_y: int) -> None:
        """Kleine Eiskristall-Rauten entlang der Trennlinie (rechte Hälfte)."""
        from PyQt6.QtGui import QColor, QPainterPath, QLinearGradient, QPen
        from PyQt6.QtCore import QPointF

        positions_x = [int(w * f) for f in (0.62, 0.68, 0.74, 0.80, 0.86, 0.91, 0.96)]
        for i, px in enumerate(positions_x):
            ch = 14 + (i % 3) * 5
            cw =  6 + (i % 2) * 3
            cy = sep_y - ch

            # Äußere Raute
            outer = QPainterPath()
            outer.moveTo(QPointF(px,      cy))
            outer.lineTo(QPointF(px + cw, sep_y - ch // 2))
            outer.lineTo(QPointF(px,      sep_y - 1))
            outer.lineTo(QPointF(px - cw, sep_y - ch // 2))
            outer.closeSubpath()

            grad = QLinearGradient(px, cy, px, sep_y)
            grad.setColorAt(0.0, QColor(200, 240, 255,   0))
            grad.setColorAt(0.4, QColor(150, 220, 255, 160))
            grad.setColorAt(1.0, QColor( 80, 180, 255, 220))
            painter.fillPath(outer, grad)

            # Innere Rautenkontur (Glas-Effekt)
            painter.setPen(QPen(QColor(200, 240, 255, 120), 0.5))
            inner = QPainterPath()
            s = 0.45
            inner.moveTo(QPointF(px,           cy + ch * s))
            inner.lineTo(QPointF(px + cw * s,  sep_y - ch * s))
            inner.lineTo(QPointF(px,           sep_y - ch * s * 0.5))
            inner.lineTo(QPointF(px - cw * s,  sep_y - ch * s))
            inner.closeSubpath()
            painter.drawPath(inner)
            painter.setPen(QPen(QColor(0, 0, 0, 0)))  # reset


# ══════════════════════════════════════════════════════════════════════════════
#  Einstiegspunkt
# ══════════════════════════════════════════════════════════════════════════════

def main():
    clear_activity_fn = lambda: None
    from PyQt6.QtCore import QCoreApplication, Qt, QTimer
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setOrganizationName("DragonTools")
    app.setApplicationName("Dragon Tools")
    app.setApplicationVersion(APP_VERSION)

    # ── Splash anzeigen ──────────────────────────────────────────────────────
    splash = DragonSplashScreen(app, text=SPLASH_TEXT)
    _close_pyinstaller_boot_splash()
    splash.set_progress(10)

    from PyQt6.QtGui import QIcon
    icon = _find_icon()
    if icon:
        app.setWindowIcon(QIcon(icon))

    splash.set_progress(20)
    from dragontools.core.crash_guard import (
        clear_activity,
        install_crash_guard,
        mark_activity,
    )
    from dragontools.core.timeout_settings import migrate_v91_timeout_defaults
    app.setApplicationVersion(APP_VERSION)
    migrate_v91_timeout_defaults()
    clear_activity_fn = clear_activity
    install_crash_guard(APP_VERSION)
    mark_activity("Qt-App wird initialisiert")

    # ── Module laden (Fortschritt mitschreiben) ──────────────────────────────
    splash.set_progress(30)
    from dragontools.gui.main_window import MainWindow, bring_to_front

    # ── Hauptfenster aufbauen ────────────────────────────────────────────────
    splash.set_progress(65)
    win = MainWindow()
    if icon:
        win.setWindowIcon(QIcon(icon))

    splash.set_progress(90)
    win.show()

    # ── Splash abschließen ───────────────────────────────────────────────────
    splash.set_progress(100)
    splash.finish(win)

    QTimer.singleShot(150, lambda: bring_to_front(win))
    mark_activity("Hauptfenster aktiv")
    try:
        return app.exec()
    finally:
        clear_activity_fn()


if __name__ == "__main__":
    sys.exit(main())
