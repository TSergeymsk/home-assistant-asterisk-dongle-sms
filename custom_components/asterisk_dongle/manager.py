"""Manager for Asterisk AMI connection."""
import socket
import logging
import time

_LOGGER = logging.getLogger(__name__)


class AsteriskManager:
    """Manager for Asterisk AMI connection."""
    
    def __init__(self, host, port, username, password):
        """Initialize the Asterisk manager."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        
    def send_command(self, command):
        """Send a command to Asterisk via AMI and return the response."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((self._host, self._port))
            
            # Login to AMI
            login_action = f'Action: Login\r\nUsername: {self._username}\r\nSecret: {self._password}\r\n\r\n'
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
            _LOGGER.error("Error connecting to Asterisk AMI: %s", e)
            return None