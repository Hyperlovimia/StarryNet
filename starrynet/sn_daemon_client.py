#!/usr/bin/python3
import socket
import json
import time
import logging
import paramiko
import struct
from typing import Dict, Any, Optional, List

"""
StarryNet Daemon Client
用于与orchestrater守护进程通信的客户端库
"""

CHUNK_SIZE = 4096  # 4KB

MSG_MAX_SIZE = 10 * 1024 * 1024  # 10MB

class SSHDaemonClient:
    """SSH client for communicating with orchestrater daemon"""

    def __init__(self, host: str, port: int, username: str = None, 
                 password: str = None, timeout: int = 30):
        """
        Initialize SSH client

        Args:
            host: Remote host where daemon is running
            port: SSH port of daemon
            username: SSH username
            password: SSH password
            timeout: Connection timeout
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)
        self._client = None
        self._channel = None
        self._connected = False

    def connect(self):
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False
            )

            # Open interactive session
            self._channel = self._client.invoke_shell()
            self._connected = True
            self.logger.info(f"SSH connected to daemon at {self.host}:{self.port}")

        except Exception as e:
            raise Exception(f"SSH connection failed: {e}")

    def disconnect(self):
        try:
            if self._channel:
                self._channel.close()
            if self._client:
                self._client.close()
        except:
            pass
        finally:
            self._channel = None
            self._client = None
            self._connected = False
            self.logger.info("SSH connection closed")

    def _ensure_connected(self):
        if not self._connected or not self._client or not self._channel:
            self.connect()

    def _send_command_via_ssh(self, command: Dict[str, Any]):
        self._ensure_connected()

        try:
            # Send command as JSON string
            command_json = json.dumps(command)

            # Log large commands for debugging
            if len(command_json) > 4096:
                self.logger.info(f"Sending large command ({len(command_json)} chars): {command_json[:200]}...")

            # Clear any pending data
            while self._channel.recv_ready():
                self._channel.recv(4096)

            # Send command with length prefix
            self._send_message_with_length_ssh(command_json)

            # Wait for response with length prefix
            response_data = self._receive_message_with_length_ssh()
            if response_data is None:
                raise Exception("No response received")

            # Parse response
            try:
                response = json.loads(response_data.decode('utf-8'))
                return response
            except json.JSONDecodeError:
                # If response is not JSON, wrap it
                return {
                    "status": "error",
                    "message": f"Invalid JSON response: {response_data.decode('utf-8')}"
                }

        except Exception as e:
            self.logger.error(f"SSH command failed: {e}")
            self._connected = False

    def _send_message_with_length_ssh(self, data: str):
        try:
            # Convert data to bytes
            data_bytes = data.encode('utf-8')

            # Pack length as 4-byte integer (big-endian)
            length_prefix = struct.pack('!I', len(data_bytes))

            # Send length prefix followed by data
            self._channel.sendall(length_prefix + data_bytes)
        except Exception as e:
            self.logger.error(f"Error sending message with length via SSH: {e}")
            raise

    def _receive_message_with_length_ssh(self) -> bytes:
        try:
            # Read 4-byte length prefix
            length_data = self._recv_exact_ssh(4)
            if not length_data:
                return None

            # Unpack length
            message_length = struct.unpack('!I', length_data)[0]

            # Validate message length (prevent excessive memory usage)
            if message_length > MSG_MAX_SIZE:
                raise Exception(f"Message too large: {message_length} bytes")

            # Read the actual message data
            message_data = self._recv_exact_ssh(message_length)
            if not message_data:
                return None

            return message_data
        except Exception as e:
            self.logger.error(f"Error receiving message with length via SSH: {e}")
            raise

    def _recv_exact_ssh(self, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = self._channel.recv(length - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def send_config(self, shell_num: int, node_mid_dict: dict, ip_lst: list):
        command = {
            'c': 'config',
            't': time.time(),
            'p': {
                'shell_num': shell_num,
                'node_mid_dict': node_mid_dict,
                'ip_lst': ip_lst
            }
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to send config: {response.get('message')}")

    def init_nodes(self):
        command = {
            'c': 'nodes',
            't': time.time(),
            'p': {}
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to init nodes: {response.get('message')}")
        return response.get('result', [])

    def get_nodes(self):
        command = {
            'c': 'list',
            't': time.time(),
            'p': {}
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to get nodes: {response.get('message')}")

        nodes = []
        for node_info in response.get('result', {}).get('nodes', []):
            nodes.append(node_info.get('name', ''))

        return nodes

    def update_network(self, link_updates: dict):
        """Update network with link changes sent directly

        Args:
            link_updates: Dictionary containing link update information
                Structure: {
                    "shell_updates": {
                        "shell_id": {
                            "del": [("node1", "node2"), ...],
                            "update": [("node1", "node2", "delay"), ...],
                            "add": [("node1", "node2", "delay", idx), ...]
                        }, ...
                    },
                    "gs_updates": {
                        "del": [("gs1", "sat1"), ...],
                        "update": [("gs1", "sat1", "delay"), ...],
                        "add": [("gs1", "sat1", "delay", idx), ...]
                    },
                    "isl_bw": "bandwidth",
                    "isl_loss": "loss",
                    "gsl_bw": "bandwidth", 
                    "gsl_loss": "loss"
                }

        Returns:
            Response from daemon
        """
        command = {
            'c': 'update_network_batch',
            't': time.time(),
            'p': link_updates
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to update network: {response.get('message')}")

    def damage_nodes(self, nodes: list):
        command = {
            'c': 'damage',
            't': time.time(),
            'p': {
                'nodes': nodes
            }
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to damage nodes: {response.get('message')}")
        return response

    def recover_nodes(self, sat_loss: float):
        command = {
            'c': 'recovery',
            't': time.time(),
            'p': {
                'loss': sat_loss
            }
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to recover nodes: {response.get('message')}")

    def init_routing(self, nodes: str | List = 'all'):
        command = {
            'c': 'routed',
            't': time.time(),
            'p': {
                'nodes': nodes
            }
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to init routing: {response.get('message')}")

    def get_ip(self, node: str):
        command = {
            'c': 'IP',
            't': time.time(),
            'p': {
                'node': node
            }
        }
        response = self._send_command_via_ssh(command)
        if response.get('status') != 'success':
            raise Exception(f"Failed to get IP: {response.get('message')}")
        return response.get('result', {})

    def ping(self, src: str, dst: str):
        command = {
            'c': 'ping',
            't': time.time(),
            'p': {
                'src': src,
                'dst': dst
            }
        }
        return self._send_command_via_ssh(command)

    def iperf(self, cmds):
        command = {
            'c': 'iperf',
            't': time.time(),
            'p': {
                'cmds': cmds
            }
        }
        return self._send_command_via_ssh(command)

    def set_static_route(self, src: str, dst: str, next_hop: str):
        """Set static route"""
        command = {
            'c': 'sr',
            't': time.time(),
            'p': {
                'src': src,
                'dst': dst,
                'next': next_hop
            }
        }
        return self._send_command_via_ssh(command)
    
    def netlink(self, routes):
        command = {
            'c': 'netlink',
            't': time.time(),
            'p': {
                'routes': routes,
            }
        }

    def check_routing_table(self, node: str):
        """Check routing table for node"""
        command = {
            'c': 'rtable',
            't': time.time(),
            'p': {
                'node': node
            }
        }
        return self._send_command_via_ssh(command)

    def clean(self):
        """Clean up all resources"""
        command = {
            'c': 'clean',
            't': time.time(),
            'p': {}
        }
        return self._send_command_via_ssh(command)

    def exec_command(self, node: str, cmd: str):
        """Execute command in node"""
        command = {
            'c': 'exec',
            't': time.time(),
            'p': {
                'node': node,
                'cmd': cmd
            }
        }
        return self._send_command_via_ssh(command)

    def set_static_routes_batch(self, routes_config: dict):
        """Set static routes for multiple nodes in batch

        Args:
            routes_config: Dictionary mapping node names to lists of route tuples
                          Each tuple: (dst, gw, dev, metric)

        Returns:
            Response from daemon
        """
        command = {
            'c': 'sr_batch',
            't': time.time(),
            'p': {
                'routes_config': routes_config
            }
        }
        return self._send_command_via_ssh(command)

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
