"""The Asterisk Dongle integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    DATA_ASTERISK_MANAGER,
    DATA_DEVICES,
    DATA_CONFIG_ENTRY,
    DISCOVERY_INTERVAL,
    ATTR_IMEI,
    ATTR_DONGLE_ID,
    SIGNAL_DEVICE_DISCOVERED,
    SIGNAL_DEVICE_REMOVED,
)
from .manager import AsteriskManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NOTIFY, Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка интеграции из ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Создаем менеджер AMI
    manager = AsteriskManager(
        entry.data["host"],
        entry.data["port"],
        entry.data["username"],
        entry.data["password"]
    )
    
    # Сохраняем данные
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CONFIG_ENTRY: entry,
        DATA_ASTERISK_MANAGER: manager,
        DATA_DEVICES: {},
    }
    
    # Первоначальное обнаружение устройств
    await _discover_devices(hass, entry)
    
    # Запускаем периодическое обнаружение
    async def _async_discovery(*_):
        await _discover_devices(hass, entry)
    
    # Сохраняем ссылку на задачу
    hass.data[DOMAIN][entry.entry_id]["discovery_job"] = async_track_time_interval(
        hass, _async_discovery, timedelta(seconds=DISCOVERY_INTERVAL)
    )
    
    # Загружаем платформы
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def _discover_devices(hass: HomeAssistant, entry: ConfigEntry):
    """Обнаружение устройств dongle через AMI."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    current_devices = data.get(DATA_DEVICES, {})
    
    try:
        # Получаем список устройств
        response = await hass.async_add_executor_job(
            manager.send_command, "dongle show devices"
        )
        
        if not response:
            _LOGGER.error("No response from Asterisk for device discovery")
            return
        
        # Парсим ответ
        discovered_devices = _parse_devices_response(response)
        _LOGGER.debug("Discovered %d devices", len(discovered_devices))
        
        # Создаем словарь для быстрого доступа по IMEI
        new_devices = {}
        for device in discovered_devices:
            imei = device[ATTR_IMEI]
            new_devices[imei] = device
            
            # Если устройство новое - отправляем сигнал
            if imei not in current_devices:
                _LOGGER.info("New device discovered: %s (IMEI: %s)", 
                           device[ATTR_DONGLE_ID], imei)
                async_dispatcher_send(
                    hass, 
                    f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}", 
                    device
                )
        
        # Проверяем удаленные устройства
        for imei in list(current_devices.keys()):
            if imei not in new_devices:
                _LOGGER.info("Device removed: %s", imei)
                async_dispatcher_send(
                    hass,
                    f"{SIGNAL_DEVICE_REMOVED}_{entry.entry_id}",
                    imei
                )
        
        # Обновляем список устройств
        data[DATA_DEVICES] = new_devices
        
    except Exception as e:
        _LOGGER.error("Error discovering devices: %s", e)


def _parse_devices_response(response: str) -> list[dict[str, Any]]:
    """Парсинг ответа 'dongle show devices'."""
    devices = []
    lines = response.split('\n')
    
    # Пропускаем заголовки до строки с данными
    start_parsing = False
    for line in lines:
        line = line.strip()
        
        # Начало таблицы данных
        if line.startswith("---"):
            start_parsing = True
            continue
            
        if start_parsing and line:
            # Парсим строку с данными
            parts = line.split()
            if len(parts) >= 10:
                device = {
                    ATTR_DONGLE_ID: parts[0],  # dongle0, dongle1
                    "group": parts[1],
                    "state": parts[2],
                    "rssi_raw": parts[3],
                    "mode": parts[4],
                    "submode": parts[5],
                    "provider": parts[6],
                    "model": parts[7],
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
    if "discovery_job" in hass.data[DOMAIN][entry.entry_id]:
        hass.data[DOMAIN][entry.entry_id]["discovery_job"]()
    
    # Выгружаем платформы
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok