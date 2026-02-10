"""Network discovery for home theater integrations."""

import asyncio
import socket
import re
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Callable
from enum import Enum


class IntegrationType(str, Enum):
    ATLONA = "atlona"
    KALEIDESCAPE = "kaleidescape"
    PLEX = "plex"
    SHIELD = "shield"
    APPLETV = "appletv"
    UNKNOWN = "unknown"


@dataclass
class DiscoveredDevice:
    """A discovered device on the network."""
    ip: str
    integration_type: IntegrationType
    name: str = ""
    port: int = 0
    verified: bool = False
    details: dict = field(default_factory=dict)
    
    def to_dict(self):
        d = asdict(self)
        d["integration_type"] = self.integration_type.value
        return d


# Log callback type: (category, action, details, level)
LogCallback = Callable[[str, str, str, str], None]


class NetworkDiscovery:
    """Discovers home theater devices on the local network."""
    
    def __init__(self):
        self._scanning = False
        self._scan_results: List[DiscoveredDevice] = []
        self._plex_results: List[DiscoveredDevice] = []  # Separate Plex-discovered devices
        self._scan_progress = 0
        self._scan_total = 0
        self._scan_phase = ""  # Current phase description
        self._plex_scanned = False  # Whether Plex scan has run for current scan
        self._log_callback: Optional[LogCallback] = None
    
    def set_logger(self, callback: LogCallback):
        """Set a callback for logging discovery activity."""
        self._log_callback = callback
    
    def _log(self, action: str, details: str = "", level: str = "info"):
        """Log discovery activity."""
        if self._log_callback:
            self._log_callback("discovery", action, details, level)
        print(f"[discovery] {action}: {details}" if details else f"[discovery] {action}")
    
    @property
    def is_scanning(self) -> bool:
        return self._scanning
    
    @property
    def scan_progress(self) -> tuple:
        return (self._scan_progress, self._scan_total)
    
    @property
    def scan_phase(self) -> str:
        return self._scan_phase
    
    @property
    def results(self) -> list:
        # Combine network and Plex results
        all_results = []
        for d in self._scan_results:
            result = d.to_dict()
            result["source"] = "network"
            all_results.append(result)
        for d in self._plex_results:
            result = d.to_dict()
            result["source"] = "plex"
            all_results.append(result)
        return all_results
    
    @property
    def plex_scanned(self) -> bool:
        return self._plex_scanned
    
    def add_plex_device(self, device: DiscoveredDevice):
        """Add a device discovered via Plex."""
        self._plex_results.append(device)
    
    def mark_plex_scanned(self):
        """Mark that Plex scan has been completed for this discovery cycle."""
        self._plex_scanned = True
    
    async def probe_port(self, ip: str, port: int, timeout: float = 2) -> bool:
        """Check if a port is open."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except:
            return False
    
    async def probe_atlona(self, ip: str, log_details: bool = False) -> Optional[DiscoveredDevice]:
        """Probe for Atlona matrix switcher."""
        try:
            if log_details:
                self._log(f"Probing {ip}", "Checking Atlona (port 23, telnet)")
            
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 23),
                timeout=5
            )
            
            if log_details:
                self._log(f"Probing {ip}", "Connected, sending Status command")
            
            writer.write(b"Status\r\n")
            await writer.drain()
            
            # Give more time for response - Atlona can be slow
            await asyncio.sleep(1.0)
            data = await asyncio.wait_for(reader.read(1024), timeout=5)
            writer.close()
            await writer.wait_closed()
            
            response = data.decode("utf-8", errors="ignore")
            
            if log_details:
                self._log(f"Probing {ip}", f"Got {len(data)} bytes response")
            
            if re.search(r"x\d+Vx\d+", response):
                if log_details:
                    self._log(f"Found Atlona at {ip}", f"Response: {response[:60]}...", "success")
                return DiscoveredDevice(
                    ip=ip,
                    integration_type=IntegrationType.ATLONA,
                    name="Atlona Matrix",
                    port=23,
                    verified=True,
                    details={"routing_sample": response[:100]}
                )
            else:
                if log_details:
                    self._log(f"Probing {ip}", f"No routing pattern found in: {response[:60]}", "warning")
        except asyncio.TimeoutError:
            if log_details:
                self._log(f"Probing {ip}", "Timeout waiting for response", "warning")
        except Exception as e:
            if log_details:
                self._log(f"Probing {ip}", f"Error: {str(e)}", "error")
        return None
    
    async def probe_kaleidescape(self, ip: str, log_details: bool = False) -> Optional[DiscoveredDevice]:
        """Probe for Kaleidescape player."""
        try:
            if log_details:
                self._log(f"Probing {ip}", "Checking Kaleidescape (port 10000)")
            
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, 10000),
                timeout=3
            )
            
            # Get friendly system name (shared by all devices in a system)
            if log_details:
                self._log(f"Probing {ip}", "Sending GET_FRIENDLY_SYSTEM_NAME")
            writer.write(b"01/1/GET_FRIENDLY_SYSTEM_NAME:\r")
            await writer.drain()
            await asyncio.sleep(0.3)
            data = await asyncio.wait_for(reader.read(256), timeout=2)
            response = data.decode("utf-8", errors="ignore")
            
            if not ("FRIENDLY_SYSTEM_NAME" in response or response.startswith("01/")):
                writer.close()
                await writer.wait_closed()
                return None
            
            system_name = ""
            match = re.search(r"FRIENDLY_SYSTEM_NAME:([^:]+):", response)
            if match:
                system_name = match.group(1).strip()
            
            if log_details:
                self._log(f"Probing {ip}", f"System name: {system_name}")
            
            # Get device info: DEVICE_INFO:component_id:serial:unknown:ip
            if log_details:
                self._log(f"Probing {ip}", "Sending GET_DEVICE_INFO")
            writer.write(b"01/1/GET_DEVICE_INFO:\r")
            await writer.drain()
            await asyncio.sleep(0.3)
            data = await asyncio.wait_for(reader.read(512), timeout=2)
            info_response = data.decode("utf-8", errors="ignore")
            
            serial = ""
            component_id = ""
            info_match = re.search(r"DEVICE_INFO:(\d+):(\d+):", info_response)
            if info_match:
                component_id = info_match.group(1).strip()
                serial = info_match.group(2).strip()
            
            # Get device type name (Player, Terra Movie Server, etc.)
            if log_details:
                self._log(f"Probing {ip}", "Sending GET_DEVICE_TYPE_NAME")
            writer.write(b"01/1/GET_DEVICE_TYPE_NAME:\r")
            await writer.drain()
            await asyncio.sleep(0.3)
            data = await asyncio.wait_for(reader.read(256), timeout=2)
            type_response = data.decode("utf-8", errors="ignore")
            
            device_type = ""
            type_match = re.search(r"DEVICE_TYPE_NAME:([^:]+):", type_response)
            if type_match:
                device_type = type_match.group(1).strip()
            
            writer.close()
            await writer.wait_closed()
            
            # Use system_name + device_type for display name
            display_name = system_name or "Kaleidescape"
            if device_type and device_type != "Player":
                display_name = f"{system_name} ({device_type})"
            
            if log_details:
                self._log(f"Found Kaleidescape at {ip}", f"{display_name} (Serial: {serial[-8:] if serial else 'N/A'})", "success")
            
            return DiscoveredDevice(
                ip=ip,
                integration_type=IntegrationType.KALEIDESCAPE,
                name=display_name,
                port=10000,
                verified=True,
                details={
                    "serial": serial,
                    "component_id": component_id,
                    "device_type": device_type,
                    "system_name": system_name,  # This is the key for filtering!
                }
            )
        except:
            pass
        return None
    
    async def get_kaleidescape_system_name(self, ip: str) -> Optional[str]:
        """Get system name from a configured Kaleidescape device."""
        device = await self.probe_kaleidescape(ip)
        if device:
            return device.details.get("system_name")
        return None
    
    async def probe_plex(self, ip: str, log_details: bool = False) -> Optional[DiscoveredDevice]:
        """Probe for Plex Media Server."""
        try:
            if log_details:
                self._log(f"Probing {ip}", "Checking Plex (port 32400, HTTP /identity)")
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"http://{ip}:32400/identity"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        name = "Plex Media Server"
                        match = re.search(r'friendlyName="([^"]+)"', text)
                        if match:
                            name = match.group(1)
                        
                        if log_details:
                            self._log(f"Found Plex at {ip}", f"Name: {name}", "success")
                        
                        return DiscoveredDevice(
                            ip=ip,
                            integration_type=IntegrationType.PLEX,
                            name=name,
                            port=32400,
                            verified=True,
                            details={"identity": text[:200]}
                        )
        except:
            pass
        return None
    
    async def probe_shield(self, ip: str, log_details: bool = False) -> Optional[DiscoveredDevice]:
        """Probe for Nvidia Shield (ADB)."""
        if log_details:
            self._log(f"Probing {ip}", "Checking Shield/Android TV (port 5555, ADB)")
        
        if await self.probe_port(ip, 5555, timeout=2):
            if log_details:
                self._log(f"Found Shield at {ip}", "ADB port open", "success")
            return DiscoveredDevice(
                ip=ip,
                integration_type=IntegrationType.SHIELD,
                name="Android TV / Shield",
                port=5555,
                verified=False,
                details={"note": "ADB port open, requires authorization"}
            )
        return None
    
    async def probe_appletv(self, ip: str, log_details: bool = False) -> Optional[DiscoveredDevice]:
        """Probe for Apple TV (AirPlay) - filters to only Apple TV players."""
        try:
            if log_details:
                self._log(f"Probing {ip}", "Checking Apple TV (port 7000, AirPlay)")
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"http://{ip}:7000/info"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    # Check for AirTunes server header (works even on 403)
                    server = resp.headers.get("Server", "")
                    if "AirTunes" in server:
                        name = "Apple TV"
                        model = ""
                        
                        # Try to parse the binary plist response for name/model
                        if resp.status == 200:
                            try:
                                import plistlib
                                data = await resp.read()
                                plist = plistlib.loads(data)
                                name = plist.get("name", "Apple TV")
                                model = plist.get("model", "")
                            except:
                                pass  # Fallback to default name
                        
                        # Filter to only Apple TV players (not HomePods, AirPort Express, etc.)
                        # Apple TV models start with "AppleTV" (e.g., AppleTV11,1)
                        if not model.startswith("AppleTV"):
                            if log_details:
                                self._log(f"Skipping {ip}", f"Not an Apple TV player: {name} ({model or 'unknown model'})")
                            return None
                        
                        if log_details:
                            self._log(f"Found Apple TV at {ip}", f"{name} ({model})", "success")
                        
                        return DiscoveredDevice(
                            ip=ip,
                            integration_type=IntegrationType.APPLETV,
                            name=name,
                            port=7000,
                            verified=True,
                            details={
                                "model": model,
                                "server": server,
                                "note": "Apple TV player - requires pairing for media detection"
                            }
                        )
        except:
            pass
        return None
    
    async def probe_ip(self, ip: str, log_details: bool = False) -> List[DiscoveredDevice]:
        """Probe an IP for all known integrations."""
        devices = []
        
        results = await asyncio.gather(
            self.probe_atlona(ip, log_details),
            self.probe_kaleidescape(ip, log_details),
            self.probe_plex(ip, log_details),
            self.probe_shield(ip, log_details),
            self.probe_appletv(ip, log_details),
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, DiscoveredDevice):
                devices.append(result)
        
        return devices
    
    def get_local_subnets(self) -> List[str]:
        """Get local subnets to scan."""
        subnets = set()
        try:
            import netifaces
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        ip = addr.get('addr', '')
                        if ip and not ip.startswith('127.'):
                            parts = ip.split('.')
                            subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
        except ImportError:
            # Fallback without netifaces
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                parts = local_ip.split(".")
                subnets.add(f"{parts[0]}.{parts[1]}.{parts[2]}")
            except:
                # Fallback to common home network
                subnets.add("192.168.0")
        
        return list(subnets)
    
    async def scan_subnet(self, subnet: str, start: int = 1, end: int = 254) -> List[DiscoveredDevice]:
        """Scan a subnet for devices."""
        self._log(f"Scanning subnet {subnet}.0/24", f"IPs {start}-{end}")
        
        batch_size = 25
        found = []
        
        for batch_start in range(start, end + 1, batch_size):
            batch_end = min(batch_start + batch_size, end + 1)
            tasks = []
            
            for i in range(batch_start, batch_end):
                ip = f"{subnet}.{i}"
                tasks.append(self.probe_ip(ip))
            
            results = await asyncio.gather(*tasks)
            
            for idx, devices in enumerate(results):
                if devices:
                    ip = f"{subnet}.{batch_start + idx}"
                    for d in devices:
                        self._log(f"Device found: {ip}", f"{d.name} ({d.integration_type.value})", "success")
                found.extend(devices)
            
            self._scan_progress += (batch_end - batch_start)
            self._scan_phase = f"Scanning Network ({self._scan_progress}/{self._scan_total} IPs)"
        
        return found
    
    async def scan_all(self, subnets: List[str] = None) -> List[DiscoveredDevice]:
        """Scan all local subnets."""
        if self._scanning:
            return []
        
        self._scanning = True
        self._scan_results = []
        self._plex_results = []  # Clear Plex results too
        self._plex_scanned = False  # Reset Plex scan flag
        self._scan_progress = 0
        self._scan_phase = "Starting scan..."
        
        if not subnets:
            subnets = self.get_local_subnets()
            self._log("Auto-detected subnets", ", ".join(subnets))
        
        self._scan_total = len(subnets) * 254
        self._log("Network scan started", f"Scanning {len(subnets)} subnet(s), {self._scan_total} IPs total")
        
        try:
            # Phase 1: Network scan
            self._scan_phase = f"Scanning Network (0/{self._scan_total} IPs)"
            for subnet in subnets:
                devices = await self.scan_subnet(subnet)
                self._scan_results.extend(devices)
            
            self._log("Network scan complete", f"Found {len(self._scan_results)} device(s)", "success")
            
        finally:
            self._scanning = False
            self._scan_phase = "Scan complete"
        
        return self._scan_results



    def filter_configured(self, devices: List[DiscoveredDevice], configured_ips: List[str]) -> List[DiscoveredDevice]:
        """Filter out devices that are already configured."""
        configured_set = set(configured_ips)
        return [d for d in devices if d.ip not in configured_set]


# Global instance
discovery = NetworkDiscovery()
