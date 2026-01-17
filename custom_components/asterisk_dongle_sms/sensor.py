"""Platform for sensor integration."""
import logging
import re
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_PORT
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .notify import AsteriskManager

_LOGGER = logging.getLogger(__name__)

# Конфигурационные константы - должны совпадать с notify.py
CONF_ADDRESS = 'address'
CONF_USER = 'user'
CONF_DONGLE = 'dongle'
CONF_SCAN_INTERVAL = 'scan_interval'

# Дополнительные для сенсора
DEFAULT_NAME = "Asterisk Dongle Signal"
DEFAULT_SCAN_INTERVAL = 60

# Схема с поддержкой строки и числа для scan_interval
PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_DONGLE): cv.string,
        vol.Required(CONF_ADDRESS): cv.string,
        vol.Required(CONF_PORT): cv.port,
        vol.Required(CONF_USER): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): 
            vol.Any(cv.positive_int, cv.string),
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the sensor platform."""
    address = config[CONF_ADDRESS]
    port = config[CONF_PORT]
    user = config[CONF_USER]
    password = config[CONF_PASSWORD]
    dongle = config[CONF_DONGLE]
    name = config[CONF_NAME]
    
    # Обрабатываем scan_interval
    scan_interval = config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    
    # Преобразуем в int, если это строка
    if isinstance(scan_interval, str):
        try:
            scan_interval = int(scan_interval)
        except ValueError:
            _LOGGER.warning(
                "Invalid scan_interval value: %s, using default: %s",
                scan_interval, DEFAULT_SCAN_INTERVAL
            )
            scan_interval = DEFAULT_SCAN_INTERVAL
    
    # Гарантируем, что это int
    if not isinstance(scan_interval, int):
        _LOGGER.warning(
            "scan_interval is not an integer: %s, using default: %s",
            type(scan_interval).__name__, DEFAULT_SCAN_INTERVAL
        )
        scan_interval = DEFAULT_SCAN_INTERVAL
    
    # Проверяем, что значение положительное
    if scan_interval <= 0:
        _LOGGER.warning(
            "scan_interval must be positive: %s, using default: %s",
            scan_interval, DEFAULT_SCAN_INTERVAL
        )
        scan_interval = DEFAULT_SCAN_INTERVAL
    
    # Создаем менеджер AMI
    ami = AsteriskManager(address, port, user, password)
    
    # Создаем сенсор
    sensor = AsteriskDongleSignalSensor(ami, dongle, name, scan_interval)
    
    # Добавляем сенсор в Home Assistant
    add_entities([sensor])
    
    _LOGGER.debug("Asterisk dongle signal sensor initialized for %s", dongle)


class AsteriskDongleSignalSensor(SensorEntity):
    """Representation of a Dongle Signal Sensor."""

    def __init__(self, ami, dongle, name, scan_interval):
        """Initialize the sensor."""
        self._ami = ami
        self._dongle = dongle
        self._name = name
        self._scan_interval = scan_interval
        self._state = None
        self._attributes = {}
        self._available = True
        self._unit_of_measurement = "dBm"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"asterisk_dongle_signal_{self._dongle}"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def device_class(self):
        """Return the device class."""
        return "signal_strength"

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        return self._attributes

    @property
    def available(self):
        """Return True if entity is available."""
        return self._available

    def update(self):
        """Fetch new state data for the sensor."""
        try:
            # Отправляем команду для получения состояния dongle
            command = f"dongle show device state {self._dongle}"
            response = self._ami.send_command(command)
            
            if response is None:
                _LOGGER.error("No response from Asterisk for dongle %s", self._dongle)
                self._available = False
                self._state = None
                return
            
            # Парсим ответ
            data = self._parse_dongle_state(response)
            
            if not data:
                _LOGGER.error("Failed to parse response for dongle %s", self._dongle)
                self._available = False
                self._state = None
                return
            
            # Извлекаем уровень сигнала в dBm
            rssi_str = data.get("rssi", "")
            _LOGGER.debug("Raw RSSI string: %s", rssi_str)
            
            # Ищем значение в dBm в строке "25, -63 dBm"
            match = re.search(r"(-?\d+)\s*dBm", rssi_str)
            if match:
                self._state = int(match.group(1))
                self._unit_of_measurement = "dBm"
                _LOGGER.debug("Extracted dBm value: %s", self._state)
            else:
                # Если не нашли dBm, попробуем извлечь сырое значение
                match_raw = re.search(r"(\d+)\s*,\s*", rssi_str)
                if match_raw:
                    raw_value = int(match_raw.group(1))
                    # Конвертируем условные единицы в dBm (примерная формула)
                    if raw_value <= 31:
                        self._state = (raw_value * 2) - 113
                        self._unit_of_measurement = "dBm"
                        _LOGGER.debug("Converted raw RSSI %s to dBm: %s", raw_value, self._state)
                    else:
                        self._state = raw_value
                        self._unit_of_measurement = "level"
                else:
                    self._state = None
                    self._unit_of_measurement = None
            
            # Сохраняем другие атрибуты
            self._attributes = {
                "device": self._dongle,
                "raw_rssi": rssi_str,
                "device_state": data.get("state", ""),
                "provider": data.get("provider_name", ""),
                "registration": data.get("gsm_registration_status", ""),
                "mode": data.get("mode", ""),
                "submode": data.get("submode", ""),
                "imei": data.get("imei", ""),
                "imsi": data.get("imsi", ""),
                "model": data.get("model", ""),
                "firmware": data.get("firmware", ""),
                "lac": data.get("location_area_code", ""),
                "cell_id": data.get("cell_id", ""),
                "audio_port": data.get("audio", ""),
                "data_port": data.get("data", ""),
                "voice_support": data.get("voice", ""),
                "sms_support": data.get("sms", ""),
            }
            
            self._available = True
            _LOGGER.debug("Successfully updated sensor for dongle %s", self._dongle)
            
        except Exception as e:
            _LOGGER.error("Error updating dongle signal for %s: %s", self._dongle, str(e))
            self._available = False
            self._state = None

    def _parse_dongle_state(self, response):
        """Parse dongle state response."""
        data = {}
        for line in response.splitlines():
            if ":" in line and "--" not in line and "===" not in line:
                key, value = line.split(":", 1)
                key = key.strip().lower().replace(" ", "_")
                data[key] = value.strip()
        return data

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        if self._state is None:
            return "mdi:signal-off"
        
        try:
            signal = int(self._state)
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
