"""Native Qt lifetime check shared by queued GUI callback boundaries."""
from PyQt6.QtCore import QObject
from PyQt6 import sip


def receiver_is_alive(owner):
    return not isinstance(owner, QObject) or not sip.isdeleted(owner)
