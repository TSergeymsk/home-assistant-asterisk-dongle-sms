"""
Asterisk Dongle SMS send platform for notify component.
"""
import logging

import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_TARGET, BaseNotificationService, PLATFORM_SCHEMA)
import homeassistant.helpers.config_validation as cv

CONF_DONGLE = 'dongle'
CONF_ADDRESS = 'address'
CONF_PORT = 'port'
CONF_USER = 'user'
CONF_PASSWORD = 'password'
CONF_DNGTYPE = 'dngtype'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_DONGLE): cv.string,
    vol.Required(CONF_ADDRESS): cv.string,
    vol.Required(CONF_PORT): cv.port,
    vol.Required(CONF_USER): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_DNGTYPE, default='sms'): vol.In(['sms', 'ussd']),
})

_LOGGER = logging.getLogger(__name__)


def get_service(hass, config, discovery_info=None):
    """Get the Asterisk notification service."""
    dongle = config.get(CONF_DONGLE)
    address = config.get(CONF_ADDRESS)
    port = config.get(CONF_PORT)
    user = config.get(CONF_USER)
    password = config.get(CONF_PASSWORD)
    dngtype = config.get(CONF_DNGTYPE)

    return AsteriskNotificationService(dongle, address, port, user, password, dngtype)


class AsteriskNotificationService(BaseNotificationService):
    """Implementation of a notification service for Asterisk."""

    def __init__(self, dongle, address, port, user, password, dngtype='sms'):
        """Initialize the service."""
        self._dongle = dongle
        self._address = address
        self._port = port
        self._user = user
        self._password = password
        self._dngtype = dngtype

    def send_message(self, message="", **kwargs):
        """Send an SMS or USSD to target users."""
        from asterisk.ami import AMIClient
        from asterisk.ami.action import SimpleAction

        client = AMIClient(address=self._address, port=self._port)
        future = client.login(username=self._user, secret=self._password)
        if future.response.is_error():
            _LOGGER.error("Can't connect to Asterisk AMI: %s", " ".join(str(future.response).splitlines()))
            return

        targets = kwargs.get(ATTR_TARGET)

        if targets is None:
            _LOGGER.error("No SMS/USSD targets, as 'target' is not defined")
            return

        # TODO: add quota per day
        for target in targets:
            _LOGGER.debug("Sending %s to %s", self._dngtype.upper(), target)
            if self._dngtype == 'sms':
                action = SimpleAction(
                    'DongleSendSMS',
                    Device=self._dongle,
                    Number=target,
                    Message=message,
                )
            elif self._dngtype == 'ussd':
                # DongleSendUSSD typically expects a Code (the USSD string); target may be ignored.
                action = SimpleAction(
                    'DongleSendUSSD',
                    Device=self._dongle,
                    USSD=message,
                )
            else:
                _LOGGER.error("Unknown dongle type: %s", self._dngtype)
                client.logoff()
                return

            client.send_action(action, callback=lambda r, t=target: self._on_message(t, r))
            _LOGGER.debug("%s to %s sent", self._dngtype.upper(), target)

        client.logoff()

    def _on_message(self, phone, response):
        if response.is_error():
            _LOGGER.exception("Error sending SMS to %s. Response: %s", phone, " ".join(str(response).splitlines()))
        else:
            _LOGGER.debug("SMS to %s successful", phone)
