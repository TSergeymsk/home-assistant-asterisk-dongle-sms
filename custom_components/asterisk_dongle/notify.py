"""Platform for notify integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import (
    ATTR_TARGET,
    BaseNotificationService,
    DOMAIN as NOTIFY_DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    DOMAIN,
    DATA_ASTERISK_MANAGER,
    DATA_DEVICES,
    DATA_CONFIG_ENTRY,
    ATTR_IMEI,
    ATTR_DONGLE_ID,
    SERVICE_SMS,
    SERVICE_USSD,
    SIGNAL_DEVICE_DISCOVERED,
    SIGNAL_DEVICE_REMOVED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка notify платформы из ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data[DATA_DEVICES]
    
    # Создаем начальные сервисы notify
    for imei, device_info in devices.items():
        await _create_notify_services(hass, entry.entry_id, device_info)
    
    # Регистрируем обработчики для новых устройств
    async def async_add_notify_services(device_info):
        """Добавить сервисы notify для нового устройства."""
        await _create_notify_services(hass, entry.entry_id, device_info)
    
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}",
        async_add_notify_services
    )
    
    return True


async def _create_notify_services(
    hass: HomeAssistant,
    entry_id: str,
    device_info: dict[str, Any]
):
    """Создать сервисы SMS и USSD для устройства."""
    data = hass.data[DOMAIN][entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    imei = device_info[ATTR_IMEI]
    
    # Создаем сервис SMS
    sms_service = AsteriskSMSNotifyService(
        manager=manager,
        device_info=device_info,
        entry_id=entry_id
    )
    
    # Создаем сервис USSD
    ussd_service = AsteriskUSSDNotifyService(
        manager=manager,
        device_info=device_info,
        entry_id=entry_id
    )
    
    # Регистрируем сервисы
    hass.services.async_register(
        NOTIFY_DOMAIN,
        f"sms_{imei}",
        sms_service.async_send_message,
        schema=SMS_SERVICE_SCHEMA,
    )
    
    hass.services.async_register(
        NOTIFY_DOMAIN,
        f"ussd_{imei}",
        ussd_service.async_send_message,
        schema=USSD_SERVICE_SCHEMA,
    )
    
    _LOGGER.debug("Created notify services for device: %s", imei)


class AsteriskSMSNotifyService(BaseNotificationService):
    """Сервис для отправки SMS через dongle."""
    
    def __init__(self, manager, device_info: dict[str, Any], entry_id: str):
        """Инициализация сервиса."""
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
    
    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Отправка SMS сообщения."""
        # Номер получателя должен быть в kwargs
        number = kwargs.get("number")
        if not number:
            _LOGGER.error("Phone number is required for SMS")
            return
        
        # Формируем команду AMI для отправки SMS
        # В зависимости от вашего модуля dongle
        cmd = (
            f"dongle sms {self._device_info[ATTR_DONGLE_ID]} "
            f"{number} {message}"
        )
        
        try:
            response = await self.hass.async_add_executor_job(
                self._manager.send_command, cmd
            )
            _LOGGER.debug("SMS send response: %s", response)
        except Exception as e:
            _LOGGER.error("Error sending SMS: %s", e)


class AsteriskUSSDNotifyService(BaseNotificationService):
    """Сервис для отправки USSD запросов через dongle."""
    
    def __init__(self, manager, device_info: dict[str, Any], entry_id: str):
        """Инициализация сервиса."""
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
    
    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Отправка USSD запроса."""
        # USSD код должен быть в message
        if not message.startswith("*"):
            _LOGGER.warning("USSD code should start with *")
        
        # Формируем команду AMI для отправки USSD
        cmd = f"dongle ussd {self._device_info[ATTR_DONGLE_ID]} {message}"
        
        try:
            response = await self.hass.async_add_executor_job(
                self._manager.send_command, cmd
            )
            _LOGGER.debug("USSD send response: %s", response)
        except Exception as e:
            _LOGGER.error("Error sending USSD: %s", e)