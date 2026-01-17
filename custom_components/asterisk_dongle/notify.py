"""Platform for notify integration."""
from __future__ import annotations

import logging
import shlex
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import config_validation as cv
from homeassistant.components.notify import (
    ATTR_TARGET,
    BaseNotificationService,
)

from .const import (
    DOMAIN,
    DATA_ASTERISK_MANAGER,
    DATA_DEVICES,
    ATTR_IMEI,
    ATTR_DONGLE_ID,
    SIGNAL_DEVICE_DISCOVERED,
    SIGNAL_DEVICE_REMOVED,
    ATTR_NUMBER,
    ATTR_MESSAGE,
    ATTR_USSD_CODE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка notify платформы из ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    devices = data[DATA_DEVICES]
    
    # Создаем начальные сервисы уведомлений
    sms_services = []
    ussd_services = []
    
    for imei, device_info in devices.items():
        # Создаем сервис SMS для этого донгла
        sms_service = AsteriskSMSNotifyService(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        sms_services.append(sms_service)
        
        # Создаем сервис USSD для этого донгла
        ussd_service = AsteriskUSSDNotifyService(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        ussd_services.append(ussd_service)
    
    # Регистрируем сервисы как отдельные уведомления
    async_add_entities(sms_services + ussd_services)
    
    # Регистрируем обработчики для новых устройств
    @callback
    async def async_add_notify_services(device_info):
        """Добавить сервисы нотификации для нового устройства."""
        # Создаем сервис SMS
        new_sms_service = AsteriskSMSNotifyService(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        
        # Создаем сервис USSD
        new_ussd_service = AsteriskUSSDNotifyService(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        
        async_add_entities([new_sms_service, new_ussd_service])
        _LOGGER.info("Added notify services for device: %s", device_info[ATTR_IMEI])
    
    @callback
    def async_remove_notify_services(imei):
        """Удалить сервисы нотификации для устройства."""
        # Home Assistant автоматически удалит сущности при удалении устройства
        _LOGGER.info("Notify services will be removed for device: %s", imei)
    
    # Подписываемся на сигналы
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}",
        async_add_notify_services
    )
    
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_REMOVED}_{entry.entry_id}",
        async_remove_notify_services
    )


class AsteriskSMSNotifyService(BaseNotificationService):
    """Сервис для отправки SMS через dongle."""
    
    def __init__(self, manager, device_info: dict[str, Any], entry_id: str, hass: HomeAssistant):
        """Инициализация сервиса."""
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
        self.hass = hass
        
        # Уникальный ID для сервиса
        imei = device_info[ATTR_IMEI]
        dongle_id = device_info[ATTR_DONGLE_ID]
        self._attr_unique_id = f"{entry_id}_{imei}_sms"
        self._attr_name = f"SMS {dongle_id} ({imei[-6:]})"
    
    @property
    def targets(self):
        """Возвращает список доступных целей."""
        # Возвращаем IMEI как цель
        return {self._device_info[ATTR_IMEI]: self._attr_name}
    
    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Отправка SMS сообщения."""
        # Получаем номер телефона из kwargs
        number = kwargs.get(ATTR_NUMBER) or kwargs.get(ATTR_TARGET)
        
        if not number:
            _LOGGER.error("Number is required for SMS")
            return
        
        if not message:
            _LOGGER.error("Message is required for SMS")
            return
        
        dongle_id = self._device_info[ATTR_DONGLE_ID]
        
        # Создаем команду для отправки SMS
        command = f"dongle sms {dongle_id} {number} {shlex.quote(message)}"
        _LOGGER.debug("Sending SMS command: %s", command)
        
        response = await self.hass.async_add_executor_job(
            self._manager.send_command, command
        )
        
        if not response:
            _LOGGER.error("No response for SMS command to %s", dongle_id)
            return
        
        _LOGGER.debug("SMS command response: %s", response)
        
        if "Response: Error" in response:
            error_msg = "Unknown error"
            for line in response.split('\n'):
                if 'Message:' in line:
                    error_msg = line.split('Message:', 1)[1].strip()
                    break
            _LOGGER.error("Failed to send SMS via %s: %s", dongle_id, error_msg)
        else:
            _LOGGER.info("SMS sent to %s via %s", number, dongle_id)


class AsteriskUSSDNotifyService(BaseNotificationService):
    """Сервис для отправки USSD запросов через dongle."""
    
    def __init__(self, manager, device_info: dict[str, Any], entry_id: str, hass: HomeAssistant):
        """Инициализация сервиса."""
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
        self.hass = hass
        
        # Уникальный ID для сервиса
        imei = device_info[ATTR_IMEI]
        dongle_id = device_info[ATTR_DONGLE_ID]
        self._attr_unique_id = f"{entry_id}_{imei}_ussd"
        self._attr_name = f"USSD {dongle_id} ({imei[-6:]})"
    
    @property
    def targets(self):
        """Возвращает список доступных целей."""
        # Возвращаем IMEI как цель
        return {self._device_info[ATTR_IMEI]: self._attr_name}
    
    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Отправка USSD запроса."""
        # Получаем USSD код из kwargs
        ussd_code = kwargs.get(ATTR_USSD_CODE) or message
        
        if not ussd_code:
            _LOGGER.error("USSD code is required")
            return
        
        dongle_id = self._device_info[ATTR_DONGLE_ID]
        
        # Важно: USSD код должен быть без кавычек
        command = f"dongle ussd {dongle_id} {ussd_code}"
        _LOGGER.debug("Sending USSD command: %s", command)
        
        response = await self.hass.async_add_executor_job(
            self._manager.send_command, command
        )
        
        if not response:
            _LOGGER.error("No response for USSD command to %s", dongle_id)
            return
        
        _LOGGER.debug("USSD command response: %s", response)
        
        if "Response: Error" in response:
            error_msg = "Unknown error"
            for line in response.split('\n'):
                if 'Message:' in line:
                    error_msg = line.split('Message:', 1)[1].strip()
                    break
            _LOGGER.error("Failed to send USSD via %s: %s", dongle_id, error_msg)
        else:
            _LOGGER.info("USSD request sent via %s: %s", dongle_id, ussd_code)


async def async_unload_entry_notify(hass: HomeAssistant, entry: ConfigEntry):
    """Выгрузка notify сервисов при выгрузке конфигурационной записи."""
    # Уведомления удаляются автоматически при выгрузке платформы
    _LOGGER.info("Notify services for Asterisk Dongle unloaded")