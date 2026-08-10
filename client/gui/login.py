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
            QWidget {
                background-color: #1e222b;
                color: #abb2bf;
                font-family: 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
            }
            QLabel {
                color: #abb2bf;
            }
            QLabel#titleLabel {
                color: #ffffff;
                font-size: 24px;
                font-weight: bold;
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
                background-color: #528bff;
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #4376db;
            }
            QPushButton:pressed {
                background-color: #3562be;
            }
            QPushButton#registerButton {
                background-color: #3e4451;
                color: #ffffff;
            }
            QPushButton#registerButton:hover {
                background-color: #4c5364;
            }
            QLabel#errorLabel {
                color: #e06c75;
                font-size: 12px;
                font-weight: bold;
            }
            QFrame#cardFrame {
                background-color: #21252b;
                border: 1px solid #2b313c;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Title Section
        self.title_label = QLabel("Secure Chat Room", self)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        # Connection Status indicator (Sub-Layout)
        self.status_layout = QHBoxLayout()
        self.status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Indicator dot
        self.status_dot = QWidget(self)
        self.status_dot.setFixedSize(10, 10)
        self.status_dot.setStyleSheet("border-radius: 5px; background-color: #e06c75;")
        self.status_layout.addWidget(self.status_dot)
        
        self.status_text = QLabel("Checking connection...", self)
        self.status_text.setStyleSheet("font-size: 12px;")
        self.status_layout.addWidget(self.status_text)
        
        layout.addLayout(self.status_layout)

        # Card container for input fields
        self.card = QFrame(self)
        self.card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(15)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        self.username_input = QLineEdit(self)
        self.username_input.setPlaceholderText("Enter username")
        form_layout.addRow("Username:", self.username_input)

        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form_layout.addRow("Password:", self.password_input)

        card_layout.addLayout(form_layout)

        # Validation error message placeholder
        self.error_label = QLabel("", self)
        self.error_label.setObjectName("errorLabel")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        card_layout.addWidget(self.error_label)

        layout.addWidget(self.card)

        # Action Buttons
        self.login_btn = QPushButton("Log In", self)
        self.login_btn.clicked.connect(self._handle_login)
        layout.addWidget(self.login_btn)

        self.register_btn = QPushButton("Create Account", self)
        self.register_btn.setObjectName("registerButton")
        self.register_btn.clicked.connect(self._handle_registration)
        layout.addWidget(self.register_btn)

        layout.addStretch()

        self._update_connection_status()

    def _update_connection_status(self):
        if self.client.connected:
            self.status_dot.setStyleSheet("border-radius: 5px; background-color: #98c379;")
            self.status_text.setText("Connected (Secure TLS)")
        else:
            self.status_dot.setStyleSheet("border-radius: 5px; background-color: #e06c75;")
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
