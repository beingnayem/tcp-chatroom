import sys
import os
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QStyle, QSystemTrayIcon
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize

# Add parent path to allow relative module imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from client.socket_client import SocketClient
from client.gui.login import LoginWidget

class MainAppWindow(QMainWindow):
    def __init__(self, client):
        super().__init__()
        self.client = client
        
        self.setWindowTitle("Secure TCP Chat Room - TLS Encryption")
        self.resize(450, 650)
        self.setMinimumSize(400, 550)
        
        self.center_window()
        
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1c23, stop:1 #0f1015);
            }
        """)
        
        # Initialize System Tray Icon for Native Desktop Notifications
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        self.tray_icon.show()
        
        # Main stacked container to hold view panels (Login Widget <-> Chat Room)
        self.stacked_widget = QStackedWidget(self)
        self.setCentralWidget(self.stacked_widget)
        
        # Instantiate and add Login view
        self.login_widget = LoginWidget(self.client, self)
        self.stacked_widget.addWidget(self.login_widget)
        self.stacked_widget.setCurrentWidget(self.login_widget)

    def center_window(self):
        qr = self.frameGeometry()
        cp = self.screen().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def show_notification(self, title, message):
        """Displays native cross-platform desktop notification bubble/toast."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(
                title, 
                message, 
                QSystemTrayIcon.MessageIcon.Information, 
                4000
            )

    def switch_to_chat(self, username, login_msg):
        """Transition route switching display to chat dashboard room panel."""
        role = "User"
        if "Role: Admin" in login_msg:
            role = "Admin"
        elif "Role: Moderator" in login_msg:
            role = "Moderator"

        # Remove previous chat widget if exists to prevent duplication leaks
        if hasattr(self, "chat_widget") and self.chat_widget:
            self.stacked_widget.removeWidget(self.chat_widget)
            self.chat_widget.deleteLater()
            self.chat_widget = None

        # Instantiate active Chat Room Dashboard
        from client.gui.chat_room import ChatRoomWidget
        self.chat_widget = ChatRoomWidget(self.client, username, self)
        self.chat_widget.update_role_label(role)
        
        self.stacked_widget.addWidget(self.chat_widget)
        self.stacked_widget.setCurrentWidget(self.chat_widget)
        
        # Transition dimensions smoothly to desktop workspace layout
        self.setMinimumSize(750, 550)
        self.anim = QPropertyAnimation(self, b"size")
        self.anim.setDuration(350)
        self.anim.setStartValue(self.size())
        self.anim.setEndValue(QSize(900, 650))
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.start()
        self.anim.finished.connect(self.center_window)

    def switch_to_login(self):
        """Transition route returning back to Login form."""
        self.stacked_widget.setCurrentWidget(self.login_widget)
        
        # Reset login inputs
        self.login_widget.username_input.clear()
        self.login_widget.password_input.clear()
        self.login_widget.error_label.setText("")
        
        # Restart queue polling timers
        self.login_widget.queue_timer.start(100)
        self.login_widget.status_timer.start(1000)
        
        # Transition back smoothly to smaller layout dimensions
        self.setMinimumSize(400, 550)
        self.anim = QPropertyAnimation(self, b"size")
        self.anim.setDuration(350)
        self.anim.setStartValue(self.size())
        self.anim.setEndValue(QSize(450, 650))
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.start()
        self.anim.finished.connect(self.center_window)
        
        # Destroy chat_widget once transitioned back to login
        if hasattr(self, "chat_widget") and self.chat_widget:
            self.stacked_widget.removeWidget(self.chat_widget)
            self.chat_widget.deleteLater()
            self.chat_widget = None

def main():
    client = SocketClient(host="127.0.0.1", port=8080)
    client.start()
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainAppWindow(client)
    window.show()
    
    app.aboutToQuit.connect(client.disconnect)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
