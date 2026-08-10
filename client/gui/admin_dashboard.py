from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QListWidget, QPushButton, QLabel, QTextBrowser, QWidget, QFrame,
    QInputDialog, QMessageBox, QLineEdit
)
from PySide6.QtCore import Qt
from common.protocol import Packet

class AdminDashboardDialog(QDialog):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.pending_add_username = None
        
        self.setWindowTitle("Server Admin Control Portal")
        self.resize(700, 500)
        self.setMinimumSize(600, 400)
        
        self._init_ui()
        self.refresh_all_data()

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1e222b;
                color: #abb2bf;
                font-family: 'Segoe UI', Roboto, sans-serif;
                font-size: 13px;
            }
            QTabWidget::panel {
                border: 1px solid #2b313c;
                background-color: #21252b;
                border-radius: 6px;
            }
            QTabBar::tab {
                background-color: #1e222b;
                color: #abb2bf;
                padding: 10px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:hover {
                background-color: #2c313c;
            }
            QTabBar::tab:selected {
                background-color: #21252b;
                color: #ffffff;
                border-bottom: 2px solid #528bff;
            }
            QLabel {
                color: #abb2bf;
            }
            QLabel#statsTitle {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
            }
            QLabel#statsVal {
                color: #98c379;
                font-size: 28px;
                font-weight: bold;
            }
            QListWidget {
                background-color: #282c34;
                border: 1px solid #3e4451;
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
            QTextBrowser {
                background-color: #282c34;
                border: 1px solid #3e4451;
                border-radius: 6px;
                color: #abb2bf;
                padding: 10px;
            }
            QPushButton {
                background-color: #3e4451;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4c5364;
            }
            QPushButton#actionBtn {
                background-color: #61afef;
                color: #1e222b;
            }
            QPushButton#actionBtn:hover {
                background-color: #7ec2f3;
            }
            QPushButton#dangerBtn {
                background-color: #e06c75;
                color: #1e222b;
            }
            QPushButton#dangerBtn:hover {
                background-color: #e57c83;
            }
            QFrame#statsCard {
                background-color: #282c34;
                border: 1px solid #3e4451;
                border-radius: 6px;
                padding: 15px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        header = QLabel("System Administration Workspace", self)
        header.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)

        # Tab Widget Control
        self.tabs = QTabWidget(self)
        
        # 1. Statistics Tab
        self.stats_tab = QWidget()
        self._setup_stats_tab()
        self.tabs.addTab(self.stats_tab, "Statistics")

        # 2. User Directory Tab
        self.users_tab = QWidget()
        self._setup_users_tab()
        self.tabs.addTab(self.users_tab, "User Management")

        # 3. Ban List Tab
        self.bans_tab = QWidget()
        self._setup_bans_tab()
        self.tabs.addTab(self.bans_tab, "Ban List")

        # 4. Audit Logs Tab
        self.logs_tab = QWidget()
        self._setup_logs_tab()
        self.tabs.addTab(self.logs_tab, "Audit Logs")

        # 5. Room Management Tab
        self.rooms_tab = QWidget()
        self._setup_rooms_tab()
        self.tabs.addTab(self.rooms_tab, "Room Management")

        layout.addWidget(self.tabs)

        # Footer Actions
        footer = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Data", self)
        self.refresh_btn.clicked.connect(self.refresh_all_data)
        footer.addWidget(self.refresh_btn)
        
        footer.addStretch()
        
        self.close_btn = QPushButton("Close", self)
        self.close_btn.clicked.connect(self.accept)
        footer.addWidget(self.close_btn)
        
        layout.addLayout(footer)

    def refresh_all_data(self):
        """Sends data query packets to server."""
        self.client.send_packet(Packet("GET_ADMIN_STATS"))
        self.client.send_packet(Packet("GET_ALL_USERS"))
        self.client.send_packet(Packet("GET_BAN_LIST"))
        self.client.send_packet(Packet("GET_SYSTEM_LOGS"))
        self.client.send_packet(Packet("GET_ADMIN_ROOMS"))

    # ================= TAB WIDGETS DECLARATIONS =================

    def _setup_stats_tab(self):
        layout = QVBoxLayout(self.stats_tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        grid = QHBoxLayout()
        grid.setSpacing(15)
        
        # Cards
        self.users_card = self._create_stats_card("Registered Users", "0")
        self.rooms_card = self._create_stats_card("Chat Rooms", "0")
        self.online_card = self._create_stats_card("Online Sessions", "0")
        self.msg_card = self._create_stats_card("Total Messages", "0")
        
        grid.addWidget(self.users_card)
        grid.addWidget(self.rooms_card)
        grid.addWidget(self.online_card)
        grid.addWidget(self.msg_card)
        layout.addLayout(grid)
        layout.addStretch()

    def _create_stats_card(self, title, val):
        card = QFrame(self)
        card.setObjectName("statsCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(10)
        
        lbl = QLabel(title, card)
        lbl.setStyleSheet("font-size: 12px; color: #abb2bf;")
        lay.addWidget(lbl)
        
        val_lbl = QLabel(val, card)
        val_lbl.setObjectName("statsVal")
        lay.addWidget(val_lbl)
        
        # Keep references to value labels
        if not hasattr(self, "stats_labels"):
            self.stats_labels = {}
        self.stats_labels[title] = val_lbl
        
        return card

    def _setup_users_tab(self):
        layout = QHBoxLayout(self.users_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        self.users_list = QListWidget(self)
        layout.addWidget(self.users_list, 2)

        # Action Buttons panel
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)
        
        btn_layout.addWidget(QLabel("Role Operations", self))
        
        self.promote_mod_btn = QPushButton("Make Moderator", self)
        self.promote_mod_btn.setObjectName("actionBtn")
        self.promote_mod_btn.clicked.connect(lambda: self._trigger_user_promote("Moderator"))
        btn_layout.addWidget(self.promote_mod_btn)

        self.promote_admin_btn = QPushButton("Make Admin", self)
        self.promote_admin_btn.setObjectName("actionBtn")
        self.promote_admin_btn.clicked.connect(lambda: self._trigger_user_promote("Admin"))
        btn_layout.addWidget(self.promote_admin_btn)

        self.demote_user_btn = QPushButton("Demote to User", self)
        self.demote_user_btn.clicked.connect(lambda: self._trigger_user_promote("User"))
        btn_layout.addWidget(self.demote_user_btn)

        btn_layout.addWidget(QLabel("Moderation", self))
        
        self.add_to_room_btn = QPushButton("Add to Room", self)
        self.add_to_room_btn.setObjectName("actionBtn")
        self.add_to_room_btn.clicked.connect(self._trigger_user_add_to_room)
        btn_layout.addWidget(self.add_to_room_btn)

        self.mute_user_btn = QPushButton("Mute", self)
        self.mute_user_btn.clicked.connect(self._trigger_user_mute)
        btn_layout.addWidget(self.mute_user_btn)

        self.unmute_user_btn = QPushButton("Unmute", self)
        self.unmute_user_btn.clicked.connect(self._trigger_user_unmute)
        btn_layout.addWidget(self.unmute_user_btn)

        self.ban_user_btn = QPushButton("Ban Account", self)
        self.ban_user_btn.setObjectName("dangerBtn")
        self.ban_user_btn.clicked.connect(self._trigger_user_ban)
        btn_layout.addWidget(self.ban_user_btn)

        btn_layout.addStretch()
        
        btn_container = QWidget()
        btn_container.setLayout(btn_layout)
        btn_container.setFixedWidth(160)
        layout.addWidget(btn_container, 1)

    def _setup_bans_tab(self):
        layout = QHBoxLayout(self.bans_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        self.bans_list = QListWidget(self)
        layout.addWidget(self.bans_list, 2)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)
        
        self.revoke_ban_btn = QPushButton("Revoke Ban", self)
        self.revoke_ban_btn.setObjectName("actionBtn")
        self.revoke_ban_btn.clicked.connect(self._trigger_revoke_ban)
        btn_layout.addWidget(self.revoke_ban_btn)
        
        btn_layout.addStretch()
        
        btn_container = QWidget()
        btn_container.setLayout(btn_layout)
        btn_container.setFixedWidth(160)
        layout.addWidget(btn_container, 1)

    def _setup_logs_tab(self):
        layout = QVBoxLayout(self.logs_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(8)
        
        self.logs_display = QTextBrowser(self)
        layout.addWidget(self.logs_display)

    # ================= RESPONSE PROCESSING (Thread-Safe routing from parent) =================

    def process_admin_packet(self, packet):
        """Processes responses received from server."""
        mtype = packet.message_type
        payload = packet.payload or {}

        if mtype == "ADMIN_STATS_RESP":
            self.stats_labels["Registered Users"].setText(str(payload.get("total_users", 0)))
            self.stats_labels["Chat Rooms"].setText(str(payload.get("total_rooms", 0)))
            self.stats_labels["Online Sessions"].setText(str(payload.get("online_users", 0)))
            self.stats_labels["Total Messages"].setText(str(payload.get("total_messages", 0)))

        elif mtype == "ALL_USERS_RESP":
            self.users_list.clear()
            users = payload.get("users", [])
            for u in users:
                self.users_list.addItem(f"{u['username']} (Role: {u['role']}, Status: {u['status']})")

        elif mtype == "ROOMS_LIST_RESP":
            if getattr(self, "pending_add_username", None):
                rooms = payload.get("rooms", [])
                target = self.pending_add_username
                self.pending_add_username = None
                if not rooms:
                    QMessageBox.information(self, "No Rooms", "No rooms exist on the server.")
                else:
                    room_name, ok = QInputDialog.getItem(
                        self, "Add User to Room", f"Select room to add {target} to:", rooms, 0, False
                    )
                    if ok and room_name:
                        packet = Packet("ADD_USER_TO_ROOM", payload={"target": target, "room": room_name})
                        self.client.send_packet(packet)

        elif mtype == "BAN_LIST_RESP":
            self.bans_list.clear()
            banned = payload.get("banned_users", [])
            for b in banned:
                self.bans_list.addItem(b)

        elif mtype == "SYSTEM_LOGS_RESP":
            self.logs_display.clear()
            logs = payload.get("logs", [])
            for l in logs:
                level_color = "#e06c75" if l["level"] == "WARNING" else "#abb2bf"
                self.logs_display.append(
                    f"<font color='#5c6370'>[{l['timestamp']}]</font> "
                    f"<font color='{level_color}'><b>[{l['level']}]</b></font> "
                    f"{l['message']}"
                )

        elif mtype == "ADMIN_ROOMS_RESP":
            self.rooms_list.clear()
            rooms = payload.get("rooms", [])
            for r in rooms:
                creator = r["creator"] or "System"
                created_at = r["created_at"] or "N/A"
                self.rooms_list.addItem(f"#{r['name']} (Creator: {creator}, Created: {created_at})")

    # ================= PRIVATE EVENT ACTIONS TRIGGER ROUTINES =================

    def _get_selected_username(self):
        item = self.users_list.currentItem()
        if not item:
            return None
        # Parse username (first word)
        return item.text().split()[0]

    def _trigger_user_promote(self, role):
        username = self._get_selected_username()
        if username:
            packet = Packet("PROMOTE_USER", payload={"target": username, "role": role})
            self.client.send_packet(packet)
            self.refresh_all_data()

    def _trigger_user_mute(self):
        username = self._get_selected_username()
        if username:
            packet = Packet("MUTE_USER", payload={"target": username})
            self.client.send_packet(packet)
            self.refresh_all_data()

    def _trigger_user_unmute(self):
        username = self._get_selected_username()
        if username:
            packet = Packet("UNMUTE_USER", payload={"target": username})
            self.client.send_packet(packet)
            self.refresh_all_data()

    def _trigger_user_ban(self):
        username = self._get_selected_username()
        if username:
            packet = Packet("BAN_USER", payload={"target": username})
            self.client.send_packet(packet)
            self.refresh_all_data()

    def _trigger_revoke_ban(self):
        item = self.bans_list.currentItem()
        if item:
            username = item.text()
            packet = Packet("REVOKE_BAN", payload={"target": username})
            self.client.send_packet(packet)
            self.refresh_all_data()

    def _trigger_user_add_to_room(self):
        username = self._get_selected_username()
        if username:
            self.pending_add_username = username
            self.client.send_packet(Packet("GET_ROOMS_LIST"))

    def _setup_rooms_tab(self):
        layout = QHBoxLayout(self.rooms_tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        self.rooms_list = QListWidget(self)
        layout.addWidget(self.rooms_list, 2)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)
        
        btn_layout.addWidget(QLabel("Room Control", self))
        
        self.delete_room_btn = QPushButton("Delete Room", self)
        self.delete_room_btn.setObjectName("dangerBtn")
        self.delete_room_btn.clicked.connect(self._trigger_admin_delete_room)
        btn_layout.addWidget(self.delete_room_btn)

        btn_layout.addSpacing(15)
        btn_layout.addWidget(QLabel("Create New Room", self))
        
        self.room_name_input = QLineEdit(self)
        self.room_name_input.setPlaceholderText("New room name...")
        btn_layout.addWidget(self.room_name_input)

        self.create_room_btn = QPushButton("Create Room", self)
        self.create_room_btn.setObjectName("actionBtn")
        self.create_room_btn.clicked.connect(self._trigger_admin_create_room)
        btn_layout.addWidget(self.create_room_btn)

        btn_layout.addStretch()
        
        btn_container = QWidget()
        btn_container.setLayout(btn_layout)
        btn_container.setFixedWidth(180)
        layout.addWidget(btn_container, 1)

    def _trigger_admin_create_room(self):
        room_name = self.room_name_input.text().strip()
        if room_name:
            packet = Packet("CREATE_ROOM", payload={"room": room_name})
            self.client.send_packet(packet)
            self.room_name_input.clear()
            self.refresh_all_data()

    def _trigger_admin_delete_room(self):
        item = self.rooms_list.currentItem()
        if item:
            room_text = item.text()
            room_name = room_text.split()[0].replace("#", "")
            if room_name == "General":
                QMessageBox.warning(self, "Invalid Operation", "The default General room cannot be deleted.")
                return
            reply = QMessageBox.question(
                self, "Delete Room", f"Are you sure you want to permanently delete room #{room_name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                packet = Packet("DELETE_ROOM", payload={"room": room_name})
                self.client.send_packet(packet)
                self.refresh_all_data()
