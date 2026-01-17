"""Platform for sensor integration."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    """Настройка сенсоров из ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    devices = data[DATA_DEVICES]
    
    # Создаем начальные сенсоры
    entities = []
    for imei, device_info in devices.items():
        entities.append(
            AsteriskDongleSignalSensor(
                hass=hass,
                manager=manager,
                device_info=device_info,
                entry_id=entry.entry_id
            )
        )
    
    async_add_entities(entities, update_before_add=False)
    
    # Регистрируем обработчики для новых устройств
    async def async_add_sensor(device_info):
        """Добавить сенсор для нового устройства."""
        new_sensor = AsteriskDongleSignalSensor(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        async_add_entities([new_sensor])
        _LOGGER.debug("Added new sensor for device: %s", device_info[ATTR_IMEI])
    
    # Подписываемся на сигналы
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}",
        async_add_sensor
    )


class AsteriskDongleSignalSensor(SensorEntity):
    """Сенсор уровня сигнала dongle."""
    
    _attr_has_entity_name = True
    
    def __init__(
        self,
        hass: HomeAssistant,
        manager,
        device_info: dict[str, Any],
        entry_id: str
    ):
        """Инициализация сенсора."""
        self.hass = hass
        self._manager = manager
        self._device_info = device_info
        self._entry_id = entry_id
        
        # Уникальный ID
        self._attr_unique_id = f"{entry_id}_{device_info[ATTR_IMEI]}_signal"
        
        # Имя сенсора
        imei_short = device_info[ATTR_IMEI][-6:]
        self._attr_name = f"Cell Signal {imei_short}"
        
        # Атрибуты сенсора
        self._attr_device_class = "signal_strength"
        self._attr_native_unit_of_measurement = "dBm"
        self._attr_should_poll = True
        
        # Состояние
        self._attr_native_value = None
        self._attributes = {}
        self._available = True
        
        # История обновлений
        self._last_update = None

    @property
    def device_info(self):
        """Возвращает информацию об устройстве."""
        return {
            "identifiers": {(DOMAIN, self._device_info[ATTR_IMEI])},
            "name": f"Dongle {self._device_info[ATTR_DONGLE_ID]}",
            "manufacturer": self._device_info.get("model", "Unknown"),
            "model": self._device_info.get("model", "Unknown"),
            "sw_version": self._device_info.get("firmware", "Unknown"),
            "via_device": (DOMAIN, self._entry_id),
        }

    @property
    def extra_state_attributes(self):
        """Возвращает дополнительные атрибуты."""
        attrs = self._attributes.copy()
        attrs.update({
            "imei": self._device_info[ATTR_IMEI],
            "dongle_id": self._device_info[ATTR_DONGLE_ID],
            "last_update": self._last_update,
        })
        return attrs

    @property
    def available(self):
        """Возвращает доступность сенсора."""
        return self._available

    async def async_update(self):
        """Обновление данных сенсора."""
        try:
            # Получаем детальную информацию о донгле
            command = f"dongle show device state {self._device_info[ATTR_DONGLE_ID]}"
            response = await self.hass.async_add_executor_job(
                self._manager.send_command, command
            )
            
            if not response:
                self._available = False
                return
            
            # Парсим ответ
            data = self._parse_dongle_state(response)
            
            if not data:
                self._available = False
                return
            
            # Извлекаем уровень сигнала
            rssi_str = data.get("rssi", "")
            match = re.search(r"(-?\d+)\s*dBm", rssi_str)
            if match:
                self._attr_native_value = int(match.group(1))
            else:
                match_raw = re.search(r"(\d+)\s*,\s*", rssi_str)
                if match_raw:
                    raw_value = int(match_raw.group(1))
                    self._attr_native_value = (raw_value * 2) - 113
                else:
                    self._attr_native_value = None
            
            # Сохраняем атрибуты
            self._attributes = {
                "raw_rssi": rssi_str,
                "provider": data.get("provider_name", ""),
                "registration": data.get("gsm_registration_status", ""),
                "network_mode": data.get("mode", ""),
                "submode": data.get("submode", ""),
                "lac": data.get("location_area_code", ""),
                "cell_id": data.get("cell_id", ""),
                "signal_quality": self._calculate_signal_quality(self._attr_native_value),
            }
            
            self._last_update = datetime.now().isoformat()
            self._available = True
            
        except Exception as e:
            _LOGGER.error("Error updating sensor for %s: %s", 
                         self._device_info[ATTR_IMEI], str(e))
            self._available = False

    def _parse_dongle_state(self, response):
        """Парсинг ответа от dongle."""
        data = {}
        lines = response.split('\n')
        in_output_block = False
        
        for line in lines:
            line = line.strip()
            
            if "Command output follows" in line:
                in_output_block = True
                continue
                
            if line == "" and in_output_block:
                in_output_block = False
                continue
                
            if in_output_block and line.startswith("Output:"):
                content = line[7:].strip()
                if ":" in content:
                    key, value = content.split(":", 1)
                    key = key.strip().lower().replace(" ", "_")
                    data[key] = value.strip()
        
        return data

    def _calculate_signal_quality(self, signal_db):
        """Рассчитывает качество сигнала."""
        if signal_db is None:
            return "Unknown"
        
        try:
            signal = int(signal_db)
            if signal >= -70:
                return "Excellent"
            elif signal >= -85:
                return "Good"
            elif signal >= -100:
                return "Fair"
            else:
                return "Poor"
        except (ValueError, TypeError):
            return "Unknown"

    @property
    def icon(self):
        """Возвращает иконку."""
        if self._attr_native_value is None:
            return "mdi:signal-off"
        
        try:
            signal = int(self._attr_native_value)
            if signal >= -70:
                return "mdi:signal"
            elif signal >= -85:
                return "mdi:signal-2g"
            elif signal >= -100:
                return "mdi:signal-1g"
            else:
                return "mdi:signal-off"
        except (ValueError, TypeError):
            return "mdi:signal"