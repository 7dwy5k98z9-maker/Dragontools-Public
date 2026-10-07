"""Native GUI and image-codec checks used by the release entry point."""
def verify_native_widgets_and_jpeg():
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
    from PyQt6.QtGui import QImage
    from .quality_tester_widget import QualityTesterWidget
    from .audio_video_matcher_widget import AudioVideoMatcherWidget
    widgets = [QualityTesterWidget(), AudioVideoMatcherWidget()]
    try:
        for widget in widgets:
            widget.ensurePolished()
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(0)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, 'JPG') or QImage.fromData(data, 'JPG').isNull():
            raise RuntimeError('Qt-JPEG-Encoder/Decoder fehlt im Frozen-Bundle.')
    finally:
        for widget in widgets:
            widget.deleteLater()
