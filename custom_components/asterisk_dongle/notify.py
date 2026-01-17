"""
Asterisk Dongle SMS send platform for notify component.
"""
import logging
import socket
import time

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


class AsteriskManager:
    """Manager for Asterisk AMI connection."""
    
    def __init__(self, address, port, user, password):
        """Initialize the Asterisk manager."""
        self._address = address
        self._port = port
        self._user = user
        self._password = password
        
    def send_command(self, command):
        """Send a command to Asterisk via AMI and return the response."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self._address, self._port))
            
            # Login to AMI
            login_action = f'Action: Login\r\nUsername: {self._user}\r\nSecret: {self._password}\r\n\r\n'
            sock.send(login_action.encode())
            time.sleep(0.5)
            
            # Send command
            command_action = f'Action: Command\r\nCommand: {command}\r\n\r\n'
            sock.send(command_action.encode())
            time.sleep(1)
            
            # Receive response
            response = sock.recv(8192).decode(errors='ignore')
            sock.close()
            
            return response
            
        except Exception as e:
            _LOGGER.error(f"Error connecting to Asterisk AMI: {e}")
            return None
    
    def send_ami_action(self, action_name, **kwargs):
        """Send a raw AMI action (for SMS/USSD)."""
        try:
            from asterisk.ami import AMIClient
            from asterisk.ami.action import SimpleAction
            
            client = AMIClient(address=self._address, port=self._port)
            future = client.login(username=self._user, secret=self._password)
            
            if future.response.is_error():
                _LOGGER.error("Can't connect to Asterisk AMI: %s", " ".join(str(future.response).splitlines()))
                return None
            
            action = SimpleAction(action_name, **kwargs)
            client.send_action(action)
            client.logoff()
            
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error sending AMI action: {e}")
            return False


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
        self._ami_manager = AsteriskManager(address, port, user, password)

    def send_message(self, message="", **kwargs):
        """Send an SMS or USSD to target users."""
        targets = kwargs.get(ATTR_TARGET)

        if targets is None:
            _LOGGER.error("No SMS/USSD targets, as 'target' is not defined")
            return

        for target in targets:
            _LOGGER.debug("Sending %s to %s", self._dngtype.upper(), target)
            
            if self._dngtype == 'sms':
                success = self._ami_manager.send_ami_action(
                    'DongleSendSMS',
                    Device=self._dongle,
                    Number=target,
                    Message=message,
                )
            elif self._dngtype == 'ussd':
                success = self._ami_manager.send_ami_action(
                    'DongleSendUSSD',
                    Device=self._dongle,
                    USSD=message,
                )
            else:
                _LOGGER.error("Unknown dongle type: %s", self._dngtype)
                return

            if success:
                _LOGGER.debug("%s to %s sent successfully", self._dngtype.upper(), target)
            else:
                _LOGGER.error("Failed to send %s to %s", self._dngtype.upper(), target)

    def get_dongle_state(self):
        """Get dongle state information."""
        response = self._ami_manager.send_command(f'dongle show device state {self._dongle}')
        return response