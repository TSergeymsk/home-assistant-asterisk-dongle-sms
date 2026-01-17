"""Platform for notify integration."""
from __future__ import annotations

import logging
import shlex
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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

SERVICE_SMS = "sms"
SERVICE_USSD = "ussd"
ATTR_NUMBER = "number"
ATTR_MESSAGE = "message"
ATTR_USSD_CODE = "ussd_code"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка notify платформы из ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    devices = data[DATA_DEVICES]
    
    # Создаем сервисы для существующих устройств
    for imei, device_info in devices.items():
        await _create_notify_services(hass, manager, device_info, entry.entry_id)
    
    # Регистрируем обработчики для новых устройств
    async def async_add_notify_services(device_info):
        """Добавить сервисы нотификации для нового устройства."""
        await _create_notify_services(hass, manager, device_info, entry.entry_id)
    
    async def async_remove_notify_services(imei):
        """Удалить сервисы нотификации для устройства."""
        await _remove_notify_services(hass, imei)
    
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


async def _create_notify_services(
    hass: HomeAssistant, 
    manager, 
    device_info: dict[str, Any], 
    entry_id: str
):
    """Создает сервисы нотификации для донгла."""
    imei = device_info[ATTR_IMEI]
    dongle_id = device_info[ATTR_DONGLE_ID]
    
    # Регистрируем сервис отправки SMS
    async def async_sms_service(call: ServiceCall):
        """Обработчик сервиса отправки SMS."""
        number = call.data.get(ATTR_NUMBER)
        message = call.data.get(ATTR_MESSAGE)
        
        if not number:
            _LOGGER.error("Number is required for SMS")
            return
        
        if not message:
            _LOGGER.error("Message is required for SMS")
            return
        
        # Экранируем специальные символы в сообщении
        safe_message = shlex.quote(message)
        
        command = f"dongle sms {dongle_id} {number} {safe_message}"
        _LOGGER.debug("Sending SMS command: %s", command)
        
        response = await hass.async_add_executor_job(manager.send_command, command)
        
        if not response:
            _LOGGER.error("No response for SMS command to %s", dongle_id)
            return
            
        if "Response: Error" in response:
            # Парсим ошибку
            error_msg = "Unknown error"
            for line in response.split('\n'):
                if 'Message:' in line:
                    error_msg = line.split('Message:', 1)[1].strip()
                    break
            _LOGGER.error("Failed to send SMS via %s: %s", dongle_id, error_msg)
        else:
            _LOGGER.info("SMS sent to %s via %s", number, dongle_id)
    
    # Регистрируем сервис отправки USSD
    async def async_ussd_service(call: ServiceCall):
        """Обработчик сервиса отправки USSD."""
        ussd_code = call.data.get(ATTR_USSD_CODE)
        
        if not ussd_code:
            _LOGGER.error("USSD code is required")
            return
        
        # USSD код должен быть в кавычках
        safe_ussd_code = shlex.quote(ussd_code)
        
        command = f"dongle ussd {dongle_id} {safe_ussd_code}"
        _LOGGER.debug("Sending USSD command: %s", command)
        
        response = await hass.async_add_executor_job(manager.send_command, command)
        
        if not response:
            _LOGGER.error("No response for USSD command to %s", dongle_id)
            return
            
        if "Response: Error" in response:
            # Парсим ошибку
            error_msg = "Unknown error"
            for line in response.split('\n'):
                if 'Message:' in line:
                    error_msg = line.split('Message:', 1)[1].strip()
                    break
            _LOGGER.error("Failed to send USSD via %s: %s", dongle_id, error_msg)
        else:
            _LOGGER.info("USSD request sent via %s: %s", dongle_id, ussd_code)
    
    # Регистрируем сервисы в Home Assistant
    hass.services.async_register(
        domain="notify",
        service=f"sms_{imei}",
        service_func=async_sms_service,
        schema=None,  # Можно добавить схему валидации позже
    )
    
    hass.services.async_register(
        domain="notify",
        service=f"ussd_{imei}",
        service_func=async_ussd_service,
        schema=None,
    )
    
    _LOGGER.info("Created notify services for device %s (IMEI: %s)", dongle_id, imei)


async def _remove_notify_services(hass: HomeAssistant, imei: str):
    """Удаляет сервисы нотификации для устройства."""
    try:
        # Удаляем сервис SMS
        hass.services.async_remove(domain="notify", service=f"sms_{imei}")
        # Удаляем сервис USSD
        hass.services.async_remove(domain="notify", service=f"ussd_{imei}")
        
        _LOGGER.info("Removed notify services for device with IMEI: %s", imei)
    except (ValueError, KeyError) as err:
        _LOGGER.warning("Error removing services for %s: %s", imei, err)


async def async_unload_entry_notify(hass: HomeAssistant, entry: ConfigEntry):
    """Выгрузка notify сервисов при выгрузке конфигурационной записи."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        if DATA_DEVICES in hass.data[DOMAIN][entry.entry_id]:
            devices = hass.data[DOMAIN][entry.entry_id][DATA_DEVICES]
            for imei in devices.keys():
                await _remove_notify_services(hass, imei)