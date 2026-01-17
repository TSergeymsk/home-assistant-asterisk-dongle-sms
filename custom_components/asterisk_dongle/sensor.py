"""Platform for sensor integration."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
        sensor = AsteriskDongleSignalSensor(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        entities.append(sensor)
    
    async_add_entities(entities, update_before_add=True)
    
    # Регистрируем обработчики для новых устройств
    @callback
    async def async_add_sensor(device_info):
        """Добавить сенсор для нового устройства."""
        new_sensor = AsteriskDongleSignalSensor(
            hass=hass,
            manager=manager,
            device_info=device_info,
            entry_id=entry.entry_id
        )
        async_add_entities([new_sensor], update_before_add=True)
        _LOGGER.info("Added new sensor for device with IMEI: %s", device_info[ATTR_IMEI])
    
    @callback
    def async_remove_sensor(imei):
        """Удалить сенсор для устройства."""
        # Находим и удаляем сущность
        for entity in entities:
            if hasattr(entity, '_attr_unique_id') and imei in entity.unique_id:
                hass.async_create_task(entity.async_remove())
                _LOGGER.info("Removed sensor for device with IMEI: %s", imei)
                break
    
    # Подписываемся на сигналы
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_DISCOVERED}_{entry.entry_id}",
        async_add_sensor
    )
    
    async_dispatcher_connect(
        hass,
        f"{SIGNAL_DEVICE_REMOVED}_{entry.entry_id}",
        async_remove_sensor
    )


class AsteriskDongleSignalSensor(SensorEntity):
    """Сенсор уровня сигнала dongle."""
    
    _attr_has_entity_name = False  # Используем собственное имя без автоматического префикса
    _attr_icon = "mdi:signal"
    
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
        
        # Уникальный ID для entity_id: sensor.dongle_<IMEI>_cell_signal
        imei = device_info[ATTR_IMEI]
        self._attr_unique_id = f"dongle_{imei}_cell_signal"
        
        # Имя сенсора (отображаемое в интерфейсе)
        self._attr_name = f"Cell Signal {imei}"
        
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
        imei = self._device_info[ATTR_IMEI]
        
        # Определяем производителя по модели
        model = self._device_info.get("model", "").upper()
        manufacturer = "Huawei"  # По умолчанию Huawei для большинства донглов
        
        if "ZTE" in model or model.startswith("ZTE"):
            manufacturer = "ZTE"
        elif "SIERRA" in model:
            manufacturer = "Sierra Wireless"
        elif "NOKIA" in model:
            manufacturer = "Nokia"
        elif "ALCATEL" in model:
            manufacturer = "Alcatel"
        
        return {
            "identifiers": {(DOMAIN, imei)},
            "name": f"Dongle {imei}",
            "manufacturer": manufacturer,
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
            "provider": self._device_info.get("provider", ""),
            "state": self._device_info.get("state", ""),
            "device_model": self._device_info.get("model", ""),
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
            dongle_id = self._device_info[ATTR_DONGLE_ID]
            command = f"dongle show device state {dongle_id}"
            response = await self.hass.async_add_executor_job(
                self._manager.send_command, command
            )
            
            if not response:
                self._available = False
                _LOGGER.warning("No response for device %s", dongle_id)
                return
            
            # Парсим ответ
            data = self._parse_dongle_state(response)
            
            if not data:
                self._available = False
                _LOGGER.warning("Could not parse response for device %s", dongle_id)
                return
            
            # Извлекаем уровень сигнала
            rssi_str = data.get("rssi", "")
            signal_value = self._extract_signal_value(rssi_str)
            self._attr_native_value = signal_value
            
            # Сохраняем атрибуты
            self._attributes = {
                "raw_rssi": rssi_str,
                "provider": data.get("provider_name", self._device_info.get("provider", "")),
                "registration": data.get("gsm_registration_status", ""),
                "network_mode": data.get("mode", self._device_info.get("mode", "")),
                "submode": data.get("submode", self._device_info.get("submode", "")),
                "lac": data.get("location_area_code", ""),
                "cell_id": data.get("cell_id", ""),
                "signal_quality": self._calculate_signal_quality(signal_value),
            }
            
            self._last_update = datetime.now().isoformat()
            self._available = True
            
            _LOGGER.debug("Successfully updated sensor for device %s", dongle_id)
            
        except Exception as e:
            _LOGGER.error("Error updating sensor for %s: %s", 
                         self._device_info[ATTR_DONGLE_ID], str(e))
            self._available = False

    def _extract_signal_value(self, rssi_str: str):
        """Извлекает значение сигнала из строки."""
        if not rssi_str:
            return None
        
        # Пробуем извлечь значение в dBm
        match = re.search(r"(-?\d+)\s*dBm", rssi_str)
        if match:
            return int(match.group(1))
        
        # Пробуем извлечь сырое значение (например: "31, -51 dBm")
        match_raw = re.search(r"(\d+)\s*,\s*", rssi_str)
        if match_raw:
            raw_value = int(match_raw.group(1))
            # Конвертируем сырое значение в dBm
            return (raw_value * 2) - 113
        
        return None

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
                
            if line == "--END COMMAND--" or (line == "" and in_output_block):
                in_output_block = False
                continue
                
            if in_output_block and ":" in line:
                key, value = line.split(":", 1)
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