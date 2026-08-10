import queue
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel, QFormLayout, QFrame
)
from PySide6.QtCore import QTimer, Qt
from common.protocol import Packet

class LoginWidget(QWidget):
    def __init__(self, client, main_window):
        super().__init__()
        self.client = client
        self.main_window = main_window
        self.is_register_mode = False
        
        self._init_ui()
        
        # Start a periodic QTimer (100ms) to check incoming socket queue
        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self._check_network_queue)
        self.queue_timer.start(100)
        
        # Start a slower timer (1s) to refresh connection status indicator
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_connection_status)
        self.status_timer.start(1000)

    def _init_ui(self):
        self.setStyleSheet("""
            LoginWidget {
                background: transparent;
            }
            QWidget {
                color: #abb2bf;
                font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                font-size: 14px;
            }
            QLabel {
                background: transparent;
                color: #8a92a5;
                font-weight: 500;
            }
            QLabel#titleLabel {
                color: #ffffff;
                font-size: 24px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }
            QLabel#fieldLabel {
                color: #8a92a5;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            QLineEdit {
                background-color: rgba(0, 0, 0, 0.25);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 12px 14px;
                color: #ffffff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #528bff;
                background-color: rgba(0, 0, 0, 0.4);
            }
            QPushButton#actionButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b23d, stop:1 #00d64a);
                color: #ffffff;
                font-weight: bold;
                font-size: 15px;
                border: none;
                border-radius: 22px;
                height: 44px;
                padding: 10px;
            }
            QPushButton#actionButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00c744, stop:1 #00ea51);
            }
            QPushButton#actionButton:pressed {
                background: #008f30;
            }
            QPushButton#toggleLink {
                background: none;
                border: none;
                color: #528bff;
                text-decoration: underline;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton#toggleLink:hover {
                color: #6ea3ff;
            }
            QPushButton#toggleLink:pressed {
                color: #3562be;
            }
            QLabel#errorLabel {
                color: #e06c75;
                font-size: 12px;
                font-weight: bold;
            }
            QFrame#cardFrame {
                background-color: rgba(33, 37, 43, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)

        # Main Layout to center the Card container
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addStretch()

        center_v = QVBoxLayout()
        center_v.addStretch()

        # The Compact Card widget
        self.card = QFrame(self)
        self.card.setObjectName("cardFrame")
        self.card.setFixedSize(380, 520)
        
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(30, 35, 30, 35)
        card_layout.setSpacing(14)

        # Title inside Card
        self.title_label = QLabel("Good to see you again", self)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.title_label)

        # Connection Status indicator inside Card
        self.status_layout = QHBoxLayout()
        self.status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_layout.setSpacing(6)
        
        self.status_dot = QWidget(self)
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setStyleSheet("border-radius: 4px; background-color: #e06c75;")
        self.status_layout.addWidget(self.status_dot)
        
        self.status_text = QLabel("Checking connection...", self)
        self.status_text.setStyleSheet("font-size: 11px; font-weight: normal; color: #8a92a5;")
        self.status_layout.addWidget(self.status_text)
        
        card_layout.addLayout(self.status_layout)
        card_layout.addSpacing(10)

        # Username Input Section
        user_lbl = QLabel("Your Username", self)
        user_lbl.setObjectName("fieldLabel")
        card_layout.addWidget(user_lbl)

        self.username_input = QLineEdit(self)
        self.username_input.setPlaceholderText("👤  e.g. elon")
        card_layout.addWidget(self.username_input)

        # Password Input Section
        pass_lbl = QLabel("Your Password", self)
        pass_lbl.setObjectName("fieldLabel")
        card_layout.addWidget(pass_lbl)

        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("🔒  ••••••••")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        card_layout.addWidget(self.password_input)

        # Validation error message placeholder
        self.error_label = QLabel("", self)
        self.error_label.setObjectName("errorLabel")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        card_layout.addWidget(self.error_label)
        
        card_layout.addStretch()

        # Green Pill Action Button
        self.action_btn = QPushButton("Sign in", self)
        self.action_btn.setObjectName("actionButton")
        self.action_btn.clicked.connect(self._handle_action)
        card_layout.addWidget(self.action_btn)

        # Flat state switcher Link Button
        self.toggle_link_btn = QPushButton("Don't have an account? Create one", self)
        self.toggle_link_btn.setObjectName("toggleLink")
        self.toggle_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_link_btn.clicked.connect(self._toggle_form_mode)
        card_layout.addWidget(self.toggle_link_btn)

        center_v.addWidget(self.card)
        center_v.addStretch()

        main_layout.addLayout(center_v)
        main_layout.addStretch()

        self._update_connection_status()

    def _toggle_form_mode(self):
        self.is_register_mode = not self.is_register_mode
        self.error_label.setText("")
        if self.is_register_mode:
            self.title_label.setText("Create your account")
            self.action_btn.setText("Sign up")
            self.toggle_link_btn.setText("Already have an account? Sign in")
        else:
            self.title_label.setText("Good to see you again")
            self.action_btn.setText("Sign in")
            self.toggle_link_btn.setText("Don't have an account? Create one")

    def _update_connection_status(self):
        if self.client.connected:
            self.status_dot.setStyleSheet("border-radius: 4px; background-color: #98c379;")
            self.status_text.setText("Connected (Secure TLS)")
        else:
            self.status_dot.setStyleSheet("border-radius: 4px; background-color: #e06c75;")
            self.status_text.setText("Disconnected (Reconnecting...)")

    def _validate_inputs(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        if not username or not password:
            self.error_label.setText("Username and password fields cannot be empty.")
            return None, None
            
        if len(username) < 3:
            self.error_label.setText("Username must be at least 3 characters.")
            return None, None
            
        self.error_label.setText("")
        return username, password

    def _handle_action(self):
        if self.is_register_mode:
            self._handle_registration()
        else:
            self._handle_login()

    def _handle_login(self):
        if not self.client.connected:
            self.error_label.setText("Unable to send request. Server is offline.")
            return

        username, password = self._validate_inputs()
        if not username:
            return

        self.error_label.setText("Authenticating...")
        
        packet = Packet(
            message_type="LOGIN",
            sender=None,
            receiver=None,
            room=None,
            payload={"username": username, "password": password}
        )
        self.client.send_packet(packet)

    def _handle_registration(self):
        if not self.client.connected:
            self.error_label.setText("Unable to send request. Server is offline.")
            return

        username, password = self._validate_inputs()
        if not username:
            return

        self.error_label.setText("Registering account...")
        
        packet = Packet(
            message_type="REGISTER",
            sender=None,
            receiver=None,
            room=None,
            payload={"username": username, "password": password}
        )
        self.client.send_packet(packet)

    def _check_network_queue(self):
        while not self.client.receive_queue.empty():
            try:
                packet = self.client.receive_queue.get_nowait()
                mtype = packet.message_type
                payload = packet.payload or {}
                
                if mtype == "REGISTER_RESP":
                    success = payload.get("success")
                    msg = payload.get("message")
                    if success:
                        self.error_label.setStyleSheet("color: #98c379; font-size: 12px; font-weight: bold;")
                        self.error_label.setText("Account created! Please log in.")
                        self._toggle_form_mode() # Switch back to login mode automatically
                    else:
                        self.error_label.setStyleSheet("color: #e06c75; font-size: 12px; font-weight: bold;")
                        self.error_label.setText(msg)
                        
                elif mtype == "LOGIN_RESP":
                    success = payload.get("success")
                    msg = payload.get("message")
                    if success:
                        self.error_label.setStyleSheet("color: #98c379; font-size: 12px; font-weight: bold;")
                        self.error_label.setText("Access granted! Connecting...")
                        
                        # Stop login timers to prevent race conditions on queue checks
                        self.queue_timer.stop()
                        self.status_timer.stop()
                        
                        # Trigger MainWindow switch to chat workspace
                        self.main_window.switch_to_chat(self.username_input.text().strip(), msg)
                        self.client.receive_queue.task_done()
                        break
                    else:
                        self.error_label.setStyleSheet("color: #e06c75; font-size: 12px; font-weight: bold;")
                        self.error_label.setText(msg)
                        self.client.receive_queue.task_done()
                        continue
                        
                self.client.receive_queue.task_done()
            except queue.Empty:
                break
            except Exception as e:
                self.error_label.setText(f"Process error: {e}")
                break
