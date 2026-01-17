"""The Asterisk Dongle integration."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import device_registry as dr

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
    
    _LOGGER.info("Setting up Asterisk Dongle integration for %s:%s", 
                 entry.data["host"], entry.data["port"])
    
    # Создаем менеджер AMI
    manager = AsteriskManager(
        entry.data["host"],
        entry.data["port"],
        entry.data["username"],
        entry.data["password"]
    )
    
    # Проверяем подключение
    try:
        test_response = await hass.async_add_executor_job(
            manager.send_command, "core show version"
        )
        if not test_response or "Response: Error" in test_response:
            _LOGGER.error("Failed to connect to Asterisk AMI")
            return False
    except Exception as e:
        _LOGGER.error("Error testing AMI connection: %s", e)
        return False
    
    # Сохраняем данные
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CONFIG_ENTRY: entry,
        DATA_ASTERISK_MANAGER: manager,
        DATA_DEVICES: {},
    }
    
    # Создаем главное устройство для интеграции
    await _create_main_device(hass, entry)
    
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


async def _create_main_device(hass: HomeAssistant, entry: ConfigEntry):
    """Создает главное устройство для интеграции."""
    device_registry = dr.async_get(hass)
    
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Asterisk AMI ({entry.data['host']})",
        manufacturer="Asterisk",
        model="AMI Gateway",
        sw_version="1.0",
    )


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
            _LOGGER.debug("No response from Asterisk for device discovery")
            return
        
        _LOGGER.debug("Raw response from 'dongle show devices':\n%s", response)
        
        # Парсим ответ
        discovered_devices = _parse_devices_response(response)
        _LOGGER.info("Discovered %d devices", len(discovered_devices))
        
        if not discovered_devices:
            _LOGGER.warning("No devices found in response")
            return
        
        # Создаем словарь для быстрого доступа по IMEI
        new_devices = {}
        for device in discovered_devices:
            imei = device[ATTR_IMEI]
            dongle_id = device[ATTR_DONGLE_ID]
            
            if not imei or imei == "N/A":
                _LOGGER.warning("Device %s has no IMEI, skipping", dongle_id)
                continue
                
            new_devices[imei] = device
            
            # Если устройство новое - отправляем сигнал
            if imei not in current_devices:
                _LOGGER.info("New device discovered: %s (IMEI: %s, Model: %s)", 
                           dongle_id, imei, device.get("model", "Unknown"))
                
                # Создаем устройство в реестре устройств
                await _create_dongle_device(hass, entry, device)
                
                # Отправляем сигнал для создания сущностей
                async_dispatcher_send(
                    hass, 
                    f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}", 
                    device
                )
        
        # Проверяем удаленные устройства
        for imei, device_info in list(current_devices.items()):
            if imei not in new_devices:
                dongle_id = device_info[ATTR_DONGLE_ID]
                _LOGGER.info("Device removed: %s (IMEI: %s)", dongle_id, imei)
                async_dispatcher_send(
                    hass,
                    f"{SIGNAL_DEVICE_REMOVED}_{entry.entry_id}",
                    imei
                )
        
        # Обновляем список устройств
        data[DATA_DEVICES] = new_devices
        
    except Exception as e:
        _LOGGER.error("Error discovering devices: %s", e, exc_info=True)


async def _create_dongle_device(hass: HomeAssistant, entry: ConfigEntry, device_info: dict):
    """Создает устройство донгла в реестре устройств."""
    device_registry = dr.async_get(hass)
    
    imei = device_info[ATTR_IMEI]
    
    # Определяем производителя по модели
    model = device_info.get("model", "").upper()
    
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, imei)},
        name=f"Dongle {imei}",  # Имя устройства: Dongle <IMEI>
        manufacturer = device_info.get("manufacturer", "Unknown"),
        model=device_info.get("model", "Unknown"),
        sw_version=device_info.get("firmware", "Unknown"),
        via_device=(DOMAIN, entry.entry_id),
    )

def _parse_devices_response(response: str) -> list[dict[str, Any]]:
    """Парсинг ответа 'dongle show devices' из AMI."""
    devices = []
    lines = response.split('\n')
    in_output_block = False

    for line in lines:
        line = line.strip()

        # 1. Находим начало блока с выводом команды
        if not in_output_block and "Command output follows" in line:
            in_output_block = True
            continue
        if not in_output_block:
            continue  # Пропускаем строки до начала вывода

        # 2. Пропускаем строку-заголовок таблицы (первая строка после маркера начинается с 'Output: ID')
        if line.startswith("Output: ID"):
            continue  # Это заголовок таблицы, пропускаем

        # 3. Конец блока данных (пустая строка или маркер конца)
        if line == "" or line == "--END COMMAND--":
            break

        # 4. Парсим строки, которые начинаются с 'Output: ' (это строки с данными)
        if line.startswith("Output: "):
            # УДАЛЯЕМ префикс 'Output: ' перед обработкой
            data_line = line[8:].strip()  # Убираем "Output: " и лишние пробелы
            _LOGGER.debug("Parsing data line: %s", data_line)

            # Разделяем строку на части, учитывая, что пробелов может быть много
            # Используем split без аргументов, чтобы разделить по любым пробельным символам
            parts = data_line.split()
            
            if len(parts) >= 10:
                try:
                    device = {
                        ATTR_DONGLE_ID: parts[0],        # dongle0
                        "group": parts[1],               # 0
                        "state": parts[2],               # Free
                        "rssi_raw": parts[3],            # 26
                        "mode": parts[4],                # 3
                        "submode": parts[5],             # 3
                        "provider": parts[6],            # beeline
                        "model": parts[7],               # E173
                        "firmware": parts[8],            # 11.126.85.00.209
                        ATTR_IMEI: parts[9],             # 357291041830484
                        "imsi": parts[10] if len(parts) > 10 else "",          # 250997278767099
                        "number": parts[11] if len(parts) > 11 else "Unknown", # Unknown
                    }
                    devices.append(device)
                    _LOGGER.debug("Successfully parsed device: %s (IMEI: %s)", 
                                 device[ATTR_DONGLE_ID], device[ATTR_IMEI])
                except IndexError as e:
                    _LOGGER.warning("Error parsing line '%s': %s", data_line, e)
            else:
                _LOGGER.warning("Skipping line '%s', not enough fields (%d)", data_line, len(parts))

    _LOGGER.info("Successfully parsed %d device(s) from AMI response", len(devices))
    return devices

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка конфигурационной записи."""
    # Останавливаем discovery
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        if "discovery_job" in hass.data[DOMAIN][entry.entry_id]:
            hass.data[DOMAIN][entry.entry_id]["discovery_job"]()
        
        # Отключаем менеджер
        if DATA_ASTERISK_MANAGER in hass.data[DOMAIN][entry.entry_id]:
            manager = hass.data[DOMAIN][entry.entry_id][DATA_ASTERISK_MANAGER]
            await hass.async_add_executor_job(manager.disconnect)
    
    # Выгружаем платформы
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    
    if unload_ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    
    return unload_ok