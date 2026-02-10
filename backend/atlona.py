"""Atlona Matrix integration."""

import asyncio
import re
from typing import Optional


class AtlonaMatrix:
    """Control and monitor Atlona OPUS matrix switcher."""
    
    def __init__(self, host: str, port: int = 23):
        self.host = host
        self.port = port
    
    async def get_routing(self) -> dict[int, int]:
        """Get current routing matrix. Returns {output: input}."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5
            )
            
            writer.write(b"Status\r\n")
            await writer.drain()
            
            # Read response
            await asyncio.sleep(0.5)
            data = await asyncio.wait_for(reader.read(1024), timeout=3)
            writer.close()
            await writer.wait_closed()
            
            # Parse response like "x4Vx1,x2Vx2,x1Vx3..."
            response = data.decode('utf-8', errors='ignore')
            routing = {}
            
            # Match video routing (xINPUTVxOUTPUT)
            matches = re.findall(r'x(\d+)Vx(\d+)', response)
            for input_num, output_num in matches:
                routing[int(output_num)] = int(input_num)
            
            return routing
            
        except Exception as e:
            print(f"Atlona error: {e}")
            return {}
    
    async def get_input_for_output(self, output: int) -> Optional[int]:
        """Get which input is routed to a specific output."""
        routing = await self.get_routing()
        return routing.get(output)
