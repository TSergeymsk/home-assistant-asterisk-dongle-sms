"""Config flow for Asterisk Dongle integration."""
from __future__ import annotations

import logging
import socket
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL
from .manager import AsteriskManager

_LOGGER = logging.getLogger(__name__)

# Шаг 1: Данные подключения
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Optional("port", default=DEFAULT_PORT): int,
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): int,
    }
)


def validate_connection(data: dict[str, Any]) -> dict[str, Any]:
    """Проверка подключения к AMI (синхронная функция)."""
    _LOGGER.debug("Validating connection to %s:%s", data["host"], data["port"])
    
    try:
        # Создаем временный менеджер для проверки
        manager = AsteriskManager(
            data["host"],
            data["port"],
            data["username"],
            data["password"]
        )
        
        # Тестируем подключение
        success, message = manager.test_connection()
        
        if not success:
            _LOGGER.error("Connection test failed: %s", message)
            if "Authentication" in message or "auth" in message.lower():
                raise InvalidAuth(message)
            else:
                raise CannotConnect(message)
        
        _LOGGER.debug("Connection validated successfully: %s", message)
        
        # Пробуем получить информацию о донглах
        response = manager.send_command("dongle show devices")
        if response and "Response: Error" not in response:
            _LOGGER.debug("Dongle command successful, found devices")
        else:
            _LOGGER.warning("Could not get dongle devices (might be OK if no dongles)")
        
        # Закрываем соединение
        manager.disconnect()
        
        return {"title": f"Asterisk AMI ({data['host']}:{data['port']})"}
        
    except socket.timeout:
        _LOGGER.error("Connection timeout")
        raise CannotConnect("Connection timeout")
    except ConnectionRefusedError:
        _LOGGER.error("Connection refused")
        raise CannotConnect("Connection refused")
    except socket.gaierror as e:
        _LOGGER.error("Invalid hostname or IP: %s", e)
        raise CannotConnect("Invalid hostname or IP address")
    except Exception as e:
        _LOGGER.exception("Unexpected error during validation: %s", str(e))
        raise CannotConnect(f"Unexpected error: {str(e)}")

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Конфигурационный поток для Asterisk Dongle."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Шаг настройки пользователем."""
        errors = {}
        
        if user_input is not None:
            try:
                # Проверяем подключение в отдельном потоке
                info = await self.hass.async_add_executor_job(
                    validate_connection, user_input
                )
                
                # Создаем уникальный ID на основе хоста и порта
                await self.async_set_unique_id(
                    f"asterisk_dongle_{user_input['host']}:{user_input['port']}"
                )
                self._abort_if_unique_id_configured()
                
                # Создаем запись конфигурации
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input
                )
                
            except CannotConnect as err:
                _LOGGER.error("Cannot connect: %s", err)
                errors["base"] = "cannot_connect"
            except InvalidAuth as err:
                _LOGGER.error("Invalid auth: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"
        
        # Показываем форму
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "scan_interval": str(DEFAULT_SCAN_INTERVAL)
            }
        )


class CannotConnect(HomeAssistantError):
    """Ошибка подключения к серверу."""


class InvalidAuth(HomeAssistantError):
    """Ошибка аутентификации."""