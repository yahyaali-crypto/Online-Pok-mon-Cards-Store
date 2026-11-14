import math
import socket
import sqlite3
import threading

# Server settings and limits for incoming commands and transactions 
SERVER_PORT = 1589
DB_FILE = "pokemon_store.db"
MAX_CLIENTS = 10
MAX_LINE = 4096
MAX_AMOUNT = 1000000000
MAX_COUNT = 1000000

# Default accounts created when the database is first set up. 
REQUIRED_USERS = [
    ("root", "root01", "Root", "Admin", 100.0, 1),
    ("mary", "mary01", "Mary", "Smith", 100.0, 0),
    ("john", "john01", "John", "Doe", 100.0, 0),
    ("moe", "moe01", "Moe", "Howard", 100.0, 0),
]
# Starting Pokemon cards for each new account. 
STARTER_CARDS = {
    "root": [("Jigglypuff", "Normal", "Common", 3)],
    "mary": [("Charizard", "Fire", "Rare", 1), ("Squirtle", "Water", "Uncommon", 30)],
    "john": [("Pikachu", "Electric", "Common", 2), ("Charizard", "Fire", "Rare", 6)],
    "moe": [("Bulbasaur", "Grass", "Common", 50)],
}
 # Commands the server accepts from clients
COMMANDS = {"LOGIN", "LOGOUT", "BUY", "SELL", "LIST", "BALANCE",
            "DEPOSIT", "WHO", "LOOKUP", "QUIT", "SHUTDOWN"}

# Shared data and locks help keep multiple client threads from interfering. 
db = None
db_lock = threading.Lock()
clients = []
clients_lock = threading.Lock()
print_lock = threading.Lock()
shutdown_event = threading.Event()
 

# Print server messages safely when several threads are running. 
def log(message):
    with print_lock:
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            print(message.encode("ascii", "replace").decode("ascii"), flush=True)
 

# Keep track of each client connection and its login information 
class Session:
 
    def __init__(self, sock, addr):
        self.sock = sock
        self.ip = addr[0]
        self.port = addr[1]
        self.user_id = None
        self.user_name = None
        self.is_root = False
        self.send_lock = threading.Lock()
 
    def logged_in(self):
        return self.user_id is not None
 
    def label(self):
        who = self.user_name if self.logged_in() else "not logged in"
        return f"{self.ip}:{self.port} ({who})"

    # Prevent two threads from sending messages on this socket at once.
    def send(self, text):
        with self.send_lock:
            self.sock.sendall(text.encode("utf-8"))

    # Close a client connection even if it has already disconnected.
    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
 

# Build a response for an invalid command. 
def reply_400(message):
    return f"400 invalid command\n{message}\n"
 
# Build a response when a user does not have permission 
def reply_401(message):
    return f"401 not authorized\n{message}\n"
 
# Check that a money amount is a valid positive number 
def parse_amount(text):
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0 or value > MAX_AMOUNT:
        return None
    return round(value, 2)
 

# Check that a card quantity is a valid positive whole number. 
def parse_count(text):
    try:
        value = int(text)
    except ValueError:
        return None
    if value <= 0 or value > MAX_COUNT:
        return None
    return value
 

# Create the database tables and add the required users if needed 
def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cur = conn.cursor()
 
    cur.execute("""
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
    cur.execute("""
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

    # Keep existing balances and cards, but update the required login details.
    for user_name, password, first, last, balance, is_root in REQUIRED_USERS:
        cur.execute("SELECT ID FROM Users WHERE user_name = ?", (user_name,))
        row = cur.fetchone()
        if row is None:
            cur.execute("""
                INSERT INTO Users (first_name, last_name, user_name, password, usd_balance, is_root)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (first, last, user_name, password, balance, is_root))
            new_id = cur.lastrowid
            for card_name, card_type, rarity, count in STARTER_CARDS.get(user_name, []):
                cur.execute("""
                    INSERT INTO Pokemon_cards (card_name, card_type, rarity, count, owner_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (card_name, card_type, rarity, count, new_id))
            log(f"Created user '{user_name}' with ${balance:.2f}")
        else:
            cur.execute("UPDATE Users SET password = ?, is_root = ? WHERE ID = ?",
                        (password, is_root, row[0]))
 
    cur.execute("UPDATE Users SET is_root = 0 WHERE user_name != 'root'")
    conn.commit()
    cur.close()
    return conn
 

# Columns used when looking up user accounts. 
USER_COLUMNS = "ID, user_name, first_name, last_name, usd_balance"
 

# Find a user by their database ID. 
def user_by_id(cur, user_id):
    cur.execute(f"SELECT {USER_COLUMNS} FROM Users WHERE ID = ?", (user_id,))
    return cur.fetchone()
 
# Find a user by username or numeric ID 
def user_by_name_or_id(cur, ident):
    cur.execute(f"SELECT {USER_COLUMNS} FROM Users WHERE user_name = ?", (ident,))
    row = cur.fetchone()
    if row is None and ident.isascii() and ident.isdigit():
        row = user_by_id(cur, int(ident))
    return row
 
# Format a user's name for display. 
def full_name(row):
    name = f"{row[2] or ''} {row[3] or ''}".strip()
    return name if name else row[1]
 
# Regular users access their own records; root may access other users. 
def get_target(cur, session, arg):
    me = user_by_id(cur, session.user_id)
    if me is None:
        return None, reply_401("Your account no longer exists.")
    if arg is None or arg == me[1] or arg == str(me[0]):
        return me, None
    if not session.is_root:
        return None, reply_401("Only root can act on another user's records.")
    other = user_by_name_or_id(cur, arg)
    if other is None:
        return None, reply_400(f"User {arg} doesn't exist.")
    return other, None

 
# Format card records into a readable table for the client. 
def format_cards(rows):
    text = f"{'ID':<5}{'Card Name':<14}{'Type':<11}{'Rarity':<11}{'Count':<7}Owner\n"
    for r in rows:
        text += f"{r[0]:<5}{r[1]:<14}{r[2]:<11}{r[3]:<11}{r[4]:<7}{r[5]}\n"
    return text
 

# Check the username and password and save the login in this session
def handle_login(cur, session, parts):
    if len(parts) != 3:
        return reply_400("Usage: LOGIN <UserID> <Password>")
    if session.logged_in():
        return reply_400(f"Already logged in as {session.user_name}. LOGOUT first.")
    cur.execute("SELECT ID, user_name, is_root FROM Users WHERE user_name = ? AND password = ?",
                (parts[1], parts[2]))
    row = cur.fetchone()
    if row is None:
        return "403 Wrong UserID or Password\n"
    session.user_id, session.user_name, session.is_root = row[0], row[1], bool(row[2])
    return "200 OK\n"
 
# Return the balance for the current user or an allowed target user. 
def handle_balance(cur, session, parts):
    if len(parts) > 2:
        return reply_400("Usage: BALANCE")
    target, error = get_target(cur, session, parts[1] if len(parts) == 2 else None)
    if error:
        return error
    return f"200 OK\nBalance for user {full_name(target)}: ${target[4]:.2f}\n"

 
# List owned cards; root can also list every card in the database 
def handle_list(cur, session, parts):
    if len(parts) > 2:
        return reply_400("Usage: LIST")
    if len(parts) == 1 and session.is_root:
        cur.execute("""
            SELECT c.ID, c.card_name, c.card_type, c.rarity, c.count,
                   COALESCE(u.user_name, 'unknown')
            FROM Pokemon_cards c LEFT JOIN Users u ON c.owner_id = u.ID
            ORDER BY c.ID
        """)
        return ("200 OK\nThe list of records in the cards database:\n"
                + format_cards(cur.fetchall()))
    target, error = get_target(cur, session, parts[1] if len(parts) == 2 else None)
    if error:
        return error
    cur.execute("""
        SELECT c.ID, c.card_name, c.card_type, c.rarity, c.count, u.user_name
        FROM Pokemon_cards c JOIN Users u ON c.owner_id = u.ID
        WHERE c.owner_id = ? ORDER BY c.ID
    """, (target[0],))
    return (f"200 OK\nThe list of records in the Pokémon cards table for current user, {target[1]}:\n"
            + format_cards(cur.fetchall()))
 

# Search the current user's cards by part of the card name
def handle_lookup(cur, session, parts):
    if len(parts) < 2:
        return reply_400("Usage: LOOKUP <card name>")
    needle = " ".join(parts[1:]).lower()
    cur.execute("""
        SELECT c.ID, c.card_name, c.card_type, c.rarity, c.count, u.user_name
        FROM Pokemon_cards c JOIN Users u ON c.owner_id = u.ID
        WHERE c.owner_id = ? AND instr(lower(c.card_name), ?) > 0
        ORDER BY c.ID
    """, (session.user_id, needle))
    rows = cur.fetchall()
    if not rows:
        return "404 Your search did not match any records.\n"
    word = "match" if len(rows) == 1 else "matches"
    return f"200 OK\nFound {len(rows)} {word}\n" + format_cards(rows)
 

# Add money to the logged-in user's balance 
def handle_deposit(cur, conn, session, parts):
    if len(parts) != 2:
        return reply_400("Usage: DEPOSIT <amount>")
    amount = parse_amount(parts[1])
    if amount is None:
        return reply_400("Deposit amount must be a positive number.")
    me = user_by_id(cur, session.user_id)
    new_balance = round(me[4] + amount, 2)
    cur.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, me[0]))
    conn.commit()
    return f"200 OK\nDeposit successful. New User balance ${new_balance:.2f}\n"
 
# Check the cost, add purchased cards, and subtract money 
def handle_buy(cur, conn, session, parts):
    if len(parts) not in (6, 7):
        return reply_400("Usage: BUY <card_name> <card_type> <rarity> <price> <count>")
    card_name, card_type, rarity = parts[1], parts[2], parts[3]
    price = parse_amount(parts[4])
    count = parse_count(parts[5])
    if price is None or count is None:
        return reply_400("Price must be a positive number and count must be a positive whole number.")
    target, error = get_target(cur, session, parts[6] if len(parts) == 7 else None)
    if error:
        return error

    # Do not allow a purchase if the account has insufficient funds
    total_cost = round(price * count, 2)
    if target[4] < total_cost:
        return reply_400(f"Not enough USD balance (need ${total_cost:.2f}, have ${target[4]:.2f}).")
    new_balance = round(target[4] - total_cost, 2)
 
    cur.execute("SELECT ID, count FROM Pokemon_cards WHERE card_name = ? AND owner_id = ?",
                (card_name, target[0]))
    existing = cur.fetchone()
    # Increase the count of an owned card or insert a new card record
    if existing:
        new_count = existing[1] + count
        cur.execute("UPDATE Pokemon_cards SET count = ? WHERE ID = ?", (new_count, existing[0]))
    else:
        new_count = count
        cur.execute("""
            INSERT INTO Pokemon_cards (card_name, card_type, rarity, count, owner_id)
            VALUES (?, ?, ?, ?, ?)
        """, (card_name, card_type, rarity, count, target[0]))
    cur.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, target[0]))
    conn.commit()
    return f"200 OK\nBOUGHT: New balance: {new_count} {card_name}. User USD balance ${new_balance:.2f}\n"
 

# Check card ownership, reduce the card count, and add the sale amount. 
def handle_sell(cur, conn, session, parts):
    if len(parts) not in (4, 5):
        return reply_400("Usage: SELL <card_name> <quantity> <price>")
    card_name = parts[1]
    qty = parse_count(parts[2])
    price = parse_amount(parts[3])
    if qty is None or price is None:
        return reply_400("Quantity must be a positive whole number and price must be a positive number.")
    target, error = get_target(cur, session, parts[4] if len(parts) == 5 else None)
    if error:
        return error
 
    cur.execute("SELECT ID, count FROM Pokemon_cards WHERE card_name = ? AND owner_id = ?",
                (card_name, target[0]))
    card = cur.fetchone()
    if card is None or card[1] < qty:
        owned = card[1] if card else 0
        return reply_400(f"Not enough {card_name} to sell (you have {owned}, tried to sell {qty}).")
 
    new_count = card[1] - qty
    new_balance = round(target[4] + qty * price, 2)
    # Remove the card record when the last copy is sold
    if new_count == 0:
        cur.execute("DELETE FROM Pokemon_cards WHERE ID = ?", (card[0],))
    else:
        cur.execute("UPDATE Pokemon_cards SET count = ? WHERE ID = ?", (new_count, card[0]))
    cur.execute("UPDATE Users SET usd_balance = ? WHERE ID = ?", (new_balance, target[0]))
    conn.commit()
    return f"200 OK\nSOLD: New balance: {new_count} {card_name}. User's balance USD ${new_balance:.2f}\n"
 

# Show connected, logged-in users; only root can use WHO. 
def handle_who(session, parts):
    if len(parts) != 1:
        return reply_400("Usage: WHO")
    if not session.is_root:
        return reply_401("Only root can use WHO.")
    with clients_lock:
        active = [(s.user_name, s.ip) for s in clients if s.logged_in()]
    text = "200 OK\nThe list of the active users:\n"
    for name, ip in active:
        text += f"{name:<12}{ip}\n"
    return text
 

# Send each command to its handler and check login/permissions.
def dispatch(cur, session, cmd, parts):
    if cmd == "QUIT":
        if len(parts) != 1:
            return reply_400("QUIT takes no arguments."), None
        return "200 OK\n", "quit"
 
    if cmd == "LOGIN":
        return handle_login(cur, session, parts), None
 
    if not session.logged_in():
        return reply_401("Please LOGIN first."), None
 
    if cmd == "LOGOUT":
        if len(parts) != 1:
            return reply_400("LOGOUT takes no arguments."), None
        session.user_id, session.user_name, session.is_root = None, None, False
        return "200 OK\n", None
    if cmd == "BALANCE":
        return handle_balance(cur, session, parts), None
    if cmd == "LIST":
        return handle_list(cur, session, parts), None
    if cmd == "LOOKUP":
        return handle_lookup(cur, session, parts), None
    if cmd == "DEPOSIT":
        return handle_deposit(cur, db, session, parts), None
    if cmd == "BUY":
        return handle_buy(cur, db, session, parts), None
    if cmd == "SELL":
        return handle_sell(cur, db, session, parts), None
    if cmd == "WHO":
        return handle_who(session, parts), None
    if cmd == "SHUTDOWN":
        if len(parts) != 1:
            return reply_400("SHUTDOWN takes no arguments."), None
        if not session.is_root:
            return reply_401("Only root can shut down the server."), None
        return "200 OK\n", "shutdown"
 
    return reply_400("Unknown command."), None
 

# Validate a command and protect shared database access with a lock. 
def handle_command(line, session):
    parts = line.split()
    if not parts:
        return reply_400("Empty command."), None
    cmd = parts[0].upper()
    if cmd not in COMMANDS:
        return reply_400(f"Unknown command: {parts[0][:30]}"), None

    # Only one thread uses the shared SQLite connection at a time.
    with db_lock:
        cur = db.cursor()
        try:
            return dispatch(cur, session, cmd, parts)
        except Exception:
            db.rollback()
            raise
        finally:
            cur.close()
 

# Notify other clients before closing their connections. 
def begin_shutdown(requester):
    who = requester.label() if requester else "Ctrl+C"
    log(f"SHUTDOWN requested by {who}. Notifying all other clients.")
    # Signal the server and client threads to stop.
    shutdown_event.set()
    with clients_lock:
        others = [s for s in clients if s is not requester]
    for s in others:
        try:
            s.send("210 the server is about to shutdown ......\n")
        except OSError:
            pass
    for s in others:
        s.close()
 

# Handle one client in its own thread until it quits or disconnects. 
def client_thread(session):
    buffer = b""
    try:
        while not shutdown_event.is_set():
            try:
                chunk = session.sock.recv(1024)
            except OSError:
                break
            if not chunk:
                break
            # A command may arrive in pieces, so collect bytes until a newline.
            buffer += chunk
 
            while True:
                newline = buffer.find(b"\n")
                if newline == -1:
                    if len(buffer) > MAX_LINE:
                        buffer = b""
                        session.send(reply_400("Command is too long."))
                    break
                raw, buffer = buffer[:newline], buffer[newline + 1:]
                line = raw.decode("utf-8", errors="replace").strip()
                log(f"Received from {session.label()}: {line}")
 
                try:
                    reply, action = handle_command(line, session)
                except Exception as error:
                    log(f"Error while handling '{line}': {error!r}")
                    reply, action = reply_400("The server could not process that command."), None
                # Send the result, then handle QUIT or SHUTDOWN if requested
                session.send(reply)
                if action == "quit":
                    return
                if action == "shutdown":
                    begin_shutdown(session)
                    return
    except OSError:
        pass
    except Exception as error:
        log(f"Unexpected error with {session.label()}: {error!r}")
    finally:
        # Remove the disconnected client from the active client list.
        with clients_lock:
            if session in clients:
                clients.remove(session)
            remaining = len(clients)
        log(f"Disconnected: {session.label()} ({remaining} client(s) connected)")
        session.close()
 
# Start the server, accept connections, and create a thread per client. 
def main():
    global db
    db = init_db()

    # Listen on the configured port and allow the address to be reused.
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("0.0.0.0", SERVER_PORT))
    server_socket.listen(20)
    server_socket.settimeout(1.0)
    log(f"Server listening on port {SERVER_PORT}...")
 
    threads = []
    try:
        while not shutdown_event.is_set():
            try:
                client_socket, addr = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client_socket.settimeout(None)
            session = Session(client_socket, addr)

            # Enforce the limit of 10 active client connections.
            with clients_lock:
                accepted = len(clients) < MAX_CLIENTS
                if accepted:
                    clients.append(session)
                connected = len(clients)

            # Reject the 11th client without stopping the server.
            if not accepted:
                log(f"Rejected {addr[0]}:{addr[1]} - server already has {MAX_CLIENTS} clients")
                try:
                    session.send(f"400 server is full\nThe server already has {MAX_CLIENTS} "
                                 f"clients connected. Try again later.\n")
                except OSError:
                    pass
                session.close()
                continue
 
            log(f"Connected: {addr[0]}:{addr[1]} ({connected} client(s) connected)")
            # Each accepted client gets its own worker thread.
            thread = threading.Thread(target=client_thread, args=(session,), daemon=True)
            thread.start()
            threads = [t for t in threads if t.is_alive()] + [thread]

    # Also clean up if the server is stopped with Ctrl+C
    except KeyboardInterrupt:
        log("\nServer interrupted with Ctrl+C.")
    finally:
        if not shutdown_event.is_set():
            begin_shutdown(None)
        server_socket.close()
        for thread in threads:
            thread.join(timeout=2)
        with db_lock:
            db.close()
        log("Server shut down. All sockets and the database are closed.")
 

# Run the server only when this file is executed directly. 
if __name__ == "__main__":
    main()