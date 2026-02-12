#!/usr/bin/env python3
"""
Atlona Telnet Broker Service

A connection broker that maintains a single persistent connection to the Atlona
matrix switcher and multiplexes requests from multiple clients.

Features:
- Single persistent connection to Atlona (avoids connection limit issues)
- Queue-based command processing
- Automatic reconnection with backoff
- Wait/hold for connection availability
- Simple TCP interface for clients

Usage:
    Server: python atlona_broker.py --host <ATLONA_IP> --port 23 --listen-port 2323
    Client: echo "Status" | nc localhost 2323

Protocol:
    Client sends command, broker forwards to Atlona, returns response.
    Special commands:
        BROKER:STATUS - Get broker status
        BROKER:RECONNECT - Force reconnection to Atlona
"""

import asyncio
import argparse
import json
import logging
import signal
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('atlona-broker')


@dataclass
class BrokerStats:
    """Broker statistics."""
    started_at: str
    atlona_host: str
    atlona_port: int
    connected: bool
    connection_attempts: int
    successful_connections: int
    commands_processed: int
    commands_failed: int
    active_clients: int
    last_command_at: Optional[str] = None
    last_error: Optional[str] = None


class AtlonaBroker:
    """Manages connection to Atlona and processes client requests."""
    
    def __init__(self, atlona_host: str, atlona_port: int = 23):
        self.atlona_host = atlona_host
        self.atlona_port = atlona_port
        
        # Connection state
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._connecting = False
        self._connection_lock = asyncio.Lock()
        
        # Command queue
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._command_lock = asyncio.Lock()
        
        # Statistics
        self._stats = BrokerStats(
            started_at=datetime.now().isoformat(),
            atlona_host=atlona_host,
            atlona_port=atlona_port,
            connected=False,
            connection_attempts=0,
            successful_connections=0,
            commands_processed=0,
            commands_failed=0,
            active_clients=0
        )
        
        # Reconnection settings
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0
        self._reconnect_task: Optional[asyncio.Task] = None
        
        # Client tracking
        self._active_clients: set = set()
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self._writer is not None
    
    async def connect(self) -> bool:
        """Connect to the Atlona matrix."""
        async with self._connection_lock:
            if self._connected:
                return True
            
            if self._connecting:
                # Wait for ongoing connection attempt
                return False
            
            self._connecting = True
            self._stats.connection_attempts += 1
            
            try:
                logger.info(f"Connecting to Atlona at {self.atlona_host}:{self.atlona_port}...")
                
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.atlona_host, self.atlona_port),
                    timeout=10.0
                )
                
                # Read any initial banner/prompt
                try:
                    await asyncio.wait_for(self._reader.read(1024), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                
                self._connected = True
                self._stats.connected = True
                self._stats.successful_connections += 1
                self._reconnect_delay = 1.0  # Reset backoff
                
                logger.info(f"Connected to Atlona successfully")
                return True
                
            except asyncio.TimeoutError:
                logger.error(f"Connection to Atlona timed out")
                self._stats.last_error = "Connection timeout"
                return False
                
            except Exception as e:
                logger.error(f"Failed to connect to Atlona: {e}")
                self._stats.last_error = str(e)
                return False
                
            finally:
                self._connecting = False
    
    async def disconnect(self):
        """Disconnect from the Atlona matrix."""
        async with self._connection_lock:
            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception:
                    pass
            
            self._reader = None
            self._writer = None
            self._connected = False
            self._stats.connected = False
            logger.info("Disconnected from Atlona")
    
    async def reconnect(self):
        """Reconnect with exponential backoff."""
        await self.disconnect()
        
        while not self._connected:
            logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
            await asyncio.sleep(self._reconnect_delay)
            
            if await self.connect():
                break
            
            # Exponential backoff
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                self._max_reconnect_delay
            )
    
    async def send_command(self, command: str, timeout: float = 5.0) -> tuple[bool, str]:
        """
        Send a command to the Atlona and return the response.
        
        Returns (success, response_or_error)
        """
        async with self._command_lock:
            # Ensure connected
            if not self.is_connected:
                if not await self.connect():
                    return False, "Not connected to Atlona"
            
            try:
                # Clear any pending data in the buffer first
                try:
                    self._reader._buffer.clear()
                except:
                    pass
                
                # Also try to read and discard any pending data
                try:
                    while True:
                        data = await asyncio.wait_for(
                            self._reader.read(4096),
                            timeout=0.1
                        )
                        if not data:
                            break
                except asyncio.TimeoutError:
                    pass  # No pending data, good
                except:
                    pass
                
                # Send command
                cmd = command.strip()
                if not cmd.endswith('\r\n'):
                    cmd += '\r\n'
                
                self._writer.write(cmd.encode())
                await self._writer.drain()
                
                # Small delay to let Atlona process and respond
                await asyncio.sleep(0.3)
                
                # Read response
                response = ""
                try:
                    data = await asyncio.wait_for(
                        self._reader.read(4096),
                        timeout=timeout
                    )
                    response = data.decode('utf-8', errors='ignore').strip()
                except asyncio.TimeoutError:
                    # Some commands don't return a response
                    pass
                
                self._stats.commands_processed += 1
                self._stats.last_command_at = datetime.now().isoformat()
                
                return True, response
                
            except Exception as e:
                logger.error(f"Command failed: {e}")
                self._stats.commands_failed += 1
                self._stats.last_error = str(e)
                
                # Connection probably broken, trigger reconnect
                asyncio.create_task(self.reconnect())
                
                return False, str(e)
    
    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a client connection."""
        client_addr = writer.get_extra_info('peername')
        client_id = f"{client_addr[0]}:{client_addr[1]}"
        
        self._active_clients.add(client_id)
        self._stats.active_clients = len(self._active_clients)
        logger.info(f"Client connected: {client_id}")
        
        try:
            while True:
                # Read command from client
                data = await asyncio.wait_for(reader.read(1024), timeout=300.0)
                if not data:
                    break
                
                command = data.decode('utf-8', errors='ignore').strip()
                if not command:
                    continue
                
                logger.debug(f"[{client_id}] Command: {command}")
                
                # Handle broker commands
                if command.upper() == "BROKER:STATUS":
                    response = json.dumps(asdict(self._stats), indent=2)
                    writer.write((response + "\n").encode())
                    await writer.drain()
                    continue
                
                if command.upper() == "BROKER:RECONNECT":
                    asyncio.create_task(self.reconnect())
                    writer.write(b"OK: Reconnecting\n")
                    await writer.drain()
                    continue
                
                if command.upper() == "BROKER:WAIT":
                    # Wait until connected
                    wait_count = 0
                    while not self.is_connected and wait_count < 30:
                        await asyncio.sleep(1)
                        wait_count += 1
                    
                    if self.is_connected:
                        writer.write(b"OK: Connected\n")
                    else:
                        writer.write(b"ERROR: Connection timeout\n")
                    await writer.drain()
                    continue
                
                # Forward command to Atlona
                success, response = await self.send_command(command)
                
                if success:
                    writer.write((response + "\n").encode())
                else:
                    writer.write(f"ERROR: {response}\n".encode())
                
                await writer.drain()
                
        except asyncio.TimeoutError:
            logger.info(f"Client {client_id} timed out")
        except ConnectionResetError:
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Client {client_id} error: {e}")
        finally:
            self._active_clients.discard(client_id)
            self._stats.active_clients = len(self._active_clients)
            
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            
            logger.info(f"Client disconnected: {client_id}")
    
    async def start_server(self, listen_host: str = "0.0.0.0", listen_port: int = 2323):
        """Start the broker server."""
        # Initial connection to Atlona
        await self.connect()
        
        # Start TCP server
        server = await asyncio.start_server(
            self.handle_client,
            listen_host,
            listen_port
        )
        
        addr = server.sockets[0].getsockname()
        logger.info(f"Atlona Broker listening on {addr[0]}:{addr[1]}")
        logger.info(f"Proxying to Atlona at {self.atlona_host}:{self.atlona_port}")
        
        async with server:
            await server.serve_forever()


async def main():
    parser = argparse.ArgumentParser(description='Atlona Telnet Broker')
    parser.add_argument('--host', required=True, help='Atlona IP address')
    parser.add_argument('--port', type=int, default=23, help='Atlona port (default: 23)')
    parser.add_argument('--listen-host', default='0.0.0.0', help='Listen address (default: 0.0.0.0)')
    parser.add_argument('--listen-port', type=int, default=2323, help='Listen port (default: 2323)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    broker = AtlonaBroker(args.host, args.port)
    
    # Handle shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(broker)))
    
    await broker.start_server(args.listen_host, args.listen_port)


async def shutdown(broker: AtlonaBroker):
    """Graceful shutdown."""
    logger.info("Shutting down...")
    await broker.disconnect()
    
    # Cancel all tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.get_event_loop().stop()


if __name__ == "__main__":
    asyncio.run(main())
