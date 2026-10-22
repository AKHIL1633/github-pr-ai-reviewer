import sqlite3


def find_user(conn: sqlite3.Connection, username: str):
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, email FROM users WHERE username = '{username}'")  # expect: security
    return cursor.fetchone()


def count_users(conn: sqlite3.Connection) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    return cursor.fetchone()[0]
