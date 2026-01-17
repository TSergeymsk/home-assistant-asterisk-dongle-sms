"""The Asterisk Dongle SMS component."""
import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "asterisk_dongle_sms"

# Импортируем класс менеджера из notify.py
from .notify import AsteriskManager

__all__ = ["DOMAIN", "AsteriskManager"]