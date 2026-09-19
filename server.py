"""
CIS427 PA1 - Pokemon Cards Store: SERVER
"""

import socket
import sqlite3
import sys

SERVER_PORT = 1234   # <-- replace with last 4 digits of your UM-ID
DB_FILE = "pokemon_store.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Users (
            ID INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            user_name TEXT NOT NULL,
            password TEXT,
            usd_balance DOUBLE NOT NULL,
            is_root INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Pokemon_cards (
            ID INTEGER PRIMARY KEY,
            card_name TEXT NOT NULL,
            card_type TEXT NOT NULL,
            rarity TEXT NOT NULL,
            count INTEGER,
            owner_id INTEGER,
            FOREIGN KEY (owner_id) REFERENCES Users(ID)
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM Users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO Users (first_name, last_name, user_name, password, usd_balance, is_root)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("John", "Doe", "j_doe", "Passwrd4", 100.0, 1))
        print("Created default user (ID 1) with $100.00 balance")

    cursor.execute("SELECT COUNT(*) FROM Pokemon_cards")
    if cursor.fetchone()[0] == 0:
        seed_cards = [
            ("Pikachu", "Electric", "Common", 2, 1),
            ("Charizard", "Fire", "Rare", 1, 1),
            ("Bulbasaur", "Grass", "Common", 50, 1),
            ("Squirtle", "Water", "Uncommon", 30, 1),
            ("Jigglypuff", "Normal", "Common", 3, 1),
        ]
        cursor.executemany("""
            INSERT INTO Pokemon_cards (card_name, card_type, rarity, count, owner_id)
            VALUES (?, ?, ?, ?, ?)
        """, seed_cards)
        print("Seeded starter Pokemon cards")

    conn.commit()
    return conn, cursor


def handle_balance(parts, cursor):
    if len(parts) != 2:
        return "403 message format error\n"
    owner_id = parts[1]
    cursor.execute("SELECT first_name, last_name, usd_balance FROM Users WHERE ID = ?", (owner_id,))
    row = cursor.fetchone()
    if row is None:
        return f"400 user {owner_id} doesn't exist\n"
    first, last, balance = row
    return f"200 OK\nBalance for user {first} {last}: ${balance:.2f}\n"


def handle_list(parts, cursor):
    if len(parts) != 2:
        return "403 message format error\n"
    owner_id = parts[1]

    cursor.execute("SELECT ID FROM Users WHERE ID = ?", (owner_id,))
    if cursor.fetchone() is None:
        return f"400 user {owner_id} doesn't exist\n"

    cursor.execute("""
        SELECT ID, card_name, card_type, rarity, count, owner_id
        FROM Pokemon_cards WHERE owner_id = ?
    """, (owner_id,))
    rows = cursor.fetchall()

    response = f"200 OK\nThe list of records in the Pokemon cards table for user {owner_id}:\n"
    response += "ID Card_Name Type Rarity Count OwnerID\n"
    for r in rows:
        response += f"{r[0]} {r[1]} {r[2]} {r[3]} {r[4]} {r[5]}\n"
    return response


def handle_sell(parts, cursor, conn):
    if len(parts) != 5:
        return "403 message format error\n"

    _, card_name, qty_str, price_str, owner_id = parts
    try:
        qty = int(qty_str)
        price = float(price_str)
    except ValueError:
        return "403 message format error\n"

    cursor.execute("SELECT usd_balance FROM Users WHERE ID = ?", (owner_id,))
    user_row = cursor.fetchone()
    if user_row is None:
        return f"400 user {owner_id} doesn't exist\n"

    cursor.execute("""
        SELECT ID, count FROM Pokemon_cards
        WHERE card_name = ? AND owner_id = ?
    """, (card_name, owner_id))
    card_row = cursor.fetchone()
    if card_row is None or card_row[1] < qty:
        return f"400 not enough {card_name} to sell\n"

    card_id, current_count = card_row
    new_count = current_count - qty
    new_balance = user_row[0] + (qty * price)

    if new_count == 0:
        cursor.execute("DELETE FROM Pokemon_cards WHERE ID = ?", (card_id,))
    else:
        cursor.execute("UPDATE Pokemon_cards SET count = ? WHERE ID = ?", (new_count, card_id))

    cursor.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, owner_id))
    conn.commit()

    return f"200 OK\nSOLD: New balance: {new_count} {card_name}. User's balance USD ${new_balance:.2f}\n"


def handle_buy(parts, cursor, conn):
    if len(parts) != 7:
        return "403 message format error\n"

    _, card_name, card_type, rarity, price_str, count_str, owner_id = parts
    try:
        price = float(price_str)
        count = int(count_str)
    except ValueError:
        return "403 message format error\n"

    cursor.execute("SELECT usd_balance FROM Users WHERE ID = ?", (owner_id,))
    user_row = cursor.fetchone()
    if user_row is None:
        return f"400 user {owner_id} doesn't exist\n"

    total_cost = price * count
    if user_row[0] < total_cost:
        return "400 not enough balance\n"

    new_balance = user_row[0] - total_cost

    cursor.execute("""
        SELECT ID, count FROM Pokemon_cards
        WHERE card_name = ? AND owner_id = ?
    """, (card_name, owner_id))
    existing = cursor.fetchone()

    if existing:
        card_id, existing_count = existing
        new_count = existing_count + count
        cursor.execute("UPDATE Pokemon_cards SET count = ? WHERE ID = ?", (new_count, card_id))
    else:
        new_count = count
        cursor.execute("""
            INSERT INTO Pokemon_cards (card_name, card_type, rarity, count, owner_id)
            VALUES (?, ?, ?, ?, ?)
        """, (card_name, card_type, rarity, count, owner_id))

    cursor.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, owner_id))
    conn.commit()

    return f"200 OK\nBOUGHT: New balance: {new_count} {card_name}. User USD balance ${new_balance:.2f}\n"


def handle_command(line, cursor, conn):
    parts = line.strip().split()
    if not parts:
        return "403 message format error\n"

    cmd = parts[0].upper()

    if cmd == "BALANCE":
        return handle_balance(parts, cursor)
    elif cmd == "LIST":
        return handle_list(parts, cursor)
    elif cmd == "SELL":
        return handle_sell(parts, cursor, conn)
    elif cmd == "BUY":
        return handle_buy(parts, cursor, conn)
    elif cmd == "SHUTDOWN":
        return "200 OK\n"
    else:
        return "400 invalid command\n"


def main():
    conn, cursor = init_db()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', SERVER_PORT))
    server_socket.listen(1)
    print(f"Server listening on port {SERVER_PORT}...")

    try:
        while True:
            client_socket, addr = server_socket.accept()
            print(f"Connected by {addr}")

            try:
                while True:
                    data = client_socket.recv(1024).decode()
                    if not data:
                        break

                    print(f"Received: {data.strip()}")

                    try:
                        response = handle_command(data, cursor, conn)
                    except Exception as e:
                        response = "403 message format error\n"
                        print(f"Error handling command: {e}")

                    client_socket.sendall(response.encode())

                    if data.strip().upper() == "SHUTDOWN":
                        client_socket.close()
                        server_socket.close()
                        conn.close()
                        print("Server shutting down.")
                        sys.exit(0)

            except ConnectionError:
                print("Client disconnected unexpectedly.")
            finally:
                client_socket.close()
                print("Client connection closed. Waiting for next client...")

    except KeyboardInterrupt:
        print("\nServer interrupted, shutting down.")
    finally:
        server_socket.close()
        conn.close()


if __name__ == "__main__":
    main()