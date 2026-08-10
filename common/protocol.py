import json
import struct
import time

class Packet:
    def __init__(self, message_type, sender=None, receiver=None, room=None, payload=None, timestamp=None):
        """
        Initializes a custom network packet.
        
        Args:
            message_type (str): Type of the packet (e.g., 'MSG', 'PM', 'JOIN', 'LEAVE', 'SYSTEM')
            sender (str or None): Name of the sender client
            receiver (str or None): Name of the recipient client (for private messages)
            room (str or None): Target chat room channel
            payload (dict or str or None): The data payload being carried
            timestamp (float or None): Unix timestamp. Defaults to current time if None.
        """
        self.message_type = message_type
        self.sender = sender
        self.receiver = receiver
        self.room = room
        self.payload = payload
        self.timestamp = timestamp if timestamp is not None else time.time()

    def to_dict(self):
        """Converts the packet structure into a dictionary."""
        return {
            "message_type": self.message_type,
            "sender": self.sender,
            "receiver": self.receiver,
            "room": self.room,
            "timestamp": self.timestamp,
            "payload": self.payload
        }

    def to_json(self):
        """Serializes the packet to a JSON string."""
        return json.dumps(self.to_dict())

    def to_bytes(self):
        """Serializes the packet to UTF-8 encoded bytes."""
        return self.to_json().encode('utf-8')

    @classmethod
    def from_dict(cls, data_dict):
        """Creates a Packet object from a dictionary."""
        return cls(
            message_type=data_dict.get("message_type"),
            sender=data_dict.get("sender"),
            receiver=data_dict.get("receiver"),
            room=data_dict.get("room"),
            payload=data_dict.get("payload"),
            timestamp=data_dict.get("timestamp")
        )

    @classmethod
    def from_json(cls, json_str):
        """Deserializes a JSON string into a Packet object."""
        data_dict = json.loads(json_str)
        return cls.from_dict(data_dict)

    @classmethod
    def from_bytes(cls, data_bytes):
        """Deserializes UTF-8 bytes into a Packet object."""
        json_str = data_bytes.decode('utf-8')
        return cls.from_json(json_str)

    def __repr__(self):
        return (f"Packet(type={self.message_type!r}, sender={self.sender!r}, "
                f"receiver={self.receiver!r}, room={self.room!r}, "
                f"timestamp={self.timestamp:.2f}, payload={self.payload!r})")


# --- Socket TCP Framing Protocols ---
# In order to prevent packet fragmentation over raw TCP sockets:
# Header: 4-byte big-endian unsigned integer (uint32) representing payload length.
# Payload: JSON bytes of the serialized Packet.

def send_framed_packet(sock, packet):
    """
    Serializes a Packet object, prefixes it with a 4-byte length header,
    and sends it completely over a TCP socket.
    """
    payload_bytes = packet.to_bytes()
    length_header = struct.pack('>I', len(payload_bytes))
    sock.sendall(length_header + payload_bytes)

def receive_framed_packet(sock):
    """
    Reads a 4-byte length prefix from a TCP socket, reads that exact number
    of payload bytes, and deserializes them back into a Packet object.
    
    Returns:
        Packet: The received Packet object, or None if connection is closed/aborted.
    """
    # Read length header
    header = _recv_all(sock, 4)
    if not header:
        return None
        
    payload_len = struct.unpack('>I', header)[0]
    
    # Read payload data
    payload_bytes = _recv_all(sock, payload_len)
    if not payload_bytes:
        return None
        
    return Packet.from_bytes(payload_bytes)

def _recv_all(sock, n):
    """Helper to receive exactly n bytes from a socket, or return None if EOF is reached."""
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)
