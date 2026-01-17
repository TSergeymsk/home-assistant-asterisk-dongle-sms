"""Platform for notify integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_set_service_schema

from .const import (
    DOMAIN,
    DATA_ASTERISK_MANAGER,
    DATA_DEVICES,
    ATTR_IMEI,
    ATTR_DONGLE_ID,
    SIGNAL_DEVICE_DISCOVERED,
    SIGNAL_DEVICE_REMOVED,
    ATTR_MESSAGE,
)

_LOGGER = logging.getLogger(__name__)

# Service field names
ATTR_TARGET = "target"

# USSD code pattern: starts with *, ends with #, can contain digits and *
USSD_PATTERN = re.compile(r'^\*[\d\*]+\#$')


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up notify platform from ConfigEntry."""
    data = hass.data[DOMAIN][entry.entry_id]
    manager = data[DATA_ASTERISK_MANAGER]
    devices = data[DATA_DEVICES]

    # Create services for existing devices
    for imei, device_info in devices.items():
        await _create_dongle_service(hass, manager, device_info, entry.entry_id)

    # Handlers for device updates
    @callback
    async def handle_device_discovered(device_info):
        """Add service for new device."""
        await _create_dongle_service(hass, manager, device_info, entry.entry_id)
        _LOGGER.info("Added notify service for device: %s", device_info[ATTR_IMEI])

    @callback
    async def handle_device_removed(imei):
        """Remove service for device."""
        await _remove_dongle_service(hass, imei)
        _LOGGER.info("Removed notify service for device: %s", imei)

    # Subscribe to signals
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


async def _create_dongle_service(
    hass: HomeAssistant, 
    manager, 
    device_info: dict[str, Any], 
    entry_id: str
):
    """Create unified notification service for a dongle."""
    imei = device_info[ATTR_IMEI]
    dongle_id = device_info[ATTR_DONGLE_ID]
    
    # Service name: notify.asterisk_<IMEI>
    service_name = f"asterisk_{imei}"

    # Schema for the unified service
    service_schema = vol.Schema({
        vol.Required(ATTR_TARGET): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
    })

    # Unified service handler
    async def async_unified_service(call: ServiceCall):
        """Handle unified SMS/USSD sending."""
        target = call.data.get(ATTR_TARGET)
        message = call.data.get(ATTR_MESSAGE)

        if not target:
            _LOGGER.error("Target is required")
            return
        
        # Check if target is a USSD code
        is_ussd = USSD_PATTERN.match(target.strip())
        
        if is_ussd:
            # USSD mode: target is USSD code, message is ignored
            _LOGGER.debug("Detected USSD code: %s", target)
            
            # Log that we're ignoring message field
            if message:
                _LOGGER.debug("Ignoring message field for USSD: %s", message)
            
            # Create USSD command
            command = f"dongle ussd {dongle_id} {target}"
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
                _LOGGER.info("USSD request sent via %s: %s", dongle_id, target)
        
        else:
            # SMS mode: target is phone number, message is SMS text
            _LOGGER.debug("Detected phone number: %s", target)
            
            if not message:
                _LOGGER.error("Message is required for SMS")
                return

            # Create SMS command
            command = f"dongle sms {dongle_id} {target} {message}"
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
                _LOGGER.info("SMS sent to %s via %s", target, dongle_id)

    # Register service in Home Assistant
    hass.services.async_register(
        domain="notify",
        service=service_name,
        service_func=async_unified_service,
        schema=service_schema,
    )

    # Set service schema for UI display
    ui_schema = {
        "description": f"Send SMS or USSD via {dongle_id} (IMEI: {imei})",
        "fields": {
            ATTR_TARGET: {
                "name": "Target",
                "description": "Phone number for SMS or USSD code (e.g., *100#) for USSD",
                "required": True,
                "selector": {"text": {}}
            },
            ATTR_MESSAGE: {
                "name": "Message",
                "description": "Text of the SMS message (ignored for USSD)",
                "required": True,
                "selector": {"text": {}}
            }
        }
    }

    # Explicitly set schema for UI
    await async_set_service_schema(hass, "notify", service_name, ui_schema)

    # Save service information for removal
    if "notify_services" not in hass.data[DOMAIN][entry_id]:
        hass.data[DOMAIN][entry_id]["notify_services"] = {}
    
    hass.data[DOMAIN][entry_id]["notify_services"][imei] = service_name

    _LOGGER.info("Created unified notify service for device %s: %s", dongle_id, service_name)


async def _remove_dongle_service(hass: HomeAssistant, imei: str):
    """Remove notification service for a device."""
    # Find entry_id for this device
    for entry_id in hass.data.get(DOMAIN, {}):
        entry_data = hass.data[DOMAIN].get(entry_id, {})
        if "notify_services" in entry_data and imei in entry_data["notify_services"]:
            service_name = entry_data["notify_services"][imei]
            
            try:
                # Remove service
                hass.services.async_remove("notify", service_name)
                
                # Remove from list
                del hass.data[DOMAIN][entry_id]["notify_services"][imei]
                
                _LOGGER.info("Removed notify service for device IMEI: %s", imei)
            except (ValueError, KeyError) as err:
                _LOGGER.warning("Error removing service for %s: %s", imei, err)
            break


async def async_unload_entry_notify(hass: HomeAssistant, entry: ConfigEntry):
    """Unload notify services when configuration entry is unloaded."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        if "notify_services" in hass.data[DOMAIN][entry.entry_id]:
            services = hass.data[DOMAIN][entry.entry_id]["notify_services"]
            for imei in list(services.keys()):
                await _remove_dongle_service(hass, imei)
        _LOGGER.info("All notify services for Asterisk Dongle unloaded")