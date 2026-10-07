"""Release temporary modal dialogs after their guarded Qt completion."""
from .qt_receiver_state import receiver_is_alive


def exec_owned_dialog(dialog):
    try:
        return dialog.exec()
    finally:
        if receiver_is_alive(dialog):
            dispose = getattr(dialog, "deleteLater", None)
            if callable(dispose):
                dispose()
