import time
import os
import sys

# Add root folder to sys path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.logger import setup_logger
from server.socket_server import SocketServer

def main():
    # Setup standard logger
    logger = setup_logger("server")
    logger.info("Initializing TCP Socket Server Foundation...")

    # Bind on all interfaces (localhost and public IPs)
    server = SocketServer(host="0.0.0.0", port=8080)
    
    if not server.start():
        logger.error("Failed to start socket server. Exiting.")
        sys.exit(1)

    logger.info("Server is running. Press Ctrl+C to terminate.")
    
    try:
        # Keep main thread alive while background acceptor/handlers run
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        server.stop()
        logger.info("Main server thread terminated.")

if __name__ == "__main__":
    main()
