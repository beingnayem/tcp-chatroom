import socket
import ssl
import threading
import queue
import time
import logging
from common.protocol import Packet, send_framed_packet, receive_framed_packet

logger = logging.getLogger("client")

class SocketClient:
    def __init__(self, host="127.0.0.1", port=8080, reconnect_delay=5):
        self.host = host
        self.port = port
        self.reconnect_delay = reconnect_delay
        
        self.sock = None
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        
        # Queues & Threads
        self.send_queue = queue.Queue()
        self.receive_queue = queue.Queue()
        self.file_events_queue = queue.Queue()
        
        self.recv_thread = None
        self.send_thread = None

    def start(self):
        """Starts the client connection process and runs the reconnect loop if needed."""
        self.running = True
        
        # Start connection worker thread
        connection_thread = threading.Thread(
            target=self._connection_manager, 
            name="ConnectionManager", 
            daemon=True
        )
        connection_thread.start()

    def _connection_manager(self):
        while self.running:
            if not self.connected:
                logger.info(f"Attempting to connect to server at {self.host}:{self.port}...")
                if self._attempt_connect():
                    self.connected = True
                    logger.info("Successfully connected to server.")
                    self._start_io_threads()
                else:
                    logger.warning(f"Connection failed. Retrying in {self.reconnect_delay} seconds...")
                    time.sleep(self.reconnect_delay)
            else:
                time.sleep(1)

    def _attempt_connect(self):
        with self.lock:
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                raw_sock.connect((self.host, self.port))
                
                # Wrap socket in TLS
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                # Ignore self-signed host/cert warnings for local testing
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
                self.sock = context.wrap_socket(raw_sock, server_hostname=self.host)
                return True
            except Exception as e:
                logger.debug(f"Socket connection attempt error: {e}")
                raw_sock.close()
                self.sock = None
                return False

    def _start_io_threads(self):
        # Clean send queue of old leftover packets
        while not self.send_queue.empty():
            try:
                self.send_queue.get_nowait()
            except queue.Empty:
                break
                
        self.recv_thread = threading.Thread(
            target=self._recv_loop, 
            name="ReceiveThread", 
            daemon=True
        )
        self.send_thread = threading.Thread(
            target=self._send_loop, 
            name="SendThread", 
            daemon=True
        )
        
        self.recv_thread.start()
        self.send_thread.start()

    def _recv_loop(self):
        while self.running and self.connected:
            try:
                # Read framed packet
                packet = receive_framed_packet(self.sock)
                if not packet:
                    logger.info("Server closed connection.")
                    break
                
                logger.info(f"Received from server: {packet}")
                self.receive_queue.put(packet)
            except ConnectionError:
                logger.warning("Connection reset or aborted by server.")
                break
            except Exception as e:
                if self.running and self.connected:
                    logger.error(f"Error in receive loop: {e}")
                break

        self._handle_disconnect()

    def _send_loop(self):
        while self.running and self.connected:
            try:
                packet = self.send_queue.get(timeout=1)
                
                with self.lock:
                    if self.sock and self.connected:
                        send_framed_packet(self.sock, packet)
                        logger.info(f"Sent packet to server: {packet}")
                        
                self.send_queue.put_complete = True # or task_done
                self.send_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                if self.running and self.connected:
                    logger.error(f"Error in send loop: {e}")
                break

        self._handle_disconnect()

    def send_packet(self, packet):
        """Enqueues a Packet object to be sent by the send thread."""
        if not self.connected:
            logger.warning("Cannot send. Client is currently offline.")
            return False
        self.send_queue.put(packet)
        return True

    def _handle_disconnect(self):
        with self.lock:
            if not self.connected:
                return
            self.connected = False
            
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                
        logger.info("Disconnected from server. Standing by for reconnect sequence...")

    def disconnect(self):
        self.running = False
        self.connected = False
        
        with self.lock:
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                
        logger.info("Client shutdown complete.")
