import sqlite3
import logging
import threading

logger = logging.getLogger("server")

class DatabaseError(Exception):
    """Custom exception class for database layer errors."""
    pass

class DatabaseManager:
    def __init__(self, db_path="chat_room.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.init_db()

    def _get_connection(self):
        """Creates and returns a connection. Sets row factory for dictionary-like results."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for high concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            # Enable foreign keys enforcement
            conn.execute("PRAGMA foreign_keys=ON;")
            return conn
        except sqlite3.Error as e:
            logger.error(f"Failed to open database connection: {e}")
            raise DatabaseError(f"Database connection error: {e}")

    def init_db(self):
        """Executes table creation queries inside a single initialization transaction."""
        schema_queries = [
            # 1. Users Table
            ("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Offline',
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """, None),
            # 2. Rooms Table
            ("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                type TEXT NOT NULL DEFAULT 'Public',
                creator_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE SET NULL
            );
            """, None),
            # 3. Messages Table
            ("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER,
                content TEXT NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """, None),
            # 5. Logs Table
            ("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                source TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """, None),
            # 6. Permissions Table
            ("""
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                role TEXT NOT NULL DEFAULT 'User',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """, None),
            # 7. Room Members Table
            ("""
            CREATE TABLE IF NOT EXISTS room_members (
                room_id INTEGER,
                user_id INTEGER,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """, None)
        ]
        
        try:
            self.execute_transaction(schema_queries)
            logger.info("Database schemas initialized successfully.")
        except DatabaseError as e:
            logger.critical(f"Critical error during database schema initialization: {e}")
            raise

    # ================= GENERIC CRUD & PARAMETERIZED QUERIES =================

    def execute(self, query, params=None):
        """
        Executes a single write operation (INSERT, UPDATE, DELETE).
        Returns the lastrowid for INSERTs, or rowcount for updates/deletes.
        """
        if params is None:
            params = ()
            
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                conn.commit()
                if query.strip().upper().startswith("INSERT"):
                    result = cursor.lastrowid
                else:
                    result = cursor.rowcount
                return result
            except sqlite3.Error as e:
                logger.error(f"Query execution failed: {query} with params {params}. Error: {e}")
                raise DatabaseError(f"Database write execution error: {e}")
            finally:
                conn.close()

    def fetch_all(self, query, params=None):
        """
        Executes a parameterized read query and returns all matching rows as dictionaries.
        """
        if params is None:
            params = ()

        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            except sqlite3.Error as e:
                logger.error(f"Read query execution failed: {query} with params {params}. Error: {e}")
                raise DatabaseError(f"Database read query error: {e}")
            finally:
                conn.close()

    def fetch_one(self, query, params=None):
        """
        Executes a parameterized read query and returns a single matching row as a dictionary,
        or None if no rows match.
        """
        if params is None:
            params = ()

        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None
            except sqlite3.Error as e:
                logger.error(f"Read query execution failed: {query} with params {params}. Error: {e}")
                raise DatabaseError(f"Database read query error: {e}")
            finally:
                conn.close()

    # ================= TRANSACTION MANAGEMENT =================

    def execute_transaction(self, operations):
        """
        Executes multiple database write operations within a single SQL transaction.
        If any query fails, the entire transaction is rolled back.
        
        Args:
            operations (list): List of tuples in the format (query_string, params_tuple)
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # Begin explicit transaction block
                conn.execute("BEGIN TRANSACTION;")
                for query, params in operations:
                    if params is None:
                        params = ()
                    cursor.execute(query, params)
                conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error(f"Transaction failed. Rolling back database operations. Error: {e}")
                try:
                    conn.rollback()
                except sqlite3.Error as rollback_err:
                    logger.error(f"Failed to rollback transaction: {rollback_err}")
                raise DatabaseError(f"Database transaction error: {e}")
            finally:
                conn.close()
