"""Константы для интеграции Asterisk Dongle."""
from typing import Final

DOMAIN: Final = "asterisk_dongle"

# Конфигурационные ключи
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Значения по умолчанию
DEFAULT_PORT: Final = 5038
DEFAULT_SCAN_INTERVAL: Final = 60
DISCOVERY_INTERVAL: Final = 3600  # 1 час

# Ключи для hass.data
DATA_ASTERISK_MANAGER: Final = "asterisk_manager"
DATA_DEVICE_DISCOVERY: Final = "device_discovery"
DATA_DEVICES: Final = "devices"
DATA_CONFIG_ENTRY: Final = "config_entry"

# Уникальные идентификаторы
ATTR_IMEI: Final = "imei"
ATTR_DONGLE_ID: Final = "dongle_id"
ATTR_MODEL: Final = "model"

# Типы платформ
PLATFORM_NOTIFY: Final = "notify"
PLATFORM_SENSOR: Final = "sensor"