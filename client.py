
"""
CIS427 PA2 - Pokemon Card Trading: CLIENT
"""

import socket
import sys
import select

# Make sure the user entered the server hostname and port number
if len(sys.argv) != 3:
    print("Usage: python3 client.py SERVER_HOST SERVER_PORT")
    sys.exit(1)

# Get the server hostname and port number from the command line
server_host = sys.argv[1]

try:
    server_port = int(sys.argv[2])
    if not 1 <= server_port <= 65535:
        raise ValueError
except ValueError:
    print("Error: Please enter a valid port number.")
    sys.exit(1)

# Create a TCP socket and connect to the server
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

try:
    client_socket.connect((server_host, server_port))
except OSError:
    print("Error: Could not connect to the server.")
    client_socket.close()
    sys.exit(1)

print("Connected to the Pokemon Card Trading server.")
print("Enter command: ", end="", flush=True)

# Keep track of messages received from the server
# TCP may deliver part of a message or multiple messages together
receive_buffer = ""

# Remember if the client is waiting for a QUIT or SHUTDOWN response
pending_exit = None

try:
    # Monitor both the keyboard and server socket at the same time
    # This must run on Linux because select() cannot watch
    # keyboard input from the Windows console
    while True:
        readable, _, _ = select.select(
            [sys.stdin, client_socket], [], []
        )

        # Check the server first in case it sent a shutdown message
        if client_socket in readable:
            data = client_socket.recv(4096)

            # An empty response means the server closed the connection
            if not data:
                if receive_buffer:
                    print("\nServer response:")
                    print(receive_buffer)
                print("\nServer disconnected.")
                break

            # Add the received data to the buffer
            receive_buffer += data.decode("utf-8", errors="replace")

            # Display complete lines received from the server
            while "\n" in receive_buffer:
                line, receive_buffer = receive_buffer.split("\n", 1)
                line = line.rstrip("\r")

                # Print server messages even when the user is not typing
                print("\n" + line)

                # A 210 message means root is shutting down the server
                if line.startswith("210 "):
                    print("The server is shutting down. Closing client.")
                    sys.exit(0)

                # Exit after the server confirms QUIT or SHUTDOWN
                if pending_exit and line.startswith("200 OK"):
                    print("Closing client connection.")
                    sys.exit(0)

            print("Enter command: ", end="", flush=True)

        # Check whether the user entered a command
        if sys.stdin in readable:
            message = sys.stdin.readline()

            # Stop if keyboard input is closed
            if not message:
                print("\nClosing client.")
                break

            message = message.strip()

            # Ignore empty commands
            if not message:
                print("Enter command: ", end="", flush=True)
                continue

            # Send the command to the server
            client_socket.sendall((message + "\n").encode("utf-8"))

            # All commands go to the server, including the new PA2 ones:
            # LOGIN, LOGOUT, DEPOSIT, WHO, and LOOKUP
            # The server checks whether the command is allowed

            # Remember if the user requested to quit or shut down
            command = message.split()[0].upper()
            if command in ("QUIT", "SHUTDOWN") and len(message.split()) == 1:
                pending_exit = command

            print("Enter command: ", end="", flush=True)

# Handle errors if the connection is lost while using the client
except (OSError, ValueError) as error:
    print(f"\nConnection error: {error}")

# Allow the user to stop the client using Ctrl+C
except KeyboardInterrupt:
    print("\nClient stopped.")

finally:
    # Close the socket when the client finishes
    client_socket.close()
