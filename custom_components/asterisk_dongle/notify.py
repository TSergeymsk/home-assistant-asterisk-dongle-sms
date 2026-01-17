"""Platform for notify integration."""
from __future__ import annotations

import logging
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

# Service field names - target is for phone number (SMS) or USSD code (USSD)
ATTR_TARGET = "target"


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
        await _create_dongle_services(hass, manager, device_info, entry.entry_id)

    # Handlers for device updates
    @callback
    async def handle_device_discovered(device_info):
        """Add services for new device."""
        await _create_dongle_services(hass, manager, device_info, entry.entry_id)
        _LOGGER.info("Added notify services for device: %s", device_info[ATTR_IMEI])

    @callback
    async def handle_device_removed(imei):
        """Remove services for device."""
        await _remove_dongle_services(hass, imei)
        _LOGGER.info("Removed notify services for device: %s", imei)

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


async def _create_dongle_services(
    hass: HomeAssistant, 
    manager, 
    device_info: dict[str, Any], 
    entry_id: str
):
    """Create notification services for a dongle."""
    imei = device_info[ATTR_IMEI]
    dongle_id = device_info[ATTR_DONGLE_ID]
    imei_short = imei[-6:] if len(imei) >= 6 else imei
    
    # Service names
    service_sms = f"asterisk_dongle_sms_{imei_short}"
    service_ussd = f"asterisk_dongle_ussd_{imei_short}"

    # Different schemas for SMS and USSD
    sms_schema = vol.Schema({
        vol.Required(ATTR_TARGET): cv.string,  # Phone number
        vol.Required(ATTR_MESSAGE): cv.string,  # SMS message
    })

    ussd_schema = vol.Schema({
        vol.Required(ATTR_TARGET): cv.string,  # USSD code
    })

    # Register SMS service
    async def async_sms_service(call: ServiceCall):
        """Handle SMS sending."""
        target = call.data.get(ATTR_TARGET)  # Phone number
        message = call.data.get(ATTR_MESSAGE)  # SMS message

        if not target:
            _LOGGER.error("Target (phone number) is required for SMS")
            return
        
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

    # Register USSD service
    async def async_ussd_service(call: ServiceCall):
        """Handle USSD sending."""
        target = call.data.get(ATTR_TARGET)  # USSD code

        if not target:
            _LOGGER.error("Target (USSD code) is required for USSD")
            return

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

    # Register services in Home Assistant with different schemas
    hass.services.async_register(
        domain="notify",
        service=service_sms,
        service_func=async_sms_service,
        schema=sms_schema,
    )

    hass.services.async_register(
        domain="notify",
        service=service_ussd,
        service_func=async_ussd_service,
        schema=ussd_schema,
    )

    # Set service schemas for UI display
    ui_sms_schema = {
        "description": f"Send SMS via {dongle_id} ({imei_short})",
        "fields": {
            ATTR_TARGET: {
                "name": "Phone Number",
                "description": "Phone number to send SMS to",
                "required": True,
                "selector": {"text": {}}
            },
            ATTR_MESSAGE: {
                "name": "Message",
                "description": "Text of the SMS message",
                "required": True,
                "selector": {"text": {}}
            }
        }
    }

    ui_ussd_schema = {
        "description": f"Send USSD request via {dongle_id} ({imei_short})",
        "fields": {
            ATTR_TARGET: {
                "name": "USSD Code",
                "description": "USSD code to send (e.g., *100#, *102#)",
                "required": True,
                "selector": {"text": {}}
            }
        }
    }

    # Explicitly set schemas for BOTH services
    await async_set_service_schema(hass, "notify", service_sms, ui_sms_schema)
    await async_set_service_schema(hass, "notify", service_ussd, ui_ussd_schema)

    # Save service information for removal
    if "notify_services" not in hass.data[DOMAIN][entry_id]:
        hass.data[DOMAIN][entry_id]["notify_services"] = {}
    
    hass.data[DOMAIN][entry_id]["notify_services"][imei] = {
        "sms": service_sms,
        "ussd": service_ussd
    }

    _LOGGER.info("Created notify services for device %s (IMEI: %s)", dongle_id, imei)


async def _remove_dongle_services(hass: HomeAssistant, imei: str):
    """Remove notification services for a device."""
    # Find entry_id for this device
    for entry_id in hass.data.get(DOMAIN, {}):
        entry_data = hass.data[DOMAIN].get(entry_id, {})
        if "notify_services" in entry_data and imei in entry_data["notify_services"]:
            services = entry_data["notify_services"][imei]
            
            try:
                # Remove SMS service
                hass.services.async_remove("notify", services["sms"])
                # Remove USSD service
                hass.services.async_remove("notify", services["ussd"])
                
                # Remove from list
                del hass.data[DOMAIN][entry_id]["notify_services"][imei]
                
                _LOGGER.info("Removed notify services for device IMEI: %s", imei)
            except (ValueError, KeyError) as err:
                _LOGGER.warning("Error removing services for %s: %s", imei, err)
            break


async def async_unload_entry_notify(hass: HomeAssistant, entry: ConfigEntry):
    """Unload notify services when configuration entry is unloaded."""
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        if "notify_services" in hass.data[DOMAIN][entry.entry_id]:
            services = hass.data[DOMAIN][entry.entry_id]["notify_services"]
            for imei in list(services.keys()):
                await _remove_dongle_services(hass, imei)
        _LOGGER.info("All notify services for Asterisk Dongle unloaded")