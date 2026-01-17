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
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.helpers import device_registry as dr

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

SERVICE_SMS = "asterisk_dongle_sms"
SERVICE_USSD = "asterisk_dongle_ussd"

# Схемы валидации для сервисов - теперь с селектором устройств
SMS_SERVICE_SCHEMA = vol.Schema({
    vol.Required("target"): cv.string,  # ID устройства в HA
    vol.Required(ATTR_NUMBER): cv.string,
    vol.Required(ATTR_MESSAGE): cv.string,
})

USSD_SERVICE_SCHEMA = vol.Schema({
    vol.Required("target"): cv.string,  # ID устройства в HA
    vol.Required(ATTR_USSD_CODE): cv.string,
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка notify платформы из ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    devices = data[DATA_DEVICES]

    # Получаем реестр устройств
    device_registry = dr.async_get(hass)

    # Функция для получения IMEI по ID устройства HA
    def get_imei_from_device_id(device_id: str) -> str | None:
        """Извлекает IMEI из идентификаторов устройства."""
        try:
            device = device_registry.async_get(device_id)
            if device:
                # Ищем идентификатор вида (DOMAIN, IMEI)
                for identifier in device.identifiers:
                    if identifier[0] == DOMAIN:
                        return identifier[1]
        except Exception as e:
            _LOGGER.warning("Error getting device info: %s", e)
        return None

    # Регистрируем сервисы для SMS и USSD
    async def async_sms_service(call: ServiceCall):
        """Обработчик сервиса отправки SMS."""
        target_device_id = call.data.get("target")  # ID устройства в HA
        number = call.data.get(ATTR_NUMBER)
        message = call.data.get(ATTR_MESSAGE)

        if not target_device_id:
            _LOGGER.error("Target device is required for SMS")
            return

        # Получаем IMEI из ID устройства
        imei = get_imei_from_device_id(target_device_id)
        if not imei:
            _LOGGER.error("Could not get IMEI from device ID %s", target_device_id)
            return

        # Находим устройство по IMEI
        if imei not in devices:
            _LOGGER.error("Device with IMEI %s not found", imei)
            return

        device_info = devices[imei]
        dongle_id = device_info[ATTR_DONGLE_ID]

        if not number:
            _LOGGER.error("Number is required for SMS")
            return
        
        if not message:
            _LOGGER.error("Message is required for SMS")
            return

        # Создаем команду для отправки SMS
        command = f"dongle sms {dongle_id} {number} {shlex.quote(message)}"
        _LOGGER.debug("Sending SMS command: %s", command)

        response = await hass.async_add_executor_job(manager.send_command, command)

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

    async def async_ussd_service(call: ServiceCall):
        """Обработчик сервиса отправки USSD."""
        target_device_id = call.data.get("target")  # ID устройства в HA
        ussd_code = call.data.get(ATTR_USSD_CODE)

        if not target_device_id:
            _LOGGER.error("Target device is required for USSD")
            return

        # Получаем IMEI из ID устройства
        imei = get_imei_from_device_id(target_device_id)
        if not imei:
            _LOGGER.error("Could not get IMEI from device ID %s", target_device_id)
            return

        # Находим устройство по IMEI
        if imei not in devices:
            _LOGGER.error("Device with IMEI %s not found", imei)
            return

        device_info = devices[imei]
        dongle_id = device_info[ATTR_DONGLE_ID]

        if not ussd_code:
            _LOGGER.error("USSD code is required")
            return

        # Важно: USSD код должен быть без кавычек
        command = f"dongle ussd {dongle_id} {ussd_code}"
        _LOGGER.debug("Sending USSD command: %s", command)

        response = await hass.async_add_executor_job(manager.send_command, command)

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

    # Регистрируем сервисы
    hass.services.async_register(
        domain="notify",
        service=SERVICE_SMS,
        service_func=async_sms_service,
        schema=SMS_SERVICE_SCHEMA,
    )

    hass.services.async_register(
        domain="notify",
        service=SERVICE_USSD,
        service_func=async_ussd_service,
        schema=USSD_SERVICE_SCHEMA,
    )

    # Создаем схему для отображения в UI с селектором устройств
    service_schema = {
        "description": "Send SMS via Asterisk Dongle",
        "fields": {
            "target": {
                "name": "Dongle Device",
                "description": "Select the dongle device",
                "required": True,
                "selector": {
                    "device": {
                        "integration": DOMAIN,
                        "multiple": False
                    }
                }
            },
            ATTR_NUMBER: {
                "name": "Phone Number",
                "description": "Phone number to send SMS to",
                "required": True,
                "selector": {
                    "text": {}
                }
            },
            ATTR_MESSAGE: {
                "name": "Message",
                "description": "Text of the SMS message",
                "required": True,
                "selector": {
                    "text": {}
                }
            }
        }
    }

    # Устанавливаем схемы сервисов для отображения в UI
    await async_set_service_schema(
        hass,
        "notify",
        SERVICE_SMS,
        service_schema
    )

    # Для USSD используем аналогичную схему, но с другим полем вместо message
    ussd_schema = service_schema.copy()
    ussd_schema["description"] = "Send USSD request via Asterisk Dongle"
    ussd_schema["fields"] = ussd_schema["fields"].copy()
    del ussd_schema["fields"][ATTR_MESSAGE]
    del ussd_schema["fields"][ATTR_NUMBER]
    ussd_schema["fields"][ATTR_USSD_CODE] = {
        "name": "USSD Code",
        "description": "USSD code to send (e.g., *100#)",
        "required": True,
        "selector": {
            "text": {}
        }
    }

    await async_set_service_schema(
        hass,
        "notify",
        SERVICE_USSD,
        ussd_schema
    )

    _LOGGER.info("Notify services for Asterisk Dongle registered with UI schemas")

    # Обработчики для обновления списка устройств
    @callback
    def handle_device_discovered(device_info):
        """Обновляем список устройств при обнаружении нового."""
        # Обновляем devices в data
        devices[device_info[ATTR_IMEI]] = device_info
        _LOGGER.debug("Device list updated, now %d devices", len(devices))

    @callback
    def handle_device_removed(imei):
        """Удаляем устройство из списка."""
        if imei in devices:
            del devices[imei]
            _LOGGER.debug("Device %s removed from list", imei)

    # Подписываемся на сигналы
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}",
        handle_device_discovered
    )
    
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_REMOVED}_{entry.entry_id}",
        handle_device_removed
    )


async def async_unload_entry_notify(hass: HomeAssistant, entry: ConfigEntry):
    """Выгрузка notify сервисов при выгрузке конфигурационной записи."""
    # Удаляем сервисы
    hass.services.async_remove(domain="notify", service=SERVICE_SMS)
    hass.services.async_remove(domain="notify", service=SERVICE_USSD)
    _LOGGER.info("Notify services for Asterisk Dongle unloaded")