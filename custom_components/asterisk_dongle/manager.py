"""Manager for Asterisk AMI connection."""
import socket
import logging
import asyncio
from typing import Optional, Any
from contextlib import asynccontextmanager

# Устанавливаем asyncio-совместимое логирование
_LOGGER = logging.getLogger(__name__)


class AsteriskManager:
    """Manager for Asterisk AMI connection with improved reliability."""
    
    def __init__(self, host: str, port: int, username: str, password: str):
        """Initialize the Asterisk manager."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._client = None
        self._adapter = None
        self._connected = False
        self._lock = asyncio.Lock()
        
    def _init_client(self):
        """Initialize AMI client (synchronous)."""
        try:
            from asterisk.ami import AMIClient, AMIClientAdapter
            
            self._client = AMIClient(
                address=self._host,
                port=self._port,
                timeout=10
            )
            self._adapter = AMIClientAdapter(self._client)
            return True
        except ImportError:
            _LOGGER.error(
                "asterisk-ami library not installed. "
                "Please add 'asterisk-ami' to requirements in manifest.json"
            )
            return False
        except Exception as e:
            _LOGGER.error("Failed to initialize AMI client: %s", e)
            return False
    
    async def _async_connect(self) -> bool:
        """Establish connection to AMI asynchronously."""
        if self._connected:
            return True
            
        async with self._lock:
            if self._connected:
                return True
                
            try:
                # Initialize client in executor since it's synchronous
                import asyncio
                from functools import partial
                
                init_func = partial(self._init_client)
                success = await asyncio.get_event_loop().run_in_executor(None, init_func)
                
                if not success:
                    return False
                
                # Connect and login
                await asyncio.get_event_loop().run_in_executor(
                    None, 
                    lambda: self._client.login(
                        username=self._username,
                        secret=self._password
                    )
                )
                
                # Verify connection by sending a simple command
                test_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._adapter.Command(command="core show version")
                )
                
                if test_response and test_response.response:
                    self._connected = True
                    _LOGGER.info(
                        "Successfully connected to AMI at %s:%s", 
                        self._host, self._port
                    )
                    return True
                else:
                    _LOGGER.error("Connection test failed")
                    return False
                    
            except socket.timeout:
                _LOGGER.error("Connection timeout to %s:%s", self._host, self._port)
                return False
            except ConnectionRefusedError:
                _LOGGER.error("Connection refused to %s:%s", self._host, self._port)
                return False
            except Exception as e:
                _LOGGER.error("Failed to connect to AMI: %s", e)
                return False
    
    async def send_command(self, command: str) -> str:
        """Send a command to Asterisk via AMI and return the response."""
        try:
            # Ensure we're connected
            if not await self._async_connect():
                _LOGGER.error("Not connected to AMI")
                return ""
            
            # Check if it's a console command or action
            if command.startswith("dongle show") or command.startswith("core show"):
                # Use Command action for console commands[citation:1]
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._adapter.Command(command=command)
                )
            else:
                # Use SimpleAction for other commands[citation:1]
                from asterisk.ami import SimpleAction
                action = SimpleAction('Command', Command=command)
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._client.send_action(action)
                )
            
            if not response:
                _LOGGER.warning("Empty response for command: %s", command)
                return ""
            
            # Extract response text
            response_text = self._extract_response_text(response)
            _LOGGER.debug(
                "Command '%s' response (first 500 chars): %s",
                command,
                response_text[:500] if response_text else "None"
            )
            
            return response_text
            
        except socket.timeout:
            _LOGGER.error("Socket timeout for command: %s", command)
            self._connected = False
            return ""
        except ConnectionResetError:
            _LOGGER.error("Connection reset for command: %s", command)
            self._connected = False
            return ""
        except Exception as e:
            _LOGGER.error("Error sending command '%s': %s", command, e)
            return ""
    
    def _extract_response_text(self, response) -> str:
        """Extract response text from AMI response object."""
        try:
            # Handle different response types
            if hasattr(response, 'data'):
                # Response has data attribute
                return response.data
            elif hasattr(response, 'response'):
                # Response object with response attribute
                if isinstance(response.response, dict):
                    # Convert dict to string representation
                    import json
                    return json.dumps(response.response, indent=2)
                else:
                    return str(response.response)
            elif hasattr(response, '__dict__'):
                # Try to get all attributes
                return str(response.__dict__)
            else:
                # Fallback to string conversion
                return str(response)
        except Exception as e:
            _LOGGER.debug("Error extracting response text: %s", e)
            return str(response)
    
    async def disconnect(self):
        """Disconnect from AMI."""
        async with self._lock:
            if self._connected and self._client:
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._client.logoff()
                    )
                    _LOGGER.debug("Disconnected from AMI")
                except Exception as e:
                    _LOGGER.debug("Error during disconnect: %s", e)
                finally:
                    self._connected = False
                    self._client = None
                    self._adapter = None
    
    def is_connected(self) -> bool:
        """Check if connected to AMI."""
        return self._connected
    
    @asynccontextmanager
    async def connection(self):
        """Context manager for AMI connection."""
        try:
            if await self._async_connect():
                yield self
            else:
                raise ConnectionError("Failed to connect to AMI")
        finally:
            await self.disconnect()