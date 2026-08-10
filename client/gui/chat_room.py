import os
import queue
import time
import hashlib
import base64
import threading
import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QTextBrowser, QLineEdit,
    QPushButton, QLabel, QFileDialog, QProgressBar, QInputDialog, QMessageBox, QMenu, QFrame
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor
from common.protocol import Packet

logger = logging.getLogger("client")

class ChatRoomWidget(QWidget):
    def __init__(self, client, username, main_window):
        super().__init__()
        self.client = client
        self.username = username
        self.main_window = main_window
        self.current_room = "General"
        self.joined_rooms = set(["General"])
        self.role = "User"
        self._pending_add_to_room_target = None
        self.room_chat_histories = {}
        
        # Admin Dialog reference
        self.admin_dialog = None
        
        self._init_ui()
        
        # Start queue reader timer (100ms)
        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self._check_network_queue)
        self.queue_timer.start(100)
        
        # Request online user list immediately
        self._request_online_list()
        self.online_timer = QTimer(self)
        self.online_timer.timeout.connect(self._request_online_list)
        self.online_timer.start(5000)

    def _init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #1e222b;
                color: #abb2bf;
                font-family: 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
            }
            QLabel {
                font-weight: bold;
                color: #ffffff;
            }
            QListWidget {
                background-color: #21252b;
                border: 1px solid #2b313c;
                border-radius: 6px;
                color: #abb2bf;
                padding: 5px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #2c313c;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #3e4451;
                color: #ffffff;
            }
            QTextBrowser {
                background-color: #282c34;
                border: 1px solid #1e222b;
                border-radius: 6px;
                color: #abb2bf;
                padding: 10px;
            }
            QLineEdit {
                background-color: #282c34;
                border: 1px solid #3e4451;
                border-radius: 6px;
                padding: 10px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #528bff;
            }
            QPushButton {
                background-color: #3e4451;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4c5364;
            }
            QPushButton#sendButton {
                background-color: #528bff;
            }
            QPushButton#sendButton:hover {
                background-color: #4376db;
            }
            QPushButton#createRoomButton {
                background-color: #98c379;
                color: #1e222b;
            }
            QPushButton#createRoomButton:hover {
                background-color: #a3d18a;
            }
            QPushButton#joinRoomButton {
                background-color: #61afef;
                color: #1e222b;
            }
            QPushButton#joinRoomButton:hover {
                background-color: #7ec2f3;
            }
            QPushButton#logoutButton {
                background-color: #e06c75;
                color: #1e222b;
            }
            QPushButton#logoutButton:hover {
                background-color: #e57c83;
            }
            QPushButton#cancelTransferBtn {
                background-color: #e06c75;
                color: #1e222b;
            }
            QPushButton#cancelTransferBtn:hover {
                background-color: #e57c83;
            }
            QPushButton#retryTransferBtn {
                background-color: #61afef;
                color: #1e222b;
            }
            QPushButton#retryTransferBtn:hover {
                background-color: #7ec2f3;
            }
            QPushButton#adminDbBtn {
                background-color: #d19a66;
                color: #1e222b;
            }
            QPushButton#adminDbBtn:hover {
                background-color: #e5b182;
            }
            QProgressBar {
                border: 1px solid #3e4451;
                border-radius: 4px;
                text-align: center;
                background-color: #282c34;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #98c379;
            }
            QFrame#transferFrame {
                background-color: #21252b;
                border: 1px solid #2b313c;
                border-radius: 6px;
                padding: 10px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Columns Layout
        workspace_layout = QHBoxLayout()
        workspace_layout.setSpacing(10)

        # LEFT COLUMN: Rooms & Transfer History
        left_layout = QVBoxLayout()
        left_layout.setSpacing(8)
        
        left_layout.addWidget(QLabel("Rooms", self))
        
        self.room_list_widget = QListWidget(self)
        self.room_list_widget.addItem("General")
        self.room_list_widget.setCurrentRow(0)
        self.room_list_widget.itemClicked.connect(self._handle_room_selection)
        left_layout.addWidget(self.room_list_widget)
        
        self.create_room_btn = QPushButton("+ Create Room", self)
        self.create_room_btn.setObjectName("createRoomButton")
        self.create_room_btn.setVisible(False)
        self.create_room_btn.clicked.connect(self._handle_create_room)
        left_layout.addWidget(self.create_room_btn)

        self.join_room_btn = QPushButton("Join Room", self)
        self.join_room_btn.setObjectName("joinRoomButton")
        self.join_room_btn.clicked.connect(self._handle_join_room)
        left_layout.addWidget(self.join_room_btn)

        self.leave_room_btn = QPushButton("Leave Room", self)
        self.leave_room_btn.clicked.connect(self._handle_leave_room)
        left_layout.addWidget(self.leave_room_btn)
        


        # Admin Dashboard Button (Only visible for Admins)
        self.admin_db_btn = QPushButton("Admin Dashboard", self)
        self.admin_db_btn.setObjectName("adminDbBtn")
        self.admin_db_btn.setVisible(False)
        self.admin_db_btn.clicked.connect(self._handle_admin_dashboard)
        left_layout.addWidget(self.admin_db_btn)

        self.logout_btn = QPushButton("Log Out", self)
        self.logout_btn.setObjectName("logoutButton")
        self.logout_btn.clicked.connect(self._handle_logout)
        left_layout.addWidget(self.logout_btn)
        
        left_container = QWidget()
        left_container.setLayout(left_layout)
        left_container.setFixedWidth(180)
        workspace_layout.addWidget(left_container)

        # CENTER COLUMN: Chat view & input panels
        center_layout = QVBoxLayout()
        center_layout.setSpacing(8)
        
        self.room_header_label = QLabel(f"Room: #{self.current_room}", self)
        self.room_header_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        center_layout.addWidget(self.room_header_label)

        self.chat_display = QTextBrowser(self)
        self.chat_display.setOpenExternalLinks(True)
        center_layout.addWidget(self.chat_display)

        # Message inputs row
        input_control_layout = QHBoxLayout()
        input_control_layout.setSpacing(8)

        self.emoji_btn = QPushButton("😊 Emoji", self)
        self.emoji_btn.clicked.connect(self._handle_emoji_popup)
        input_control_layout.addWidget(self.emoji_btn)

        self.msg_input = QLineEdit(self)
        self.msg_input.setPlaceholderText("Type a message to send...")
        self.msg_input.returnPressed.connect(self._handle_send_msg)
        input_control_layout.addWidget(self.msg_input)

        self.send_btn = QPushButton("Send", self)
        self.send_btn.setObjectName("sendButton")
        self.send_btn.clicked.connect(self._handle_send_msg)
        input_control_layout.addWidget(self.send_btn)

        center_layout.addLayout(input_control_layout)

        center_container = QWidget()
        center_container.setLayout(center_layout)
        workspace_layout.addWidget(center_container)

        # RIGHT COLUMN: Active Presence Panel
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        
        right_layout.addWidget(QLabel("Online Users", self))
        
        self.user_list_widget = QListWidget(self)
        self.user_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.user_list_widget.customContextMenuRequested.connect(self._show_admin_menu)
        right_layout.addWidget(self.user_list_widget)
        
        right_container = QWidget()
        right_container.setLayout(right_layout)
        right_container.setFixedWidth(160)
        workspace_layout.addWidget(right_container)

        main_layout.addLayout(workspace_layout)

        # Footer Status bar
        footer_layout = QHBoxLayout()
        self.status_lbl = QLabel(f"Logged in as: {self.username} (Role: User) | TLS Secured", self)
        self.status_lbl.setStyleSheet("font-size: 11px; font-weight: normal; color: #abb2bf;")
        footer_layout.addWidget(self.status_lbl)
        main_layout.addLayout(footer_layout)

    # ================= EVENT HANDLERS & ROUTINGS =================

    def update_role_label(self, role):
        self.role = role
        self.status_lbl.setText(f"Logged in as: {self.username} (Role: {role}) | TLS Secured")
        
        # Toggle Admin Dashboard and Create Room buttons visibility based on role permissions
        if role in ["Admin", "Moderator"]:
            self.admin_db_btn.setVisible(True)
            self.create_room_btn.setVisible(True)
        else:
            self.admin_db_btn.setVisible(False)
            self.create_room_btn.setVisible(False)

    def _handle_room_selection(self, item):
        if not item:
            return
        room_name = item.text()
        if room_name == self.current_room:
            return
        self.current_room = room_name
        self.room_header_label.setText(f"Room: #{self.current_room}")
        self._refresh_chat_display()
        self.chat_display.append(f"<font color='#528bff'><b>[SYSTEM] Chat context switched to #{self.current_room}</b></font>")

    def _handle_create_room(self):
        room_name, ok = QInputDialog.getText(self, "Create Room", "Enter new room name:")
        if ok and room_name.strip():
            packet = Packet(
                message_type="CREATE_ROOM",
                payload={"room": room_name.strip()}
            )
            self.client.send_packet(packet)

    def _handle_join_room(self):
        self._pending_add_to_room_target = None
        packet = Packet(message_type="GET_ROOMS_LIST")
        self.client.send_packet(packet)

    def _handle_admin_add_to_room(self, target_username):
        self._pending_add_to_room_target = target_username
        packet = Packet(message_type="GET_ROOMS_LIST")
        self.client.send_packet(packet)

    def _handle_leave_room(self):
        if self.current_room == "General":
            QMessageBox.warning(self, "Warning", "You cannot leave the default General room.")
            return
        reply = QMessageBox.question(
            self, "Leave Room", f"Are you sure you want to leave #{self.current_room}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            packet = Packet(
                message_type="LEAVE_ROOM",
                payload={"room": self.current_room}
            )
            self.client.send_packet(packet)

    def _handle_logout(self):
        reply = QMessageBox.question(
            self, "Log Out", "Are you sure you want to log out of your session?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            packet = Packet(
                message_type="LOGOUT",
                payload={}
            )
            self.client.send_packet(packet)

    def _handle_admin_dashboard(self):
        """Spawns the modal administrative control dashboard."""
        from client.gui.admin_dashboard import AdminDashboardDialog
        self.admin_dialog = AdminDashboardDialog(self.client, self)
        self.admin_dialog.exec()

    def _handle_send_msg(self):
        text = self.msg_input.text().strip()
        if not text:
            return
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower()
            if cmd == "/msg":
                if len(parts) < 3:
                    self.chat_display.append("<font color='#e06c75'>Usage: /msg &lt;username&gt; &lt;message&gt;</font>")
                    return
                recipient = parts[1]
                msg_body = " ".join(parts[2:])
                packet = Packet(
                    message_type="PM",
                    receiver=recipient,
                    payload={"text": msg_body}
                )
                self.client.send_packet(packet)
                self.chat_display.append(f"<font color='#d19a66'>[PM to {recipient}] Me: {msg_body}</font>")
            else:
                self._send_raw_cmd_packet(cmd, parts)
        else:
            packet = Packet(
                message_type="MSG",
                room=self.current_room,
                payload={"text": text}
            )
            self.client.send_packet(packet)
        self.msg_input.clear()

    def _send_raw_cmd_packet(self, cmd, parts):
        try:
            if cmd == "/kick" and len(parts) >= 3:
                packet = Packet("KICK_USER", payload={"target": parts[1], "room": parts[2]})
                self.client.send_packet(packet)
            elif cmd == "/ban" and len(parts) >= 2:
                packet = Packet("BAN_USER", payload={"target": parts[1]})
                self.client.send_packet(packet)
            elif cmd == "/mute" and len(parts) >= 2:
                packet = Packet("MUTE_USER", payload={"target": parts[1]})
                self.client.send_packet(packet)
            elif cmd == "/unmute" and len(parts) >= 2:
                packet = Packet("UNMUTE_USER", payload={"target": parts[1]})
                self.client.send_packet(packet)
            elif cmd == "/promote" and len(parts) >= 3:
                packet = Packet("PROMOTE_USER", payload={"target": parts[1], "role": parts[2]})
                self.client.send_packet(packet)
            elif cmd == "/demote" and len(parts) >= 2:
                packet = Packet("PROMOTE_USER", payload={"target": parts[1], "role": "User"})
                self.client.send_packet(packet)
            else:
                self.chat_display.append("<font color='#e06c75'>Unknown command or missing parameters.</font>")
        except Exception as e:
            self.chat_display.append(f"<font color='#e06c75'>Command error: {e}</font>")

    def _handle_emoji_popup(self):
        menu = QMenu(self)
        emojis = ["😊", "😂", "👍", "🎉", "🔥", "❤️", "🤔", "👀"]
        for e in emojis:
            action = menu.addAction(e)
            action.triggered.connect(lambda checked=False, val=e: self.msg_input.insert(val))
        menu.exec(QCursor.pos())

    # ================= ADMIN MODERATION EVENTS =================

    def _show_admin_menu(self, position):
        item = self.user_list_widget.itemAt(position)
        if not item:
            return
        target_text = item.text()
        target_username = target_text.split()[0]
        if target_username == self.username:
            return

        menu = QMenu(self)
        if self.role in ["Admin", "Moderator"]:
            action_mute = menu.addAction(f"Mute {target_username}")
            action_mute.triggered.connect(lambda: self._trigger_admin_action("MUTE_USER", target_username))
            
            action_unmute = menu.addAction(f"Unmute {target_username}")
            action_unmute.triggered.connect(lambda: self._trigger_admin_action("UNMUTE_USER", target_username))
            
            action_kick = menu.addAction(f"Kick from {self.current_room}")
            action_kick.triggered.connect(lambda: self._trigger_admin_action("KICK_USER", target_username, self.current_room))
            
            action_add_room = menu.addAction(f"Add {target_username} to Room...")
            action_add_room.triggered.connect(lambda target=target_username: self._handle_admin_add_to_room(target))

        if self.role == "Admin":
            menu.addSeparator()
            action_ban = menu.addAction(f"Ban {target_username}")
            action_ban.triggered.connect(lambda: self._trigger_admin_action("BAN_USER", target_username))
            
            menu.addSeparator()
            action_promote_mod = menu.addAction(f"Promote to Moderator")
            action_promote_mod.triggered.connect(lambda: self._trigger_admin_action("PROMOTE_USER", target_username, "Moderator"))
            
            action_promote_admin = menu.addAction(f"Promote to Admin")
            action_promote_admin.triggered.connect(lambda: self._trigger_admin_action("PROMOTE_USER", target_username, "Admin"))
            
            action_demote = menu.addAction(f"Demote to User")
            action_demote.triggered.connect(lambda: self._trigger_admin_action("PROMOTE_USER", target_username, "User"))

        if not menu.isEmpty():
            menu.exec(self.user_list_widget.viewport().mapToGlobal(position))

    def _trigger_admin_action(self, mtype, target, param=None):
        payload = {"target": target}
        if mtype == "KICK_USER":
            payload["room"] = param
        elif mtype == "PROMOTE_USER":
            payload["role"] = param
        packet = Packet(message_type=mtype, payload=payload)
        self.client.send_packet(packet)

    # ================= NETWORK PRESENCE & ROUTINGS =================

    def _request_online_list(self):
        if self.client.connected:
            packet = Packet(message_type="GET_ONLINE_LIST", payload={})
            self.client.send_packet(packet)

    def _check_network_queue(self):
        while not self.client.receive_queue.empty():
            try:
                packet = self.client.receive_queue.get_nowait()
                mtype = packet.message_type
                payload = packet.payload or {}
                


                # Route admin dashboard query responses directly to the dialog window
                if mtype in ["ADMIN_STATS_RESP", "BAN_LIST_RESP", "SYSTEM_LOGS_RESP", "ALL_USERS_RESP", "ADMIN_ROOMS_RESP"]:
                    if self.admin_dialog and self.admin_dialog.isVisible():
                        self.admin_dialog.process_admin_packet(packet)
                    self.client.receive_queue.task_done()
                    continue

                if mtype == "ROOMS_LIST_RESP":
                    if self.admin_dialog and self.admin_dialog.isVisible() and getattr(self.admin_dialog, "pending_add_username", None):
                        self.admin_dialog.process_admin_packet(packet)
                    else:
                        rooms = payload.get("rooms", [])
                        if self._pending_add_to_room_target:
                            target = self._pending_add_to_room_target
                            self._pending_add_to_room_target = None
                            if not rooms:
                                QMessageBox.information(self, "No Rooms", "No rooms exist on the server.")
                            else:
                                room_name, ok = QInputDialog.getItem(
                                    self, "Add User to Room", f"Select room to add {target} to:", rooms, 0, False
                                )
                                if ok and room_name:
                                    packet = Packet(
                                        message_type="ADD_USER_TO_ROOM",
                                        payload={"target": target, "room": room_name}
                                    )
                                    self.client.send_packet(packet)
                        else:
                            available_rooms = [r for r in rooms if r not in self.joined_rooms]
                            if not available_rooms:
                                QMessageBox.information(self, "Join Room", "You are already a member of all existing rooms.")
                            else:
                                room_name, ok = QInputDialog.getItem(
                                    self, "Join Room", "Select a room to join:", available_rooms, 0, False
                                )
                                if ok and room_name:
                                    packet = Packet(
                                        message_type="JOIN_ROOM",
                                        payload={"room": room_name}
                                    )
                                    self.client.send_packet(packet)
                    self.client.receive_queue.task_done()
                    continue

                if mtype == "PRESENCE":
                    user = payload.get("username")
                    status = payload.get("status")
                    self.chat_display.append(f"<font color='#98c379'><i>* {user} is now {status}</i></font>")
                    self._request_online_list()
                    
                    # Native Presence Update Notification (Requirement)
                    if user != self.username:
                        self.main_window.show_notification(
                            "User Status Change",
                            f"User '{user}' is now {status}."
                        )

                elif mtype == "ONLINE_LIST_RESP":
                    users = payload.get("online_users", [])
                    self.user_list_widget.clear()
                    for u in users:
                        self.user_list_widget.addItem(f"{u['username']} ({u['status']})")

                elif mtype == "ROLE_UPDATE":
                    new_role = payload.get("role")
                    msg = payload.get("message")
                    self.update_role_label(new_role)
                    self.chat_display.append(f"<font color='#e5c07b'><b>[SYSTEM] {msg}</b></font>")

                elif mtype == "KICKED":
                    room = packet.room
                    msg = payload.get("message")
                    self.chat_display.append(f"<font color='#e06c75'><b>[SYSTEM] {msg}</b></font>")
                    
                    self.joined_rooms.discard(room)
                    self._refresh_rooms_list()
                    if self.current_room == room:
                        self._handle_room_selection(self.room_list_widget.item(0))

                elif mtype == "CREATE_ROOM_RESP":
                    success = payload.get("success")
                    room = payload.get("room")
                    if success:
                        self.joined_rooms.add(room)
                        self._refresh_rooms_list()
                        self.chat_display.append(f"<font color='#98c379'><b>[SYSTEM] Room #{room} created.</b></font>")
                    else:
                        QMessageBox.warning(self, "Room Error", payload.get("message", "Failed to create room."))

                elif mtype == "DELETE_ROOM_RESP":
                    success = payload.get("success")
                    room = payload.get("room")
                    if success:
                        self.joined_rooms.discard(room)
                        self._refresh_rooms_list()
                        self.chat_display.append(f"<font color='#e06c75'><b>[SYSTEM] Room #{room} has been deleted.</b></font>")
                        if self.current_room == room:
                            self._handle_room_selection(self.room_list_widget.item(0))

                elif mtype == "JOIN_ROOM_RESP":
                    success = payload.get("success")
                    room = packet.room
                    msg = payload.get("message", f"Joined #{room}")
                    if success:
                        self.joined_rooms.add(room)
                        self._refresh_rooms_list()
                        self.chat_display.append(f"<font color='#98c379'><b>[SYSTEM] {msg}</b></font>")

                elif mtype == "LEAVE_ROOM_RESP":
                    success = payload.get("success")
                    room = packet.room
                    if success:
                        self.joined_rooms.discard(room)
                        self._refresh_rooms_list()
                        self.chat_display.append(f"<font color='#e06c75'><b>[SYSTEM] Left #{room}.</b></font>")
                        if self.current_room == room:
                            self._handle_room_selection(self.room_list_widget.item(0))

                elif mtype == "ROOMS_STATUS":
                    joined = payload.get("joined_rooms", [])
                    if joined:
                        self.joined_rooms = set(joined)
                        self._refresh_rooms_list()

                elif mtype == "MSG":
                    sender = packet.sender or "Server"
                    text = payload.get("text", "")
                    room = packet.room or "General"
                    
                    if room not in self.room_chat_histories:
                        self.room_chat_histories[room] = []
                    formatted_msg = f"<b>{sender}</b>: {text}"
                    self.room_chat_histories[room].append(formatted_msg)
                    
                    if room == self.current_room:
                        self.chat_display.append(formatted_msg)
                    
                    # Native Desktop Notification for incoming messages
                    if sender != self.username:
                        if f"@{self.username}" in text:
                            # Mention Notification (Requirement)
                            self.main_window.show_notification(
                                f"Mentioned in #{room}",
                                f"{sender}: {text}"
                            )
                        else:
                            # Standard Message Notification (Requirement)
                            self.main_window.show_notification(
                                f"New message in #{room}",
                                f"{sender}: {text}"
                            )

                elif mtype == "PM":
                    sender = packet.sender
                    text = payload.get("text", "")
                    formatted_msg = f"<font color='#d19a66'><b>[PM from {sender}]</b>: {text}</font>"
                    if self.current_room not in self.room_chat_histories:
                        self.room_chat_histories[self.current_room] = []
                    self.room_chat_histories[self.current_room].append(formatted_msg)
                    self.chat_display.append(formatted_msg)
                    
                    # Private Message Notification (Requirement)
                    if sender != self.username:
                        self.main_window.show_notification(
                            f"Private Message from {sender}",
                            text
                        )

                elif mtype == "SYSTEM":
                    msg = payload.get("message", "")
                    formatted_msg = f"<font color='#e5c07b'><b>[SYSTEM] {msg}</b></font>"
                    if self.current_room not in self.room_chat_histories:
                        self.room_chat_histories[self.current_room] = []
                    self.room_chat_histories[self.current_room].append(formatted_msg)
                    self.chat_display.append(formatted_msg)

                elif mtype == "HISTORY":
                    room = packet.room
                    history = payload.get("history", [])
                    self.room_chat_histories[room] = []
                    self.room_chat_histories[room].append(f"<font color='#5c6370'>--- History for #{room} ---</font>")
                    for h in history:
                        self.room_chat_histories[room].append(f"<b>{h['username']}</b>: {h['text']}")
                    self.room_chat_histories[room].append("<font color='#5c6370'>-------------------------</font>")
                    
                    if room == self.current_room:
                        self._refresh_chat_display()

                elif mtype == "PM_HISTORY":
                    history = payload.get("history", [])
                    if history:
                        if self.current_room not in self.room_chat_histories:
                            self.room_chat_histories[self.current_room] = []
                        
                        self.room_chat_histories[self.current_room].append("<font color='#d19a66'>--- PM History ---</font>")
                        for h in history:
                            formatted = f"<i>{h['sender']} -> {h['receiver']}</i>: {h['text']}"
                            self.room_chat_histories[self.current_room].append(formatted)
                        self.room_chat_histories[self.current_room].append("<font color='#d19a66'>-----------------</font>")
                        
                        self._refresh_chat_display()

                elif mtype == "ERROR":
                    QMessageBox.critical(self, "Server Error", payload.get("message", "An unexpected error occurred."))

                elif mtype == "LOGOUT_RESP":
                    self.queue_timer.stop()
                    self.online_timer.stop()
                    self.main_window.switch_to_login()

                self.client.receive_queue.task_done()
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error parsing GUI packet queue: {e}")
                break

    def _refresh_chat_display(self):
        self.chat_display.clear()
        hist = self.room_chat_histories.get(self.current_room, [])
        for msg_html in hist:
            self.chat_display.append(msg_html)

    def _refresh_rooms_list(self):
        self.room_list_widget.clear()
        rooms = sorted(list(self.joined_rooms))
        for r in rooms:
            self.room_list_widget.addItem(r)
            if r == self.current_room:
                row_idx = self.room_list_widget.count() - 1
                self.room_list_widget.setCurrentRow(row_idx)
