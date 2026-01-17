"""Config flow for Asterisk Dongle integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL
from .notify import AsteriskManager

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


async def validate_connection(data: dict[str, Any]) -> dict[str, Any]:
    """Проверка подключения к AMI."""
    try:
        # Создаем временный менеджер для проверки
        manager = AsteriskManager(
            data["host"],
            data["port"],
            data["username"],
            data["password"]
        )
        
        # Пробуем выполнить простую команду
        response = manager.send_command("core show version")
        if not response or "Response: Error" in response:
            raise CannotConnect
            
        return {"title": f"Asterisk AMI ({data['host']})"}
        
    except Exception as e:
        _LOGGER.error("Connection validation failed: %s", e)
        raise CannotConnect from e


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Конфигурационный поток для Asterisk Dongle."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Шаг настройки пользователем."""
        errors = {}
        
        if user_input is not None:
            try:
                # Проверяем подключение
                info = await self.hass.async_add_executor_job(
                    validate_connection, user_input
                )
                
                # Создаем уникальный ID на основе хоста и порта
                await self.async_set_unique_id(
                    f"{user_input['host']}:{user_input['port']}"
                )
                self._abort_if_unique_id_configured()
                
                # Создаем запись конфигурации
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input
                )
                
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
        
        # Показываем форму с ошибками или впервые
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