import socket
import sys

# Get the server hostname and port number from the command line
server_host = sys.argv[1]
server_port = int(sys.argv[2])

# Create a TCP socket and connect to the server
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect((server_host, server_port))

# Keep accepting commands until the user quits or shuts down the server
while True:
    message = input("Enter command: ")

    # Send the command to the server
    client_socket.sendall((message + "\n").encode())

    # Receive and display the server's response
    response = client_socket.recv(4096).decode()
    print("Server response:")
    print(response)

    # Stop the client after QUIT or SHUTDOWN
    if message.strip().upper() in ["QUIT", "SHUTDOWN"]:
        break

# Close the connection to the server
client_socket.close()