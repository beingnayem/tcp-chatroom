import socket
import ssl
import threading
import logging
import time
import os
import base64
import hashlib
from common.protocol import Packet, receive_framed_packet, send_framed_packet
from server.db_manager import DatabaseManager, DatabaseError
from server.auth import register_user, login_user

logger = logging.getLogger("server")

class SocketServer:
    def __init__(self, host="0.0.0.0", port=8080):
        self.host = host
        self.port = port
        self.server_socket = None
        self.clients = {}  # client_address -> client_socket
        self.sessions = {}  
        self.client_rooms = {}  # client_address -> set(room_name)
        
        self.muted_users = set()
        
        self.lock = threading.Lock()
        self.running = False
        
        # Directories & Paths
        self.cert_file = "server.crt"
        self.key_file = "server.key"
        
        # Threads
        self.accept_thread = None
        self.presence_thread = None
        
        # SQLite Database Manager
        self.db_manager = DatabaseManager("chat_room.db")
        self._ensure_default_room()

    def _ensure_default_room(self):
        try:
            self.db_manager.execute(
                "INSERT OR IGNORE INTO rooms (name, type) VALUES ('General', 'Public');"
            )
        except DatabaseError as e:
            logger.error(f"Error ensuring default room: {e}")

    def start(self):
        """Initializes TLS context, binds the socket, and begins listening for client connections."""
        # 1. Check for SSL Certificates
        if not os.path.exists(self.cert_file) or not os.path.exists(self.key_file):
            logger.critical("\n" + "="*80 + "\n"
                            "SSL ERROR: TLS Certificate files 'server.crt' or 'server.key' not found!\n"
                            "Please run the following command to generate self-signed keys for local testing:\n\n"
                            f"openssl req -new -newkey rsa:2048 -days 365 -nodes -x509 -keyout {self.key_file} -out {self.cert_file} -subj \"/CN=localhost\"\n"
                            + "="*80)
            return False

        # Create TLS Server Context
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            self.ssl_context.load_cert_chain(certfile=self.cert_file, keyfile=self.key_file)
            logger.info("TLS certificate chain loaded successfully.")
        except Exception as e:
            logger.critical(f"Failed to load SSL context chain: {e}")
            return False

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen()
            self.running = True
            logger.info(f"TCP Server bound and listening on {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to bind socket: {e}")
            self.server_socket.close()
            return False

        # Spawn acceptor thread
        self.accept_thread = threading.Thread(
            target=self._accept_loop, 
            name="AcceptorThread", 
            daemon=True
        )
        self.accept_thread.start()

        # Spawn presence thread
        self.presence_thread = threading.Thread(
            target=self._presence_monitor_loop,
            name="PresenceMonitor",
            daemon=True
        )
        self.presence_thread.start()
        
        return True

    def _accept_loop(self):
        while self.running:
            try:
                raw_socket, client_address = self.server_socket.accept()
                if not self.running:
                    raw_socket.close()
                    break

                logger.info(f"Accepted raw TCP connection from client: {client_address}. Wrapping in TLS...")
                
                # Wrap socket in TLS encryption
                try:
                    ssl_socket = self.ssl_context.wrap_socket(raw_socket, server_side=True)
                    logger.info(f"TLS handshake successful with client: {client_address}")
                except Exception as ssl_err:
                    logger.error(f"TLS handshake failed with client {client_address}: {ssl_err}")
                    raw_socket.close()
                    continue

                with self.lock:
                    self.clients[client_address] = ssl_socket
                    self.client_rooms[client_address] = set()

                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(ssl_socket, client_address),
                    name=f"ClientHandler-{client_address}",
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.running:
                    logger.error(f"Error accepting connection: {e}")
                break

    def _handle_client(self, client_socket, client_address):
        logger.info(f"Client handler thread started for {client_address}")
        
        while self.running:
            try:
                packet = receive_framed_packet(client_socket)
                if not packet:
                    logger.info(f"Client disconnected gracefully: {client_address}")
                    break
                
                self._update_activity(client_address)
                self._process_packet(client_socket, client_address, packet)
            except ConnectionError:
                logger.warning(f"Connection reset abruptly by peer: {client_address}")
                break
            except Exception as e:
                if self.running:
                    logger.error(f"Error handling socket data for {client_address}: {e}")
                break

        self._disconnect_client(client_address)

    def _process_packet(self, client_socket, client_address, packet):
        """Processes incoming requests, enforcing authentication, room, and FTProto constraints."""
        mtype = packet.message_type
        payload = packet.payload or {}

        # 1. Registration / Login requests do not require active authentication
        if mtype == "REGISTER":
            username = payload.get("username", "")
            password = payload.get("password", "")
            success, msg = register_user(self.db_manager, username, password)
            
            if success:
                logger.info(f"Registration success: New user '{username}' registered from {client_address}")
            else:
                logger.warning(f"Registration failure: User '{username}' registration failed from {client_address}: {msg}")
            
            resp = Packet(
                message_type="REGISTER_RESP",
                sender="SERVER",
                receiver=username,
                room=None,
                payload={"success": success, "message": msg}
            )
            send_framed_packet(client_socket, resp)
            return

        elif mtype == "LOGIN":
            username = payload.get("username", "")
            password = payload.get("password", "")
            success, msg = login_user(self.db_manager, username, password)
            
            role = "User"
            if success:
                user_info = self.db_manager.fetch_one(
                    "SELECT id FROM users WHERE username = ?;", (username,)
                )
                user_id = user_info["id"]
                
                perm_info = self.db_manager.fetch_one(
                    "SELECT role FROM permissions WHERE user_id = ?;", (user_id,)
                )
                role = perm_info["role"] if perm_info else "User"
                
                with self.lock:
                    self.sessions[client_address] = {
                        "username": username,
                        "id": user_id,
                        "status": "Online",
                        "last_active": time.time(),
                        "role": role
                    }
                
                self._update_db_presence(user_id, "Online")
                self._restore_persisted_rooms(client_address, user_id)
                self._broadcast_presence_change(username, "Online")
                logger.info(f"Authentication success: User '{username}' (Role: {role}) logged in from {client_address}")
            else:
                logger.warning(f"Authentication failure: User '{username}' login failed from {client_address}: {msg}")
            
            resp = Packet(
                message_type="LOGIN_RESP",
                sender="SERVER",
                receiver=username,
                room=None,
                payload={"success": success, "message": f"{msg} (Role: {role})" if success else msg}
            )
            send_framed_packet(client_socket, resp)

            if success:
                # Restore channels list status to client
                with self.lock:
                    joined = list(self.client_rooms[client_address])
                status_packet = Packet(
                    message_type="ROOMS_STATUS",
                    sender="SERVER",
                    receiver=username,
                    room=None,
                    payload={"joined_rooms": joined}
                )
                send_framed_packet(client_socket, status_packet)
                
                # Send private message history (PMs)
                self._send_pm_history(client_socket, user_id, username)
            return

        # 2. Enforce authentication for all other actions
        with self.lock:
            session = self.sessions.get(client_address)

        if not session:
            logger.warning(f"Rejected unauthenticated packet type '{mtype}' from {client_address}")
            resp = Packet(
                message_type="ERROR",
                sender="SERVER",
                receiver=None,
                room=None,
                payload={"message": "Unauthorized. You must log in first."}
            )
            send_framed_packet(client_socket, resp)
            return

        logged_in_user = session["username"]
        user_id = session["id"]
        user_role = session["role"]

        # 3. Process authorized requests
        if mtype == "LOGOUT":
            self._update_db_presence(user_id, "Offline")
            with self.lock:
                self.sessions.pop(client_address, None)
                self.client_rooms[client_address] = set()
            self._broadcast_presence_change(logged_in_user, "Offline")
            
            resp = Packet(
                message_type="LOGOUT_RESP",
                sender="SERVER",
                receiver=logged_in_user,
                room=None,
                payload={"success": True, "message": "Logged out successfully."}
            )
            send_framed_packet(client_socket, resp)
            logger.info(f"User '{logged_in_user}' logged out from {client_address}")

        elif mtype == "GET_ONLINE_LIST":
            room_name = payload.get("room", "General").strip() or "General"
            try:
                if room_name == "General":
                    users_data = self.db_manager.fetch_all("""
                        SELECT username, status FROM users
                        ORDER BY CASE status
                            WHEN 'Online' THEN 1
                            WHEN 'Idle' THEN 2
                            WHEN 'Offline' THEN 3
                            ELSE 4
                        END ASC, username ASC;
                    """)
                else:
                    users_data = self.db_manager.fetch_all("""
                        SELECT users.username, users.status
                        FROM room_members
                        JOIN users ON room_members.user_id = users.id
                        WHERE room_members.room_id = (SELECT id FROM rooms WHERE name = ?)
                        ORDER BY CASE users.status
                            WHEN 'Online' THEN 1
                            WHEN 'Idle' THEN 2
                            WHEN 'Offline' THEN 3
                            ELSE 4
                        END ASC, users.username ASC;
                    """, (room_name,))
                
                resp = Packet(
                    message_type="ONLINE_LIST_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=room_name,
                    payload={"online_users": users_data}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Error fetching room members: {e}")

        elif mtype == "PM":
            recipient_username = packet.receiver
            message_text = payload.get("text", "")
            if not recipient_username:
                self._send_error(client_socket, "Recipient username must be specified.")
                return
            if recipient_username == logged_in_user:
                self._send_error(client_socket, "You cannot send a private message to yourself.")
                return
            recipient = self.db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (recipient_username,))
            if not recipient:
                self._send_error(client_socket, f"User '{recipient_username}' does not exist.")
                return
            recipient_id = recipient["id"]
            try:
                self.db_manager.execute(
                    "INSERT INTO messages (sender_id, recipient_id, content) VALUES (?, ?, ?);",
                    (user_id, recipient_id, message_text)
                )
            except DatabaseError as e:
                logger.error(f"Failed to persist PM to database: {e}")

            logger.info(f"Private Message sent from '{logged_in_user}' to '{recipient_username}': {message_text}")

            pm_packet = Packet(
                message_type="PM",
                sender=logged_in_user,
                receiver=recipient_username,
                room=None,
                payload={"text": message_text},
                timestamp=time.time()
            )
            recipient_address, recipient_socket = self._get_online_user_socket(recipient_username)
            if recipient_socket:
                try:
                    send_framed_packet(recipient_socket, pm_packet)
                except Exception as e:
                    logger.error(f"Failed to deliver PM: {e}")
            else:
                system_resp = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"message": f"User '{recipient_username}' is currently offline. Your message has been saved."}
                )
                send_framed_packet(client_socket, system_resp)

        # ================= ADMINISTRATIVE / RBAC MODERATION HANDLERS =================

        elif mtype == "CREATE_ROOM":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied: Only Admins and Moderators can create rooms.")
                return
            room_name = payload.get("room", "").strip()
            if not room_name:
                self._send_error(client_socket, "Room name cannot be empty.")
                return
            try:
                self.db_manager.execute(
                    "INSERT INTO rooms (name, creator_id) VALUES (?, ?);",
                    (room_name, user_id)
                )
                self._join_room_logic(client_address, user_id, room_name)
                
                # Auto-append newly created rooms for all online Admins/Moderators
                with self.lock:
                    for addr, sess in self.sessions.items():
                        if sess["role"] in ["Admin", "Moderator"]:
                            self.client_rooms[addr].add(room_name)
                            sock = self.clients.get(addr)
                            if sock:
                                notify = Packet(
                                    message_type="CREATE_ROOM_RESP",
                                    sender="SERVER",
                                    receiver=sess["username"],
                                    payload={"success": True, "room": room_name, "message": f"Room '{room_name}' created successfully."}
                                )
                                try:
                                    send_framed_packet(sock, notify)
                                except Exception:
                                    pass

                self._log_audit("INFO", f"Room '{room_name}' was created by '{logged_in_user}' (Role: {user_role}).")
            except DatabaseError:
                self._send_error(client_socket, f"Failed to create room '{room_name}'. It may already exist.")

        elif mtype == "DELETE_ROOM":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied: Only Admins and Moderators can delete rooms.")
                return
            room_name = payload.get("room", "").strip()
            if not room_name or room_name == "General":
                self._send_error(client_socket, "Invalid room deletion request.")
                return
            try:
                self.db_manager.execute("DELETE FROM rooms WHERE name = ?;", (room_name,))
                
                # Discard from all client room memberships and notify active recipients
                with self.lock:
                    active_addrs = list(self.sessions.keys())
                for addr in active_addrs:
                    with self.lock:
                        had_room = room_name in self.client_rooms.get(addr, set())
                        self.client_rooms[addr].discard(room_name)
                        sock = self.clients.get(addr)
                        username = self.sessions[addr]["username"]
                    if had_room and sock:
                        resp = Packet(
                            message_type="DELETE_ROOM_RESP",
                            sender="SERVER",
                            receiver=username,
                            payload={"success": True, "room": room_name, "message": f"Room '{room_name}' has been deleted."}
                        )
                        try:
                            send_framed_packet(sock, resp)
                        except Exception:
                            pass
                            
                self._log_audit("INFO", f"Room '{room_name}' was deleted by '{logged_in_user}' (Role: {user_role}).")
            except DatabaseError as e:
                self._send_error(client_socket, f"Error deleting room: {e}")

        elif mtype == "KICK_USER":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied: Only Admins and Moderators can kick users.")
                return
            target_username = payload.get("target", "").strip()
            room_name = payload.get("room", "").strip()
            if not target_username or not room_name:
                self._send_error(client_socket, "Target user and room name must be specified.")
                return
            target_addr, target_socket = self._get_online_user_socket(target_username)
            if not target_addr:
                self._send_error(client_socket, f"User '{target_username}' is not currently online.")
                return
            with self.lock:
                target_joined = room_name in self.client_rooms.get(target_addr, set())
            if not target_joined:
                self._send_error(client_socket, f"User '{target_username}' is not in room '{room_name}'.")
                return
            try:
                target_user = self.db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (target_username,))
                room_info = self.db_manager.fetch_one("SELECT id FROM rooms WHERE name = ?;", (room_name,))
                if target_user and room_info:
                    self.db_manager.execute(
                        "DELETE FROM room_members WHERE room_id = ? AND user_id = ?;",
                        (room_info["id"], target_user["id"])
                    )
                with self.lock:
                    self.client_rooms[target_addr].discard(room_name)
                self._log_audit("WARNING", f"User '{target_username}' was kicked from room '{room_name}' by '{logged_in_user}' (Role: {user_role}).")
                kick_packet = Packet(
                    message_type="KICKED",
                    sender=logged_in_user,
                    receiver=target_username,
                    room=room_name,
                    payload={"message": f"You have been kicked from #{room_name} by {logged_in_user}."}
                )
                send_framed_packet(target_socket, kick_packet)
                confirm_resp = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"message": f"Successfully kicked '{target_username}' from room '{room_name}'."}
                )
                send_framed_packet(client_socket, confirm_resp)
                room_notice = Packet(
                    message_type="MSG",
                    sender="SERVER",
                    receiver=None,
                    room=room_name,
                    payload={"text": f"User '{target_username}' has been kicked from the channel by {logged_in_user}."}
                )
                self._broadcast_to_room(room_name, room_notice)
            except DatabaseError as e:
                self._send_error(client_socket, f"Error kicking user: {e}")

        elif mtype == "ADD_USER_TO_ROOM":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied: Only Admins and Moderators can add users to rooms.")
                return
            target_username = payload.get("target", "").strip()
            room_name = payload.get("room", "").strip()
            if not target_username or not room_name:
                self._send_error(client_socket, "Target user and room name must be specified.")
                return
            try:
                target_user = self.db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (target_username,))
                if not target_user:
                    self._send_error(client_socket, f"User '{target_username}' does not exist.")
                    return
                room_info = self.db_manager.fetch_one("SELECT id FROM rooms WHERE name = ?;", (room_name,))
                if not room_info:
                    self._send_error(client_socket, f"Room '{room_name}' does not exist.")
                    return
                
                self.db_manager.execute(
                    "INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?);",
                    (room_info["id"], target_user["id"])
                )
                
                target_addr, target_socket = self._get_online_user_socket(target_username)
                if target_addr:
                    with self.lock:
                        if target_addr in self.client_rooms:
                            self.client_rooms[target_addr].add(room_name)
                    
                    join_notice = Packet(
                        message_type="JOIN_ROOM_RESP",
                        sender="SERVER",
                        receiver=target_username,
                        room=room_name,
                        payload={"success": True, "message": f"You have been added to room '{room_name}' by '{logged_in_user}'."}
                    )
                    send_framed_packet(target_socket, join_notice)
                    self._send_room_history(target_socket, room_name)
                
                self._log_audit("INFO", f"User '{target_username}' was added to room '{room_name}' by '{logged_in_user}' (Role: {user_role}).")
                
                confirm_resp = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"message": f"Successfully added '{target_username}' to room '{room_name}'."}
                )
                send_framed_packet(client_socket, confirm_resp)
                
                room_notice = Packet(
                    message_type="MSG",
                    sender="SERVER",
                    receiver=None,
                    room=room_name,
                    payload={"text": f"User '{target_username}' has been added to the channel by {logged_in_user}."}
                )
                self._broadcast_to_room(room_name, room_notice)
                
            except DatabaseError as e:
                self._send_error(client_socket, f"Error adding user to room: {e}")

        elif mtype == "BAN_USER":
            if user_role != "Admin":
                self._send_error(client_socket, "Permission Denied: Only Admins can ban users.")
                return
            target_username = payload.get("target", "").strip()
            if not target_username:
                self._send_error(client_socket, "Target username must be specified.")
                return
            if target_username == logged_in_user:
                self._send_error(client_socket, "You cannot ban yourself.")
                return
            try:
                target_user = self.db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (target_username,))
                if not target_user:
                    self._send_error(client_socket, f"User '{target_username}' does not exist.")
                    return
                target_perm = self.db_manager.fetch_one("SELECT role FROM permissions WHERE user_id = ?;", (target_user["id"],))
                if target_perm and target_perm["role"] == "Admin":
                    self._send_error(client_socket, "Permission Denied: Cannot ban an Administrator.")
                    return
                self.db_manager.execute(
                    "UPDATE users SET status = 'Banned' WHERE id = ?;", (target_user["id"],)
                )
                self._log_audit("WARNING", f"User '{target_username}' was BANNED from the server by Admin '{logged_in_user}'.")
                target_addr, target_socket = self._get_online_user_socket(target_username)
                if target_socket:
                    ban_notice = Packet(
                        message_type="ERROR",
                        sender="SERVER",
                        receiver=target_username,
                        room=None,
                        payload={"message": "You have been banned from the server by an administrator."}
                    )
                    try:
                        send_framed_packet(target_socket, ban_notice)
                    except Exception:
                        pass
                    self._disconnect_client(target_addr)
                confirm_resp = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"message": f"User '{target_username}' has been banned."}
                )
                send_framed_packet(client_socket, confirm_resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Error banning user: {e}")

        elif mtype == "MUTE_USER":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied: Only Admins and Moderators can mute users.")
                return
            target_username = payload.get("target", "").strip()
            if not target_username:
                self._send_error(client_socket, "Target username must be specified.")
                return
            target_user = self.db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (target_username,))
            if not target_user:
                self._send_error(client_socket, f"User '{target_username}' does not exist.")
                return
            with self.lock:
                self.muted_users.add(target_username)
            self._log_audit("INFO", f"User '{target_username}' was muted by '{logged_in_user}' (Role: {user_role}).")
            resp = Packet(
                message_type="SYSTEM",
                sender="SERVER",
                receiver=logged_in_user,
                room=None,
                payload={"message": f"User '{target_username}' has been muted."}
            )
            send_framed_packet(client_socket, resp)
            target_addr, target_socket = self._get_online_user_socket(target_username)
            if target_socket:
                mute_notice = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=target_username,
                    room=None,
                    payload={"message": f"You have been muted by {logged_in_user}."}
                )
                send_framed_packet(target_socket, mute_notice)

        elif mtype == "UNMUTE_USER":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied: Only Admins and Moderators can unmute users.")
                return
            target_username = payload.get("target", "").strip()
            if not target_username:
                self._send_error(client_socket, "Target username must be specified.")
                return
            with self.lock:
                self.muted_users.discard(target_username)
            self._log_audit("INFO", f"User '{target_username}' was unmuted by '{logged_in_user}' (Role: {user_role}).")
            resp = Packet(
                message_type="SYSTEM",
                sender="SERVER",
                receiver=logged_in_user,
                room=None,
                payload={"message": f"User '{target_username}' has been unmuted."}
            )
            send_framed_packet(client_socket, resp)
            target_addr, target_socket = self._get_online_user_socket(target_username)
            if target_socket:
                unmute_notice = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=target_username,
                    room=None,
                    payload={"message": "You have been unmuted."}
                )
                send_framed_packet(target_socket, unmute_notice)

        elif mtype == "PROMOTE_USER":
            if user_role != "Admin":
                self._send_error(client_socket, "Permission Denied: Only Admins can manage user roles.")
                return
            target_username = payload.get("target", "").strip()
            new_role = payload.get("role", "").strip()
            if not target_username or new_role not in ["Admin", "Moderator", "User"]:
                self._send_error(client_socket, "Target username and valid role (Admin/Moderator/User) required.")
                return
            try:
                target_user = self.db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (target_username,))
                if not target_user:
                    self._send_error(client_socket, f"User '{target_username}' does not exist.")
                    return
                self.db_manager.execute(
                    "UPDATE permissions SET role = ? WHERE user_id = ?;",
                    (new_role, target_user["id"])
                )
                self._log_audit("INFO", f"User '{target_username}' role was updated to '{new_role}' by Admin '{logged_in_user}'.")
                target_addr, target_socket = self._get_online_user_socket(target_username)
                if target_socket:
                    with self.lock:
                        self.sessions[target_addr]["role"] = new_role
                    notice_packet = Packet(
                        message_type="ROLE_UPDATE",
                        sender="SERVER",
                        receiver=target_username,
                        room=None,
                        payload={"role": new_role, "message": f"Your role has been updated to {new_role}."}
                    )
                    send_framed_packet(target_socket, notice_packet)
                confirm_resp = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"message": f"Successfully updated '{target_username}' to role '{new_role}'."}
                )
                send_framed_packet(client_socket, confirm_resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Error updating user permissions: {e}")

        # ================= DASHBOARD ADMIN PORTAL REQUEST QUERIES =================

        elif mtype == "GET_ADMIN_STATS":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied.")
                return
            try:
                users_count = self.db_manager.fetch_one("SELECT COUNT(*) as count FROM users;")["count"]
                rooms_count = self.db_manager.fetch_one("SELECT COUNT(*) as count FROM rooms;")["count"]
                msg_count = self.db_manager.fetch_one("SELECT COUNT(*) as count FROM messages;")["count"]
                files_count = 0
                with self.lock:
                    online_count = len(self.sessions)
                resp = Packet(
                    message_type="ADMIN_STATS_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={
                        "total_users": users_count,
                        "total_rooms": rooms_count,
                        "total_messages": msg_count,
                        "total_files": files_count,
                        "online_users": online_count
                    }
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Database query error: {e}")

        elif mtype == "GET_BAN_LIST":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied.")
                return
            try:
                banned_rows = self.db_manager.fetch_all("SELECT username FROM users WHERE status = 'Banned';")
                banned_users = [row["username"] for row in banned_rows]
                resp = Packet(
                    message_type="BAN_LIST_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"banned_users": banned_users}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Database query error: {e}")

        elif mtype == "GET_SYSTEM_LOGS":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied.")
                return
            try:
                log_rows = self.db_manager.fetch_all("SELECT level, message, timestamp FROM logs ORDER BY timestamp DESC LIMIT 100;")
                logs = [{"level": r["level"], "message": r["message"], "timestamp": r["timestamp"]} for r in log_rows]
                resp = Packet(
                    message_type="SYSTEM_LOGS_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"logs": logs}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Database query error: {e}")

        elif mtype == "GET_ADMIN_ROOMS":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied.")
                return
            try:
                rooms_data = self.db_manager.fetch_all("""
                    SELECT rooms.id, rooms.name, rooms.created_at, users.username AS creator
                    FROM rooms
                    LEFT JOIN users ON rooms.creator_id = users.id;
                """)
                resp = Packet(
                    message_type="ADMIN_ROOMS_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"rooms": rooms_data}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Database query error: {e}")

        elif mtype == "GET_ALL_USERS":
            if user_role not in ["Admin", "Moderator"]:
                self._send_error(client_socket, "Permission Denied.")
                return
            try:
                user_rows = self.db_manager.fetch_all("""
                    SELECT users.username, users.status, permissions.role 
                    FROM users
                    LEFT JOIN permissions ON users.id = permissions.user_id;
                """)
                users = [{"username": r["username"], "status": r["status"], "role": r["role"] or "User"} for r in user_rows]
                resp = Packet(
                    message_type="ALL_USERS_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"users": users}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Database query error: {e}")

        elif mtype == "REVOKE_BAN":
            if user_role != "Admin":
                self._send_error(client_socket, "Permission Denied: Only Admins can revoke bans.")
                return
            target = payload.get("target", "").strip()
            if not target:
                self._send_error(client_socket, "Target username must be specified.")
                return
            try:
                self.db_manager.execute("UPDATE users SET status = 'Offline' WHERE username = ? AND status = 'Banned';", (target,))
                self._log_audit("INFO", f"Ban was revoked for user '{target}' by Admin '{logged_in_user}'.")
                resp = Packet(
                    message_type="SYSTEM",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"message": f"Successfully revoked ban for user '{target}'."}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Database error: {e}")

        # Standard join/leave commands
        elif mtype == "JOIN_ROOM":
            room_name = payload.get("room", "").strip()
            if not room_name:
                self._send_error(client_socket, "Room name required to join.")
                return
            room = self.db_manager.fetch_one("SELECT id FROM rooms WHERE name = ?;", (room_name,))
            if not room:
                self._send_error(client_socket, f"Room '{room_name}' does not exist.")
                return
            success = self._join_room_logic(client_address, user_id, room_name)
            if success:
                resp = Packet(
                    message_type="JOIN_ROOM_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=room_name,
                    payload={"success": True, "message": f"Joined room '{room_name}'."}
                )
                send_framed_packet(client_socket, resp)
                self._send_room_history(client_socket, room_name)
            else:
                self._send_error(client_socket, f"Failed to join room '{room_name}'.")

        elif mtype == "GET_ROOMS_LIST":
            try:
                rooms = self.db_manager.fetch_all("SELECT name FROM rooms;")
                room_names = [r["name"] for r in rooms]
                resp = Packet(
                    message_type="ROOMS_LIST_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=None,
                    payload={"rooms": room_names}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Error fetching rooms list: {e}")

        elif mtype == "GET_ROOM_HISTORY":
            room_name = payload.get("room", "").strip()
            if not room_name:
                self._send_error(client_socket, "Room name required to fetch history.")
                return
            with self.lock:
                joined_rooms = self.client_rooms.get(client_address, set())
            if room_name in joined_rooms:
                self._send_room_history(client_socket, room_name)
            else:
                self._send_error(client_socket, f"Access Denied: You are not a member of room '{room_name}'.")

        elif mtype == "LEAVE_ROOM":
            room_name = payload.get("room", "").strip()
            if not room_name or room_name == "General":
                self._send_error(client_socket, "You cannot leave the default General room.")
                return
            with self.lock:
                joined_rooms = self.client_rooms.get(client_address, set())
            if room_name not in joined_rooms:
                self._send_error(client_socket, f"You are not a member of room '{room_name}'.")
                return
            try:
                room_info = self.db_manager.fetch_one("SELECT id FROM rooms WHERE name = ?;", (room_name,))
                if room_info:
                    self.db_manager.execute(
                        "DELETE FROM room_members WHERE room_id = ? AND user_id = ?;",
                        (room_info["id"], user_id)
                    )
                with self.lock:
                    self.client_rooms[client_address].discard(room_name)
                resp = Packet(
                    message_type="LEAVE_ROOM_RESP",
                    sender="SERVER",
                    receiver=logged_in_user,
                    room=room_name,
                    payload={"success": True, "message": f"Left room '{room_name}'."}
                )
                send_framed_packet(client_socket, resp)
            except DatabaseError as e:
                self._send_error(client_socket, f"Error leaving room: {e}")

        elif mtype == "MSG":
            with self.lock:
                is_muted = logged_in_user in self.muted_users
            if is_muted:
                self._send_error(client_socket, "You have been muted by a moderator and cannot send messages.")
                return
            room_name = packet.room
            if not room_name:
                self._send_error(client_socket, "A target room name must be specified to send a message.")
                return
            with self.lock:
                joined_rooms = self.client_rooms.get(client_address, set())
            if room_name not in joined_rooms:
                self._send_error(client_socket, f"Access Denied: You must join room '{room_name}' before sending messages.")
                return
            message_text = payload.get("text", "")
            try:
                room_info = self.db_manager.fetch_one("SELECT id FROM rooms WHERE name = ?;", (room_name,))
                if room_info:
                    self.db_manager.execute(
                        "INSERT INTO messages (sender_id, room_id, content) VALUES (?, ?, ?);",
                        (user_id, room_info["id"], message_text)
                    )
            except DatabaseError as e:
                logger.error(f"Failed to persist room chat message: {e}")
            
            logger.info(f"Message from '{logged_in_user}' broadcast to room '{room_name}': {message_text}")
            
            broadcast_packet = Packet(
                message_type="MSG",
                sender=logged_in_user,
                receiver=None,
                room=room_name,
                payload={"text": message_text},
                timestamp=time.time()
            )
            self._broadcast_to_room(room_name, broadcast_packet)

        else:
            resp = Packet(
                message_type="ERROR",
                sender="SERVER",
                receiver=logged_in_user,
                room=None,
                payload={"message": f"Action '{mtype}' is not recognized."}
            )
            send_framed_packet(client_socket, resp)

    # ================= LOGICAL & AUDIT UTILITIES =================

    def _log_audit(self, level, message):
        logger.info(f"AUDIT [{level}] - {message}")
        try:
            self.db_manager.execute(
                "INSERT INTO logs (level, source, message) VALUES (?, 'SERVER', ?);",
                (level, message)
            )
        except DatabaseError as e:
            logger.error(f"Failed to write audit log to database: {e}")

    def _update_activity(self, client_address):
        with self.lock:
            session = self.sessions.get(client_address)
        if session:
            session["last_active"] = time.time()
            if session["status"] == "Idle":
                session["status"] = "Online"
                username = session["username"]
                user_id = session["id"]
                logger.info(f"User '{username}' is active again. Restoring status to Online.")
                self._update_db_presence(user_id, "Online")
                self._broadcast_presence_change(username, "Online")

    def _update_db_presence(self, user_id, status):
        try:
            self.db_manager.execute(
                "UPDATE users SET status = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?;",
                (status, user_id)
            )
        except DatabaseError as e:
            logger.error(f"Failed to update database user status: {e}")

    def _broadcast_presence_change(self, username, status):
        presence_packet = Packet(
            message_type="PRESENCE",
            sender="SERVER",
            receiver=None,
            room=None,
            payload={"username": username, "status": status, "timestamp": time.time()}
        )
        self._broadcast_to_authenticated(presence_packet)

    def _presence_monitor_loop(self):
        logger.info("Presence monitor loop started.")
        idle_threshold = 30
        while self.running:
            time.sleep(5)
            with self.lock:
                active_addresses = list(self.sessions.keys())
            for addr in active_addresses:
                with self.lock:
                    session = self.sessions.get(addr)
                if session and session["status"] == "Online":
                    inactive_duration = time.time() - session["last_active"]
                    if inactive_duration > idle_threshold:
                        username = session["username"]
                        user_id = session["id"]
                        logger.info(f"User '{username}' has gone idle (inactive for {inactive_duration:.1f}s)")
                        with self.lock:
                            session["status"] = "Idle"
                        self._update_db_presence(user_id, "Idle")
                        self._broadcast_presence_change(username, "Idle")

    def _get_online_user_socket(self, username):
        with self.lock:
            for addr, session in self.sessions.items():
                if session["username"] == username:
                    return addr, self.clients.get(addr)
        return None, None

    def _send_pm_history(self, client_socket, user_id, username):
        try:
            history_rows = self.db_manager.fetch_all("""
                SELECT messages.content, sender_user.username AS sender, recipient_user.username AS receiver, messages.sent_at 
                FROM messages 
                JOIN users AS sender_user ON messages.sender_id = sender_user.id 
                JOIN users AS recipient_user ON messages.recipient_id = recipient_user.id
                WHERE (messages.sender_id = ? OR messages.recipient_id = ?) AND messages.room_id IS NULL
                ORDER BY messages.sent_at ASC 
                LIMIT 50;
            """, (user_id, user_id))
            history_payload = []
            for row in history_rows:
                history_payload.append({
                    "sender": row["sender"],
                    "receiver": row["receiver"],
                    "text": row["content"],
                    "sent_at": row["sent_at"]
                })
            history_packet = Packet(
                message_type="PM_HISTORY",
                sender="SERVER",
                receiver=username,
                room=None,
                payload={"history": history_payload}
            )
            send_framed_packet(client_socket, history_packet)
        except DatabaseError as e:
            logger.error(f"Error fetching PM history: {e}")

    def _restore_persisted_rooms(self, client_address, user_id):
        try:
            # Check user role context
            user_perm = self.db_manager.fetch_one("SELECT role FROM permissions WHERE user_id = ?;", (user_id,))
            role = user_perm["role"] if user_perm else "User"
            
            if role in ["Admin", "Moderator"]:
                # Admins and Moderators automatically restore ALL rooms
                all_rooms = self.db_manager.fetch_all("SELECT name FROM rooms;")
                with self.lock:
                    self.client_rooms[client_address] = set(r["name"] for r in all_rooms)
            else:
                persisted_rooms = self.db_manager.fetch_all("""
                    SELECT rooms.name FROM rooms
                    JOIN room_members ON rooms.id = room_members.room_id
                    WHERE room_members.user_id = ?;
                """, (user_id,))
                with self.lock:
                    self.client_rooms[client_address] = set(r["name"] for r in persisted_rooms)
            
            # Ensure "General" default room is present
            with self.lock:
                self.client_rooms[client_address].add("General")
        except DatabaseError as e:
            logger.error(f"Failed to restore rooms for user_id={user_id}: {e}")

    def _join_room_logic(self, client_address, user_id, room_name):
        try:
            room = self.db_manager.fetch_one("SELECT id FROM rooms WHERE name = ?;", (room_name,))
            if room:
                self.db_manager.execute(
                    "INSERT OR IGNORE INTO room_members (room_id, user_id) VALUES (?, ?);",
                    (room["id"], user_id)
                )
                with self.lock:
                    self.client_rooms[client_address].add(room_name)
                return True
            return False
        except DatabaseError as e:
            logger.error(f"Error executing join room operations: {e}")
            return False

    def _send_room_history(self, client_socket, room_name):
        try:
            history_rows = self.db_manager.fetch_all("""
                SELECT messages.content, users.username, messages.sent_at 
                FROM messages 
                JOIN users ON messages.sender_id = users.id 
                JOIN rooms ON messages.room_id = rooms.id
                WHERE rooms.name = ?
                ORDER BY messages.sent_at ASC 
                LIMIT 50;
            """, (room_name,))
            history_payload = []
            for row in history_rows:
                history_payload.append({
                    "username": row["username"],
                    "text": row["content"],
                    "sent_at": row["sent_at"]
                })
            history_packet = Packet(
                message_type="HISTORY",
                sender="SERVER",
                receiver=None,
                room=room_name,
                payload={"history": history_payload}
            )
            send_framed_packet(client_socket, history_packet)
        except DatabaseError as e:
            logger.error(f"Error fetching room history: {e}")

    def _broadcast_to_room(self, room_name, packet):
        with self.lock:
            active_sessions = list(self.sessions.keys())
        for addr in active_sessions:
            with self.lock:
                joined_rooms = self.client_rooms.get(addr, set())
                client_socket = self.clients.get(addr)
            if room_name in joined_rooms and client_socket:
                try:
                    send_framed_packet(client_socket, packet)
                except Exception as e:
                    logger.error(f"Failed to send room message to {addr}: {e}")

    def _send_error(self, client_socket, error_message):
        resp = Packet(
            message_type="ERROR",
            sender="SERVER",
            receiver=None,
            room=None,
            payload={"message": error_message}
        )
        try:
            send_framed_packet(client_socket, resp)
        except Exception:
            pass

    def _broadcast_to_authenticated(self, packet):
        with self.lock:
            active_sessions = list(self.sessions.keys())
        for addr in active_sessions:
            with self.lock:
                client_socket = self.clients.get(addr)
            if client_socket:
                try:
                    send_framed_packet(client_socket, packet)
                except Exception as e:
                    logger.error(f"Failed to broadcast to {addr}: {e}")

    def _disconnect_client(self, client_address):
        username = None
        user_id = None
        with self.lock:
            client_socket = self.clients.pop(client_address, None)
            session = self.sessions.pop(client_address, None)
            self.client_rooms.pop(client_address, None)
            if session:
                username = session["username"]
                user_id = session["id"]
        if user_id:
            self._update_db_presence(user_id, "Offline")
            self._broadcast_presence_change(username, "Offline")
        if client_socket:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client_socket.close()
            except Exception:
                pass
            logger.info(f"Socket connection closed and cleaned up for {client_address}")

    def stop(self):
        logger.info("Stopping TCP Socket Server...")
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception as e:
                logger.error(f"Error closing server listening socket: {e}")
        active_addresses = list(self.clients.keys())
        for address in active_addresses:
            self._disconnect_client(address)
        logger.info("TCP Socket Server stopped successfully.")
