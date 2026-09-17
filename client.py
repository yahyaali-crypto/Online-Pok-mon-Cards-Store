import socket
import sys

server_host = sys.argv[1]
server_port = int(sys.argv[2])

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect((server_host, server_port))

message = input("Enter a message: ")
client_socket.sendall(message.encode())

response = client_socket.recv(1024)
print("Server response:", response.decode())

client_socket.close()