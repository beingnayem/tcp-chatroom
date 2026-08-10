import bcrypt
import logging
from server.db_manager import DatabaseError

logger = logging.getLogger("server")

def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verifies a password against a hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def register_user(db_manager, username, password):
    """
    Registers a new user and configures their permissions.
    The first registered user is automatically set to Admin role.
    """
    username = username.strip()
    password = password.strip()
    
    if not username or not password:
        return False, "Username and password cannot be empty."
        
    hashed = hash_password(password)
    
    try:
        # Check if database has users
        user_count = db_manager.fetch_one("SELECT COUNT(*) as count FROM users;")
        is_first = (user_count["count"] == 0)
        role = "Admin" if is_first else "User"
        
        # Execute registration inside a transaction block to maintain database consistency
        # Inserts user and establishes permissions in one go
        operations = [
            ("INSERT INTO users (username, password_hash) VALUES (?, ?);", (username, hashed))
        ]
        db_manager.execute_transaction(operations)
        
        # Get the newly created user's ID
        new_user = db_manager.fetch_one("SELECT id FROM users WHERE username = ?;", (username,))
        new_user_id = new_user["id"]
        
        # Setup role in permissions table
        db_manager.execute(
            "INSERT INTO permissions (user_id, role) VALUES (?, ?);",
            (new_user_id, role)
        )
        
        logger.info(f"Registered user '{username}' with role '{role}'")
        return True, "Registration successful."
    except DatabaseError as e:
        logger.warning(f"Registration failed for '{username}': {e}")
        return False, "Username already exists."

def login_user(db_manager, username, password):
    """
    Validates user credentials. Rejects logins for banned users.
    """
    username = username.strip()
    password = password.strip()
    
    try:
        user = db_manager.fetch_one(
            "SELECT * FROM users WHERE username = ?;",
            (username,)
        )
    except DatabaseError as e:
        logger.error(f"Database error during login fetch: {e}")
        return False, "Authentication server error."
        
    if not user:
        return False, "Invalid username or password."
        
    if user["status"] == "Banned":
        return False, "Your account has been banned by an administrator."
        
    if verify_password(password, user["password_hash"]):
        return True, "Login successful."
    else:
        return False, "Invalid username or password."
