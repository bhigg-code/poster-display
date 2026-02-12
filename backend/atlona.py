"""Atlona Matrix integration with broker support."""

import asyncio
import re
from typing import Optional


class AtlonaMatrix:
    """Control and monitor Atlona OPUS matrix switcher.
    
    Supports two modes:
    1. Direct connection (default) - connects directly to Atlona
    2. Broker mode - connects via atlona-broker service
    
    Broker mode is recommended when multiple services need to access the Atlona,
    as the Atlona has limited concurrent telnet connections.
    """
    
    def __init__(self, host: str, port: int = 23, use_broker: bool = False, 
                 broker_host: str = "localhost", broker_port: int = 2323):
        self.host = host
        self.port = port
        self.use_broker = use_broker
        self.broker_host = broker_host
        self.broker_port = broker_port
    
    async def _send_command(self, command: str, timeout: float = 5.0) -> str:
        """Send command and return response."""
        if self.use_broker:
            return await self._send_via_broker(command, timeout)
        else:
            return await self._send_direct(command, timeout)
    
    async def _send_direct(self, command: str, timeout: float = 5.0) -> str:
        """Send command directly to Atlona."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout
            )
            
            writer.write(f"{command}\r\n".encode())
            await writer.drain()
            
            # Read response
            await asyncio.sleep(0.3)
            data = await asyncio.wait_for(reader.read(1024), timeout=timeout)
            
            writer.close()
            await writer.wait_closed()
            
            return data.decode('utf-8', errors='ignore')
            
        except Exception as e:
            print(f"Atlona direct error: {e}")
            return ""
    
    async def _send_via_broker(self, command: str, timeout: float = 5.0) -> str:
        """Send command via broker service."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.broker_host, self.broker_port),
                timeout=timeout
            )
            
            # Send command
            writer.write(f"{command}\n".encode())
            await writer.drain()
            
            # Read response
            data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
            
            writer.close()
            await writer.wait_closed()
            
            response = data.decode('utf-8', errors='ignore').strip()
            
            # Check for broker errors
            if response.startswith("ERROR:"):
                print(f"Atlona broker error: {response}")
                return ""
            
            return response
            
        except Exception as e:
            print(f"Atlona broker error: {e}")
            return ""
    
    async def check_broker_available(self) -> bool:
        """Check if broker service is available."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.broker_host, self.broker_port),
                timeout=2.0
            )
            
            writer.write(b"BROKER:STATUS\n")
            await writer.drain()
            
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            
            writer.close()
            await writer.wait_closed()
            
            return b"connected" in data.lower()
            
        except Exception:
            return False
    
    async def wait_for_broker(self, timeout: float = 30.0) -> bool:
        """Wait for broker to be connected to Atlona."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.broker_host, self.broker_port),
                timeout=timeout
            )
            
            writer.write(b"BROKER:WAIT\n")
            await writer.drain()
            
            data = await asyncio.wait_for(reader.read(1024), timeout=timeout)
            
            writer.close()
            await writer.wait_closed()
            
            return b"OK" in data
            
        except Exception:
            return False
    
    async def get_routing(self) -> dict[int, int]:
        """Get current routing matrix. Returns {output: input}."""
        response = await self._send_command("Status")
        
        if not response:
            return {}
        
        routing = {}
        
        # Match video routing (xINPUTVxOUTPUT)
        matches = re.findall(r'x(\d+)Vx(\d+)', response)
        for input_num, output_num in matches:
            routing[int(output_num)] = int(input_num)
        
        return routing
    
    async def get_input_for_output(self, output: int) -> Optional[int]:
        """Get which input is routed to a specific output."""
        routing = await self.get_routing()
        return routing.get(output)
    
    async def set_routing(self, input_num: int, output_num: int) -> bool:
        """Route an input to an output."""
        command = f"x{input_num}AVx{output_num}"
        response = await self._send_command(command)
        return bool(response)  # Non-empty response indicates success
    
    async def get_status(self) -> dict:
        """Get full status including broker info if using broker."""
        status = {
            "host": self.host,
            "port": self.port,
            "use_broker": self.use_broker,
            "routing": await self.get_routing()
        }
        
        if self.use_broker:
            status["broker_host"] = self.broker_host
            status["broker_port"] = self.broker_port
            status["broker_available"] = await self.check_broker_available()
        
        return status
