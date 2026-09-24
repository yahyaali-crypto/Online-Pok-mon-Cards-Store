"""
CIS427 PA1 - Pokemon Cards Store: SERVER
"""

import socket
import sqlite3
import sys

# Server port and database file
SERVER_PORT = 1589   # last 4 digits of Zahra's UM-ID (mine is 0947 is a privileged port, <1024, and won't bind on the school server)
DB_FILE = "pokemon_store.db"


#Set up the database and add starter data if the tables are empty
def init_db():
    # Connect to the SQLite database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create the Users table if it does not already exist
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

    # Create the Pokemon cards table if it does not already exist
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

    # Add a default user if the Users table is empty
    cursor.execute("SELECT COUNT(*) FROM Users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO Users (first_name, last_name, user_name, password, usd_balance, is_root)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("John", "Doe", "j_doe", "Passwrd4", 100.0, 1))
        print("Created default user (ID 1) with $100.00 balance")

    #Add starter Pokemon cards if the table is empty
    cursor.execute("SELECT COUNT(*) FROM Pokemon_cards")
    if cursor.fetchone()[0] == 0:
        seed_cards = [
            ("Pikachu", "Electric", "Common", 2, 1),
            ("Charizard", "Fire", "Rare", 1, 1),
            ("Bulbasaur", "Grass", "Common", 50, 1),
            ("Squirtle", "Water", "Uncommon", 30, 1),
            ("Jigglypuff", "Normal", "Common", 3, 1),
        ]
        # Insert all of the starter cards into the database
        cursor.executemany("""
            INSERT INTO Pokemon_cards (card_name, card_type, rarity, count, owner_id)
            VALUES (?, ?, ?, ?, ?)
        """, seed_cards)
        print("Seeded starter Pokemon cards")

    # Save database changes
    conn.commit()
    return conn, cursor


# Return the current balance for a user
def handle_balance(parts, cursor):
    # BALANCE should contain the command and owner ID
    if len(parts) != 2:
        return "403 message format error\n"
    owner_id = parts[1]
    # Find the user and their current balance
    cursor.execute("SELECT first_name, last_name, usd_balance FROM Users WHERE ID = ?", (owner_id,))
    row = cursor.fetchone()
    # Return an error if the user does not exist
    if row is None:
        return f"400 user {owner_id} doesn't exist\n"
    first, last, balance = row
    return f"200 OK\nBalance for user {first} {last}: ${balance:.2f}\n"


# List all Pokemon cards owned by a user
def handle_list(parts, cursor):
    # LIST should contain the command and owner ID
    if len(parts) != 2:
        return "403 message format error\n"
    owner_id = parts[1]

    # Make sure the user exists
    cursor.execute("SELECT ID FROM Users WHERE ID = ?", (owner_id,))
    if cursor.fetchone() is None:
        return f"400 user {owner_id} doesn't exist\n"

    # Get all cards that belong to this user
    cursor.execute("""
        SELECT ID, card_name, card_type, rarity, count, owner_id
        FROM Pokemon_cards WHERE owner_id = ?
    """, (owner_id,))
    rows = cursor.fetchall()

    # Build the response that will be sent back to the client
    response = f"200 OK\nThe list of records in the Pokemon cards table for user {owner_id}:\n"
    response += "ID Card_Name Type Rarity Count OwnerID\n"
    for r in rows:
        response += f"{r[0]} {r[1]} {r[2]} {r[3]} {r[4]} {r[5]}\n"
    return response


# Sell Pokemon cards and add the money to the user's balance
def handle_sell(parts, cursor, conn):
    # Check that the SELL command has the correct number of arguments
    if len(parts) != 5:
        return "403 message format error\n"

    _, card_name, qty_str, price_str, owner_id = parts
    # Convert the quantity and price into numbers
    try:
        qty = int(qty_str)
        price = float(price_str)
    except ValueError:
        return "403 message format error\n"

    # Quantity and price must both be greater than zero
    if qty <= 0 or price <= 0:
        return "403 message format error\n"

    # Check that the user exists and get their current balance
    cursor.execute("SELECT usd_balance FROM Users WHERE ID = ?", (owner_id,))
    user_row = cursor.fetchone()
    if user_row is None:
        return f"400 user {owner_id} doesn't exist\n"

    # Find the card and its current quantity
    cursor.execute("""
        SELECT ID, count FROM Pokemon_cards
        WHERE card_name = ? AND owner_id = ?
    """, (card_name, owner_id))
    card_row = cursor.fetchone()
    # Make sure the user owns enough cards to sell
    if card_row is None or card_row[1] < qty:
        return f"400 not enough {card_name} to sell\n"

    card_id, current_count = card_row
    new_count = current_count - qty
    new_balance = user_row[0] + (qty * price)

    # Remove the card if the new count is zero, otherwise update its count
    if new_count == 0:
        cursor.execute("DELETE FROM Pokemon_cards WHERE ID = ?", (card_id,))
    else:
        cursor.execute("UPDATE Pokemon_cards SET count = ? WHERE ID = ?", (new_count, card_id))

    # Update the user's balance and save the changes
    cursor.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, owner_id))
    conn.commit()

    return f"200 OK\nSOLD: New balance: {new_count} {card_name}. User's balance USD ${new_balance:.2f}\n"


# Buy Pokemon cards and subtract the cost from the user's balance
def handle_buy(parts, cursor, conn):
    # Check that the BUY command has the correct number of arguments
    if len(parts) != 7:
        return "403 message format error\n"

    _, card_name, card_type, rarity, price_str, count_str, owner_id = parts
    # Convert the price and count into numbers
    try:
        price = float(price_str)
        count = int(count_str)
    except ValueError:
        return "403 message format error\n"

    # Price and count must both be greater than zero
    if price <= 0 or count <= 0:
        return "403 message format error\n"

    # Check that the user exists and get their current balance
    cursor.execute("SELECT usd_balance FROM Users WHERE ID = ?", (owner_id,))
    user_row = cursor.fetchone()
    if user_row is None:
        return f"400 user {owner_id} doesn't exist\n"

    # Calculate the total cost and make sure the user has enough money
    total_cost = price * count
    if user_row[0] < total_cost:
        return "400 not enough balance\n"

    new_balance = user_row[0] - total_cost

    # Check if the user already owns this card
    cursor.execute("""
        SELECT ID, count FROM Pokemon_cards
        WHERE card_name = ? AND owner_id = ?
    """, (card_name, owner_id))
    existing = cursor.fetchone()

    # Update the count if the card exists, otherwise add a new card
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

    # Update the user's balance and save the changes
    cursor.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, owner_id))
    conn.commit()

    return f"200 OK\nBOUGHT: New balance: {new_count} {card_name}. User USD balance ${new_balance:.2f}\n"


# Read the command and send it to the correct handler
def handle_command(line, cursor, conn):
    parts = line.strip().split()
    # Reject an empty command
    if not parts:
        return "403 message format error\n"

    cmd = parts[0].upper()

    # Process each supported command
    if cmd == "BALANCE":
        return handle_balance(parts, cursor)
    elif cmd == "LIST":
        return handle_list(parts, cursor)
    elif cmd == "SELL":
        return handle_sell(parts, cursor, conn)
    elif cmd == "BUY":
        return handle_buy(parts, cursor, conn)
    elif cmd == "QUIT":
        if len(parts) != 1:
            return "403 message format error\n"
        return "200 OK\n"
    elif cmd == "SHUTDOWN":
        if len(parts) != 1:
            return "403 message format error\n"
        return "200 OK\n"
    else:
        return "400 invalid command\n"


# Start the server and wait for client connections
def main():
    # Open the database
    conn, cursor = init_db()

    # Create a TCP server socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow the port to be reused after restarting the server
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Bind the socket to the server port and listen for a client
    server_socket.bind(('0.0.0.0', SERVER_PORT))
    server_socket.listen(1)
    print(f"Server listening on port {SERVER_PORT}...")

    try:
        # Keep the server running so another client can connect after one exits
        while True:
            client_socket, addr = server_socket.accept()
            print(f"Connected by {addr}")

            try:
                # Keep receiving commands from the connected client
                while True:
                    data = client_socket.recv(1024).decode()
                    # Stop reading if the client disconnects
                    if not data:
                        break

                    # Print each command received from the client
                    print(f"Received: {data.strip()}")

                    # Process the command and handle unexpected errors
                    try:
                        response = handle_command(data, cursor, conn)
                    except Exception as e:
                        response = "403 message format error\n"
                        print(f"Error handling command: {e}")

                    # Send the result back to the client
                    client_socket.sendall(response.encode())

                    # SHUTDOWN closes the sockets, database, and ends the server
                    if data.strip().upper() == "SHUTDOWN":
                        client_socket.close()
                        server_socket.close()
                        conn.close()
                        print("Server shutting down.")
                        sys.exit(0)

            # Handle a client that disconnects unexpectedly
            except ConnectionError:
                print("Client disconnected unexpectedly.")
            # Close this client before waiting for the next one
            finally:
                client_socket.close()
                print("Client connection closed. Waiting for next client...")

    # Allow the server to be stopped with Ctrl+C
    except KeyboardInterrupt:
        print("\nServer interrupted, shutting down.")
    # Close the server socket and database before exiting
    finally:
        server_socket.close()
        conn.close()


# Run the server when this file is started directly
if __name__ == "__main__":
    main()