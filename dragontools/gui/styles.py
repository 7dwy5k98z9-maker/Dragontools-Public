# -*- coding: utf-8 -*-
"""
dragontools/gui/styles.py

Qt-Stylesheets für Dragon Tools.

Vorher waren STYLE_LIGHT und STYLE_DARK direkt in main_window.py definiert
(~80 Zeilen CSS), ohne jeden Bezug zur Fensterlogik.  Hier isoliert, damit:
  - main_window.py schlanker wird
  - Styling leicht gefunden und angepasst werden kann
  - zukuenftige Theme-Erweiterungen eine klare Heimat haben

Benutzung
---------
    from .styles import STYLE_LIGHT, STYLE_DARK
    app.setStyleSheet(STYLE_DARK if dark_mode else STYLE_LIGHT)
"""

STYLE_LIGHT = """
    QMenuBar{background:#f0f0f0;color:black;padding:4px;}
    QMenuBar::item{background:transparent;padding:4px 10px;border-radius:4px;}
    QMenuBar::item:selected{background:#0078d7;color:white;}
    QMenu{background:#f9f9f9;border:1px solid #c0c0c0;padding:4px;}
    QMenu::item{padding:5px 24px;}
    QMenu::item:selected{background:#0078d7;color:white;}
    QTabBar::tab{background:#e0e0e0;color:black;padding:6px 14px;border:1px solid #b0b0b0;
                 border-bottom:none;border-top-left-radius:4px;border-top-right-radius:4px;}
    QTabBar::tab:hover{background:#0078d7;color:white;}
    QTabBar::tab:selected{background:#fff;color:black;border-color:#0078d7;font-weight:bold;}
    QTabWidget::pane{border:1px solid #b0b0b0;top:-1px;}
    QGroupBox{border:1px solid #c0c0c0;border-radius:4px;margin-top:8px;padding-top:4px;}
    QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}
    QPushButton{padding:4px 12px;border:1px solid #b0b0b0;border-radius:3px;background:#f5f5f5;}
    QPushButton:hover{background:#0078d7;color:white;border-color:#005fa3;}
    QPushButton:pressed{background:#005fa3;color:white;}
    QPushButton:disabled{color:#999;background:#ececec;}
    QProgressBar{border:1px solid #b0b0b0;border-radius:3px;text-align:center;}
    QProgressBar::chunk{background:#0078d7;border-radius:2px;}
    QLineEdit:disabled{background:#f0f0f0;color:#999;}
    QComboBox:disabled{background:#f0f0f0;color:#999;}
"""

STYLE_DARK = """
    QWidget{background:#1e1e1e;color:#e0e0e0;}
    QGroupBox{border:1px solid #444;margin-top:8px;}
    QGroupBox::title{color:#aaa;}
    QLineEdit,QTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QListWidget{
        background:#2d2d2d;color:#e0e0e0;border:1px solid #555;}
    QPushButton{background:#2d2d2d;color:#e0e0e0;border:1px solid #555;
                padding:4px 12px;border-radius:3px;}
    QPushButton:hover{background:#0078d7;color:white;}
    QPushButton:disabled{color:#666;background:#252525;}
    QTabBar::tab{background:#2d2d2d;color:#ccc;border:1px solid #555;padding:6px 14px;}
    QTabBar::tab:selected{background:#1e1e1e;color:white;font-weight:bold;}
    QTabWidget::pane{border:1px solid #555;}
    QMenuBar{background:#2d2d2d;color:#e0e0e0;}
    QMenuBar::item:selected{background:#0078d7;}
    QMenu{background:#2d2d2d;color:#e0e0e0;border:1px solid #555;}
    QMenu::item:selected{background:#0078d7;}
    QProgressBar{background:#2d2d2d;border:1px solid #555;}
    QProgressBar::chunk{background:#0078d7;}
    QCheckBox,QLabel{color:#e0e0e0;}
    QLineEdit:disabled{background:#252525;color:#555;}
"""
