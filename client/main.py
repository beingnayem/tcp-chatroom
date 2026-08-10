import time
import sys
import os
import logging
import threading
import queue
import hashlib
import base64
from datetime import datetime

# Add root folder to sys path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.logger import setup_logger
from common.protocol import Packet
from client.socket_client import SocketClient

logger = logging.getLogger("client")

class ClientState:
    def __init__(self):
        self.current_room = "General"
        self.joined_rooms = set(["General"])

state = ClientState()

def printer_worker(client):
    """Background worker that pulls packets from the client receive queue and prints them."""
    while client.running:
        try:
            packet = client.receive_queue.get(timeout=0.5)
            payload = packet.payload or {}
            
            # Intercept file transfer responses and forward them to the uploader thread's queue
            if packet.message_type in ["FILE_INIT_RESP", "FILE_PROGRESS", "FILE_COMPLETE"]:
                client.file_events_queue.put(packet)
                client.receive_queue.task_done()
                continue

            if packet.message_type == "REGISTER_RESP":
                success = payload.get("success")
                msg = payload.get("message")
                status = "SUCCESS" if success else "FAILED"
                print(f"\n[REGISTER RESULT] {status}: {msg}")
                
            elif packet.message_type == "LOGIN_RESP":
                success = payload.get("success")
                msg = payload.get("message")
                status = "SUCCESS" if success else "FAILED"
                print(f"\n[LOGIN RESULT] {status}: {msg}")
                
            elif packet.message_type == "LOGOUT_RESP":
                msg = payload.get("message")
                print(f"\n[LOGOUT RESULT]: {msg}")
                state.joined_rooms = set(["General"])
                state.current_room = "General"
                
            elif packet.message_type == "ROOMS_STATUS":
                joined = payload.get("joined_rooms", [])
                if joined:
                    state.joined_rooms = set(joined)
                    if "General" in state.joined_rooms:
                        state.current_room = "General"
                    else:
                        state.current_room = joined[0]
                print(f"\n[SERVER] Restored your joined channels: {list(state.joined_rooms)}")
                print(f"[SERVER] Active channel context is: #{state.current_room}")

            elif packet.message_type == "CREATE_ROOM_RESP":
                success = payload.get("success")
                room = payload.get("room")
                msg = payload.get("message")
                if success:
                    print(f"\n[CREATE ROOM SUCCESS] Created and joined room: #{room}")
                    state.joined_rooms.add(room)
                    state.current_room = room
                else:
                    print(f"\n[CREATE ROOM FAILED]: {msg}")

            elif packet.message_type == "DELETE_ROOM_RESP":
                success = payload.get("success")
                room = payload.get("room")
                msg = payload.get("message")
                if success:
                    print(f"\n[DELETE ROOM SUCCESS] Room #{room} has been deleted.")
                    state.joined_rooms.discard(room)
                    if state.current_room == room:
                        state.current_room = "General"
                else:
                    print(f"\n[DELETE ROOM FAILED]: {msg}")

            elif packet.message_type == "JOIN_ROOM_RESP":
                success = payload.get("success")
                room = packet.room
                msg = payload.get("message")
                if success:
                    print(f"\n[JOIN ROOM SUCCESS] Joined room: #{room}")
                    state.joined_rooms.add(room)
                    state.current_room = room
                else:
                    print(f"\n[JOIN ROOM FAILED]: {msg}")

            elif packet.message_type == "LEAVE_ROOM_RESP":
                success = payload.get("success")
                room = packet.room
                msg = payload.get("message")
                if success:
                    print(f"\n[LEAVE ROOM SUCCESS] Left room: #{room}")
                    state.joined_rooms.discard(room)
                    if state.current_room == room:
                        state.current_room = "General"
                else:
                    print(f"\n[LEAVE ROOM FAILED]: {msg}")

            elif packet.message_type == "PRESENCE":
                username = payload.get("username")
                status = payload.get("status")
                print(f"\n[PRESENCE UPDATE] User '{username}' is now {status}")

            elif packet.message_type == "ONLINE_LIST_RESP":
                online_users = payload.get("online_users", [])
                print("\n============= ONLINE USERS LIST =============")
                for u in online_users:
                    username = u.get("username")
                    status = u.get("status")
                    print(f"  - {username} ({status})")
                print("=============================================")

            elif packet.message_type == "ROLE_UPDATE":
                role = payload.get("role")
                msg = payload.get("message")
                print(f"\n[SERVER NOTICE] {msg}")

            elif packet.message_type == "KICKED":
                room = packet.room
                sender = packet.sender
                msg = payload.get("message")
                print(f"\n[KICKED WARNING] {msg}")
                state.joined_rooms.discard(room)
                if state.current_room == room:
                    state.current_room = "General"

            elif packet.message_type == "MSG":
                sender = packet.sender or "Unknown"
                text = payload.get("text", "")
                room = packet.room or "Public"
                ts = datetime.fromtimestamp(packet.timestamp).strftime('%H:%M:%S')
                if room == state.current_room:
                    print(f"\n[{ts}] {sender}: {text}")
                else:
                    print(f"\n[{ts}] [#{room}] {sender}: {text}")
                
            elif packet.message_type == "PM":
                sender = packet.sender or "Unknown"
                text = payload.get("text", "")
                ts = datetime.fromtimestamp(packet.timestamp).strftime('%H:%M:%S')
                print(f"\n[{ts}] [PM] {sender}: {text}")

            elif packet.message_type == "SYSTEM":
                msg = payload.get("message", "")
                print(f"\n[SYSTEM] {msg}")

            elif packet.message_type == "HISTORY":
                room = packet.room or "General"
                history = payload.get("history", [])
                print(f"\n============= HISTORY FOR #{room} ({len(history)} messages) =============")
                for h in history:
                    username = h.get("username")
                    text = h.get("text")
                    sent_at = h.get("sent_at", "")
                    time_part = sent_at[-8:] if len(sent_at) >= 8 else "History"
                    print(f"[{time_part}] {username}: {text}")
                print("================================================================")

            elif packet.message_type == "PM_HISTORY":
                history = payload.get("history", [])
                print(f"\n============= PRIVATE MESSAGES HISTORY ({len(history)} messages) =============")
                for h in history:
                    sender = h.get("sender")
                    receiver = h.get("receiver")
                    text = h.get("text")
                    sent_at = h.get("sent_at", "")
                    time_part = sent_at[-8:] if len(sent_at) >= 8 else "History"
                    print(f"[{time_part}] {sender} -> {receiver}: {text}")
                print("=========================================================================")

            elif packet.message_type == "ERROR":
                # Check if this error relates to an active file upload
                # Forward to file queue so uploader thread doesn't freeze waiting
                client.file_events_queue.put(packet)
                print(f"\n[ERROR MESSAGE]: {payload.get('message')}")
            else:
                print(f"\n[PACKET RECEIVED]: {packet}")
                
            client.receive_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            if client.running:
                logger.error(f"Error in printing thread: {e}")
            break

# ================= CLIENT SIDE UPLOADER THREAD =================

def file_uploader_worker(client, filepath):
    """Worker thread running chunked uploads, calculating hashes, seeks, and progress bars."""
    if not os.path.exists(filepath):
        print(f"\n[UPLOAD ERROR] Local file not found at path: {filepath}")
        return

    filename = os.path.basename(filepath)
    filesize = os.stat(filepath).st_size
    
    # Enforce Client-side max size check (50MB)
    max_limit = 50 * 1024 * 1024
    if filesize > max_limit:
        print(f"\n[UPLOAD ERROR] File '{filename}' exceeds maximum allowed size of 50MB.")
        return

    # 1. Compute SHA-256 checksum
    print(f"\n[UPLOAD] Computing integrity checksum for '{filename}'...")
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while True:
                block = f.read(65536)
                if not block:
                    break
                sha256.update(block)
        checksum = sha256.hexdigest()
    except Exception as e:
        print(f"\n[UPLOAD ERROR] Failed to calculate file checksum: {e}")
        return

    # 2. Initiate handshake
    init_packet = Packet(
        message_type="FILE_INIT",
        sender=None,
        receiver=None,
        room=None,
        payload={"filename": filename, "filesize": filesize, "chunk_size": 32768, "checksum": checksum}
    )
    
    # Clear file events queue
    while not client.file_events_queue.empty():
        client.file_events_queue.get_nowait()

    client.send_packet(init_packet)

    # 3. Wait for handshake response
    try:
        resp = client.file_events_queue.get(timeout=5)
        if resp.message_type == "ERROR":
            print(f"\n[UPLOAD FAILED] Server rejected initiation: {resp.payload.get('message')}")
            return
            
        payload = resp.payload or {}
        transfer_id = payload.get("transfer_id")
        offset = payload.get("offset", 0)
    except queue.Empty:
        print("\n[UPLOAD ERROR] Request timeout waiting for server response.")
        return

    # 4. Stream data chunks from offset (Resume support)
    chunk_size = 32768  # 32 KB
    
    try:
        with open(filepath, "rb") as f:
            f.seek(offset)
            bytes_sent = offset
            chunk_index = 0
            
            print(f"\n[UPLOAD START] Resuming/Starting upload at offset={offset} bytes...")
            
            while True:
                data_bytes = f.read(chunk_size)
                is_eof = len(data_bytes) < chunk_size or bytes_sent + len(data_bytes) >= filesize
                
                # Base64 encode chunk
                data_b64 = base64.b64encode(data_bytes).decode('utf-8')
                
                data_packet = Packet(
                    message_type="FILE_DATA",
                    sender=None,
                    receiver=None,
                    room=None,
                    payload={
                        "transfer_id": transfer_id,
                        "chunk_index": chunk_index,
                        "offset": bytes_sent,
                        "data": data_b64,
                        "is_eof": is_eof
                    }
                )
                client.send_packet(data_packet)
                
                # Wait for server progress acknowledgment
                prog_resp = client.file_events_queue.get(timeout=5)
                if prog_resp.message_type == "ERROR":
                    print(f"\n[UPLOAD FAILED] Server error during streaming: {prog_resp.payload.get('message')}")
                    return
                    
                prog_payload = prog_resp.payload or {}
                bytes_sent = prog_payload.get("bytes_written", bytes_sent)
                percentage = prog_payload.get("progress_percentage", 0.0)
                
                # Render ASCII Terminal Progress Bar
                bar_len = 20
                filled_len = int(round(bar_len * (percentage / 100)))
                bar = '█' * filled_len + '░' * (bar_len - filled_len)
                sys.stdout.write(
                    f"\r[UPLOAD] [{bar}] {percentage}% ({bytes_sent / (1024*1024):.2f} MB / {filesize / (1024*1024):.2f} MB)"
                )
                sys.stdout.flush()
                
                if is_eof or bytes_sent >= filesize:
                    break
                    
                chunk_index += 1
                
        # 5. Wait for server complete validation response
        print(f"\n[UPLOAD] Upload finished. Waiting for server integrity checks...")
        comp_resp = client.file_events_queue.get(timeout=10)
        if comp_resp.message_type == "FILE_COMPLETE":
            print(f"[UPLOAD SUCCESS] File '{filename}' successfully sent and verified! (SHA-256: {comp_resp.payload.get('sha256_hash')})")
        else:
            print(f"[UPLOAD FAILED] Server rejected file finalization: {comp_resp.payload.get('message')}")
            
    except Exception as e:
        print(f"\n[UPLOAD ERROR] Exception occurred during upload stream: {e}")

# ================= CLIENT APP LOOP =================

def main():
    setup_logger("client")
    logger.info("Initializing TCP Socket Client with FTProto Support...")

    client = SocketClient(host="127.0.0.1", port=8080)
    client.start()

    # Start queue printer thread
    printer_thread = threading.Thread(
        target=printer_worker, 
        args=(client,), 
        name="QueuePrinter", 
        daemon=True
    )
    printer_thread.start()

    time.sleep(0.5)

    print("\n================ ACTIONS ===================")
    print("  /register <username> <password>")
    print("  /login <username> <password>")
    print("  /logout")
    print("  /sendfile <filepath>   (FTProto chunked send)")
    print("  /online                (Retrieve online list)")
    print("  /msg <username> <message> (Private message)")
    print("  /create <room_name>")
    print("  /delete <room_name>")
    print("  /join <room_name>")
    print("  /leave <room_name>")
    print("  /select <room_name>    (Switch current chat context)")
    print("  /status                (Show joined channels list)")
    print("  /exit")
    print("  Type any other text to send to active room")
    print("============================================")

    try:
        while client.running:
            prompt = f"\n[#{state.current_room}] Enter input: "
            user_input = input(prompt).strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                parts = user_input.split()
                cmd = parts[0].lower()

                if cmd == "/exit":
                    break

                elif cmd == "/register":
                    if len(parts) < 3:
                        print("Usage: /register <username> <password>")
                        continue
                    username = parts[1]
                    password = parts[2]
                    packet = Packet(
                        message_type="REGISTER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"username": username, "password": password}
                    )
                    client.send_packet(packet)

                elif cmd == "/login":
                    if len(parts) < 3:
                        print("Usage: /login <username> <password>")
                        continue
                    username = parts[1]
                    password = parts[2]
                    packet = Packet(
                        message_type="LOGIN",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"username": username, "password": password}
                    )
                    client.send_packet(packet)

                elif cmd == "/logout":
                    packet = Packet(
                        message_type="LOGOUT",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={}
                    )
                    client.send_packet(packet)

                elif cmd == "/sendfile":
                    if len(parts) < 2:
                        print("Usage: /sendfile <filepath>")
                        continue
                    filepath = " ".join(parts[1:])
                    # Launch file upload on a separate worker thread
                    upload_thread = threading.Thread(
                        target=file_uploader_worker,
                        args=(client, filepath),
                        name="UploaderWorker",
                        daemon=True
                    )
                    upload_thread.start()

                elif cmd == "/online":
                    packet = Packet(
                        message_type="GET_ONLINE_LIST",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={}
                    )
                    client.send_packet(packet)

                elif cmd == "/msg":
                    if len(parts) < 3:
                        print("Usage: /msg <username> <message>")
                        continue
                    recipient = parts[1]
                    msg_body = " ".join(parts[2:])
                    packet = Packet(
                        message_type="PM",
                        sender=None,
                        receiver=recipient,
                        room=None,
                        payload={"text": msg_body}
                    )
                    client.send_packet(packet)

                elif cmd == "/create":
                    if len(parts) < 2:
                        print("Usage: /create <room_name>")
                        continue
                    room = parts[1]
                    packet = Packet(
                        message_type="CREATE_ROOM",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"room": room}
                    )
                    client.send_packet(packet)

                elif cmd == "/delete":
                    if len(parts) < 2:
                        print("Usage: /delete <room_name>")
                        continue
                    room = parts[1]
                    packet = Packet(
                        message_type="DELETE_ROOM",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"room": room}
                    )
                    client.send_packet(packet)

                elif cmd == "/join":
                    if len(parts) < 2:
                        print("Usage: /join <room_name>")
                        continue
                    room = parts[1]
                    packet = Packet(
                        message_type="JOIN_ROOM",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"room": room}
                    )
                    client.send_packet(packet)

                elif cmd == "/leave":
                    if len(parts) < 2:
                        print("Usage: /leave <room_name>")
                        continue
                    room = parts[1]
                    packet = Packet(
                        message_type="LEAVE_ROOM",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"room": room}
                    )
                    client.send_packet(packet)

                elif cmd == "/select":
                    if len(parts) < 2:
                        print("Usage: /select <room_name>")
                        continue
                    room = parts[1]
                    if room in state.joined_rooms:
                        state.current_room = room
                        print(f"Chat context switched to: #{room}")
                    else:
                        print(f"You cannot select #{room} because you have not joined it. Use /join {room} first.")

                elif cmd == "/status":
                    print(f"Joined channels: {list(state.joined_rooms)}")
                    print(f"Current target context: #{state.current_room}")

                # Admin commands
                elif cmd == "/kick":
                    if len(parts) < 3:
                        print("Usage: /kick <username> <room>")
                        continue
                    target = parts[1]
                    room = parts[2]
                    packet = Packet(
                        message_type="KICK_USER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"target": target, "room": room}
                    )
                    client.send_packet(packet)

                elif cmd == "/ban":
                    if len(parts) < 2:
                        print("Usage: /ban <username>")
                        continue
                    target = parts[1]
                    packet = Packet(
                        message_type="BAN_USER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"target": target}
                    )
                    client.send_packet(packet)

                elif cmd == "/mute":
                    if len(parts) < 2:
                        print("Usage: /mute <username>")
                        continue
                    target = parts[1]
                    packet = Packet(
                        message_type="MUTE_USER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"target": target}
                    )
                    client.send_packet(packet)

                elif cmd == "/unmute":
                    if len(parts) < 2:
                        print("Usage: /unmute <username>")
                        continue
                    target = parts[1]
                    packet = Packet(
                        message_type="UNMUTE_USER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"target": target}
                    )
                    client.send_packet(packet)

                elif cmd == "/promote":
                    if len(parts) < 3:
                        print("Usage: /promote <username> <Admin|Moderator>")
                        continue
                    target = parts[1]
                    role = parts[2]
                    packet = Packet(
                        message_type="PROMOTE_USER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"target": target, "role": role}
                    )
                    client.send_packet(packet)

                elif cmd == "/demote":
                    if len(parts) < 2:
                        print("Usage: /demote <username>")
                        continue
                    target = parts[1]
                    packet = Packet(
                        message_type="PROMOTE_USER",
                        sender=None,
                        receiver=None,
                        room=None,
                        payload={"target": target, "role": "User"}
                    )
                    client.send_packet(packet)

                else:
                    print("Unknown command. Type /status to check available parameters.")
            else:
                packet = Packet(
                    message_type="MSG",
                    sender=None,
                    receiver=None,
                    room=state.current_room,
                    payload={"text": user_input}
                )
                client.send_packet(packet)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        client.disconnect()
        logger.info("Client terminated.")

if __name__ == "__main__":
    main()
