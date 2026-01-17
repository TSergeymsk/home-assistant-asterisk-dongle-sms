"""The Asterisk Dongle integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    DATA_ASTERISK_MANAGER,
    DATA_DEVICE_DISCOVERY,
    DATA_DEVICES,
    DATA_CONFIG_ENTRY,
    DISCOVERY_INTERVAL,
    ATTR_IMEI,
    ATTR_DONGLE_ID,
    ATTR_MODEL,
    PLATFORM_NOTIFY,
    PLATFORM_SENSOR,
)
from .notify import AsteriskManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NOTIFY, Platform.SENSOR]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Настройка интеграции из configuration.yaml (для обратной совместимости)."""
    # Регистрируем домен
    hass.data.setdefault(DOMAIN, {})
    
    # Если есть конфиг в YAML, создаем entry
    if DOMAIN in config:
        _LOGGER.warning(
            "Configuration via YAML is deprecated. "
            "Please use the UI to configure Asterisk Dongle."
        )
        
        # Создаем фиктивный entry для обратной совместимости
        # В реальности лучше мигрировать конфиг
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=config[DOMAIN]
            )
        )
    
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка интеграции из ConfigEntry."""
    # Сохраняем entry в hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CONFIG_ENTRY: entry,
        DATA_DEVICES: {},
    }
    
    # Создаем менеджер AMI
    manager = AsteriskManager(
        entry.data["host"],
        entry.data["port"],
        entry.data["username"],
        entry.data["password"]
    )
    
    hass.data[DOMAIN][entry.entry_id][DATA_ASTERISK_MANAGER] = manager
    
    # Первоначальное обнаружение устройств
    await _discover_devices(hass, entry)
    
    # Запускаем периодическое обнаружение
    async def _async_discovery(*_):
        await _discover_devices(hass, entry)
    
    hass.data[DOMAIN][entry.entry_id][DATA_DEVICE_DISCOVERY] = async_track_time_interval(
        hass, _async_discovery, timedelta(seconds=DISCOVERY_INTERVAL)
    )
    
    # Загружаем платформы
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def _discover_devices(hass: HomeAssistant, entry: ConfigEntry):
    """Обнаружение устройств dongle через AMI."""
    manager = hass.data[DOMAIN][entry.entry_id][DATA_ASTERISK_MANAGER]
    devices = hass.data[DOMAIN][entry.entry_id][DATA_DEVICES]
    
    try:
        # Получаем список устройств
        response = await hass.async_add_executor_job(
            manager.send_command, "dongle show devices"
        )
        
        if not response:
            _LOGGER.error("No response from Asterisk for device discovery")
            return
        
        # Парсим ответ
        discovered = _parse_devices_response(response)
        _LOGGER.debug("Discovered %d devices: %s", len(discovered), discovered)
        
        # Обновляем список устройств
        for device in discovered:
            imei = device[ATTR_IMEI]
            if imei not in devices:
                devices[imei] = device
                _LOGGER.info("New device discovered: %s", device)
        
        # TODO: Обработка удаленных устройств
        
    except Exception as e:
        _LOGGER.error("Error discovering devices: %s", e)


def _parse_devices_response(response: str) -> list[dict[str, Any]]:
    """Парсинг ответа 'dongle show devices'."""
    devices = []
    lines = response.split('\n')
    
    # Ищем строку с данными
    in_data = False
    for line in lines:
        line = line.strip()
        
        # Пропускаем заголовки
        if line.startswith("ID") and "Group" in line:
            in_data = True
            continue
            
        # Пропускаем разделители
        if not line or line.startswith("---"):
            continue
            
        if in_data and line:
            # Парсим строку с данными
            parts = line.split()
            if len(parts) >= 10:
                device = {
                    ATTR_DONGLE_ID: parts[0],  # dongle0, dongle1 и т.д.
                    "group": parts[1],
                    "state": parts[2],
                    "rssi_raw": parts[3],
                    "mode": parts[4],
                    "submode": parts[5],
                    "provider": parts[6],
                    ATTR_MODEL: parts[7],
                    "firmware": parts[8],
                    ATTR_IMEI: parts[9],
                    "imsi": parts[10] if len(parts) > 10 else "",
                    "number": parts[11] if len(parts) > 11 else "Unknown",
                }
                devices.append(device)
    
    return devices


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка конфигурационной записи."""
    # Останавливаем discovery
    if DATA_DEVICE_DISCOVERY in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id][DATA_DEVICE_DISCOVERY]()
    
    # Выгружаем платформы
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезагрузка записи конфигурации."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)