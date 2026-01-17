"""Platform for notify integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import (
    ATTR_TARGET,
    BaseNotificationService,
    DOMAIN as NOTIFY_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    DATA_ASTERISK_MANAGER,
    DATA_DEVICES,
    ATTR_IMEI,
    ATTR_DONGLE_ID,
    SIGNAL_DEVICE_DISCOVERED,
    SIGNAL_DEVICE_REMOVED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка notify платформы из ConfigEntry."""
    # Пока оставляем пустым, реализуем позже
    pass


class AsteriskSMSNotifyService(BaseNotificationService):
    """Сервис для отправки SMS через dongle."""
    
    def __init__(self, manager, device_info: dict[str, Any], entry_id: str):
        """Инициализация сервиса."""
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
    
    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Отправка SMS сообщения."""
        # Реализуем позже
        _LOGGER.debug("SMS send requested for device %s", self._device_info[ATTR_IMEI])


class AsteriskUSSDNotifyService(BaseNotificationService):
    """Сервис для отправки USSD запросов через dongle."""
    
    def __init__(self, manager, device_info: dict[str, Any], entry_id: str):
        """Инициализация сервиса."""
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
    
    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Отправка USSD запроса."""
        # Реализуем позже
        _LOGGER.debug("USSD send requested for device %s", self._device_info[ATTR_IMEI])