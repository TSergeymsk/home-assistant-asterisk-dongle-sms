"""Manager for Asterisk AMI connection."""
import socket
import logging
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class AsteriskManager:
    """Manager for Asterisk AMI connection."""
    
    def __init__(self, host: str, port: int, username: str, password: str):
        """Initialize the Asterisk manager."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._socket: Optional[socket.socket] = None
        self._connected = False
        
    def _connect(self) -> bool:
        """Establish connection to AMI."""
        try:
            if self._socket:
                self._socket.close()
                
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(10)
            self._socket.connect((self._host, self._port))
            
            # Login to AMI
            login_action = (
                f'Action: Login\r\n'
                f'Username: {self._username}\r\n'
                f'Secret: {self._password}\r\n'
                f'\r\n'
            )
            self._socket.send(login_action.encode())
            
            # Wait for login response
            time.sleep(0.5)
            response = self._receive_response()
            
            if response and "Response: Success" in response:
                self._connected = True
                _LOGGER.debug("Successfully connected to AMI")
                return True
            else:
                _LOGGER.error("Login failed. Response: %s", response[:200] if response else "None")
                return False
                
        except Exception as e:
            _LOGGER.error("Error connecting to Asterisk AMI: %s", e)
            self._connected = False
            return False
    
    def _receive_response(self) -> str:
        """Receive full response from AMI."""
        if not self._socket:
            return ""
            
        response = b""
        try:
            # Set timeout for reading
            self._socket.settimeout(5)
            
            # Read until we get the full response
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
                response += chunk
                
                # AMI responses end with \r\n\r\n
                if response.endswith(b'\r\n\r\n'):
                    break
                    
        except socket.timeout:
            # Timeout is OK, we might have received everything
            pass
            
        return response.decode('utf-8', errors='ignore')
    
    def send_command(self, command: str) -> str:
        """Send a command to Asterisk via AMI and return the response."""
        if not self._connected and not self._connect():
            _LOGGER.error("Not connected to AMI")
            return ""
            
        try:
            # Send command
            command_action = (
                f'Action: Command\r\n'
                f'Command: {command}\r\n'
                f'\r\n'
            )
            self._socket.send(command_action.encode())
            
            # Wait for response
            time.sleep(0.5)
            response = self._receive_response()
            
            return response
            
        except Exception as e:
            _LOGGER.error("Error sending command to AMI: %s", e)
            self._connected = False
            return ""
    
    def disconnect(self):
        """Disconnect from AMI."""
        try:
            if self._socket:
                self._socket.close()
        except:
            pass
        finally:
            self._socket = None
            self._connected = False