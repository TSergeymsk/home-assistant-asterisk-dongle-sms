"""Manager for Asterisk AMI connection."""
import socket
import logging
import time
from typing import Optional, Tuple

_LOGGER = logging.getLogger(__name__)


class AsteriskManager:
    """Manager for Asterisk AMI connection with improved error handling."""
    
    def __init__(self, host: str, port: int, username: str, password: str):
        """Initialize the Asterisk manager."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._connected = False
        self._socket: Optional[socket.socket] = None
        
    def _connect(self) -> Tuple[bool, str]:
        """Establish connection to AMI synchronously. Returns (success, error_message)."""
        try:
            if self._socket:
                try:
                    self._socket.close()
                except:
                    pass
                    
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
            
            if not response:
                return False, "No response from server"
                
            if "Response: Success" in response and "Message: Authentication accepted" in response:
                self._connected = True
                _LOGGER.debug("Successfully connected to AMI at %s:%s", self._host, self._port)
                return True, ""
            elif "Response: Error" in response:
                # Parse error message
                error_msg = "Authentication failed"
                for line in response.split('\n'):
                    if 'Message:' in line:
                        error_msg = line.split('Message:', 1)[1].strip()
                        break
                return False, error_msg
            else:
                return False, "Unexpected login response format"
                
        except socket.timeout:
            return False, "Connection timeout"
        except ConnectionRefusedError:
            return False, "Connection refused"
        except socket.gaierror:
            return False, "Invalid hostname or IP address"
        except Exception as e:
            return False, f"Connection error: {str(e)}"
    
    def _receive_response(self, timeout: float = 5.0) -> str:
        """Receive full response from AMI."""
        if not self._socket:
            return ""
            
        response = b""
        try:
            self._socket.settimeout(timeout)
            start_time = time.time()
            
            # Read until we get complete AMI response (ends with \r\n\r\n)
            while True:
                try:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    
                    # AMI responses typically end with \r\n\r\n
                    if response.endswith(b'\r\n\r\n'):
                        break
                        
                    # Also check for other termination patterns
                    if b'\n\n' in response[-10:]:
                        break
                        
                    # Timeout check
                    if time.time() - start_time > timeout:
                        break
                        
                except socket.timeout:
                    # Partial response might be OK
                    break
                    
        except Exception as e:
            _LOGGER.debug("Error receiving response: %s", e)
            
        return response.decode('utf-8', errors='ignore')
    
    def send_command(self, command: str) -> str:
        """Send a command to Asterisk via AMI and return the response synchronously."""
        try:
            # Ensure connection
            if not self._connected:
                success, error_msg = self._connect()
                if not success:
                    _LOGGER.error("Failed to connect: %s", error_msg)
                    return ""
            
            # Send command
            command_action = (
                f'Action: Command\r\n'
                f'Command: {command}\r\n'
                f'\r\n'
            )
            self._socket.send(command_action.encode())
            
            # Wait for response (shorter wait for command responses)
            time.sleep(0.5)
            response = self._receive_response(timeout=3.0)
            
            # If no response, try reconnecting and retrying once
            if not response:
                _LOGGER.warning("No response for command '%s', reconnecting...", command)
                self._connected = False
                success, error_msg = self._connect()
                if success:
                    self._socket.send(command_action.encode())
                    time.sleep(0.5)
                    response = self._receive_response(timeout=3.0)
            
            _LOGGER.debug("Command '%s' got response length: %d", command, len(response) if response else 0)
            
            return response or ""
            
        except socket.timeout:
            _LOGGER.error("Socket timeout for command: %s", command)
            self._connected = False
            return ""
        except ConnectionResetError:
            _LOGGER.error("Connection reset for command: %s", command)
            self._connected = False
            return ""
        except BrokenPipeError:
            _LOGGER.error("Broken pipe for command: %s", command)
            self._connected = False
            return ""
        except Exception as e:
            _LOGGER.error("Error sending command '%s': %s", command, e)
            return ""
    
    def disconnect(self):
        """Disconnect from AMI."""
        try:
            if self._socket:
                # Send logout command
                try:
                    logout_action = 'Action: Logoff\r\n\r\n'
                    self._socket.send(logout_action.encode())
                    time.sleep(0.1)
                except:
                    pass
                    
                self._socket.close()
                _LOGGER.debug("Disconnected from AMI")
        except:
            pass
        finally:
            self._socket = None
            self._connected = False
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test connection to AMI with a simple command. Returns (success, message)."""
        try:
            response = self.send_command("core show version")
            if not response:
                return False, "No response from server"
                
            if "Response: Error" in response:
                # Parse error message
                error_msg = "Command failed"
                for line in response.split('\n'):
                    if 'Message:' in line:
                        error_msg = line.split('Message:', 1)[1].strip()
                        break
                return False, error_msg
                
            # Check for success indicators
            if "Response: Success" in response or "Asterisk" in response:
                return True, "Connection successful"
            else:
                return False, "Unexpected response format"
                
        except Exception as e:
            return False, f"Test failed: {str(e)}"
    
    def is_connected(self) -> bool:
        """Check if connected to AMI."""
        return self._connected
    
    def __del__(self):
        """Destructor to ensure socket is closed."""
        self.disconnect()