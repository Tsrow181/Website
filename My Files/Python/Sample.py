import os
import subprocess
import signal
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
ROOTFS_DIR = os.path.join(PREFIX, "var/lib/proot-distro/installed-rootfs")
DISTRO_CONF_DIR = os.path.join(PREFIX, "etc/proot-distro")

# Store active sandboxes in memory: { name: { port, distro, pid } }
sandboxes = {}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Termux Sandbox Manager</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }
        .container { max-width: 1000px; margin: auto; }
        .card { background: #1e293b; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1, h2 { color: #38bdf8; margin-top: 0; }
        label { display: block; margin: 10px 0 5px; font-weight: bold; }
        input, select { width: 100%; padding: 10px; border-radius: 5px; border: 1px solid #334155; background: #0f172a; color: white; box-sizing: border-box; }
        button { background: #0284c7; color: white; padding: 10px 20px; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; margin-top: 15px; }
        button:hover { background: #0369a1; }
        .btn-delete { background: #ef4444; padding: 5px 10px; font-size: 14px; margin: 0; }
        .btn-delete:hover { background: #dc2626; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #334155; }
        iframe { width: 100%; height: 500px; border: 1px solid #38bdf8; border-radius: 8px; margin-top: 15px; }
    </style>
</head>
<body>
<div class="container">
    <h1>🚀 Termux Sandbox Manager</h1>

    <!-- MODIFIERS & CREATE FORM -->
    <div class="card">
        <h2>🛠️ Create / Clone New Linux Sandbox</h2>
        <form method="POST" action="/create">
            <label>Sandbox Name (e.g. clone1):</label>
            <input type="text" name="name" required placeholder="my-test-linux">

            <label>Base Distribution (Template):</label>
            <select name="distro">
                <option value="alpine">Alpine Linux (Super fast & light)</option>
                <option value="ubuntu">Ubuntu Linux</option>
            </select>

            <label>Port for Web Console:</label>
            <input type="number" name="port" value="7682" required>

            <label>Console Password (Username will be 'admin'):</label>
            <input type="password" name="password" value="secret123" required>

            <label>Pre-installed Packages Modifier (Optional):</label>
            <input type="text" name="packages" placeholder="e.g. git curl python3 nano">

            <button type="submit">⚡ Clone & Launch Sandbox</button>
        </form>
    </div>

    <!-- ACTIVE SANDBOXES TABLE -->
    <div class="card">
        <h2>📦 Active Cloned Sandboxes</h2>
        <table>
            <tr>
                <th>Name</th>
                <th>Base OS</th>
                <th>Port</th>
                <th>Console</th>
                <th>Action</th>
            </tr>
            {% for name, s in sandboxes.items() %}
            <tr>
                <td><b>{{ name }}</b></td>
                <td>{{ s.distro }}</td>
                <td>{{ s.port }}</td>
                <td><a href="http://{{ host }}:{{ s.port }}" target="_blank" style="color:#38bdf8;">Open Full Window</a></td>
                <td>
                    <form method="POST" action="/delete" style="display:inline;">
                        <input type="hidden" name="name" value="{{ name }}">
                        <button type="submit" class="btn-delete">Destroy</button>
                    </form>
                </td>
            </tr>
            {% else %}
            <tr><td colspan="5" style="color: #94a3b8;">No active sandboxes. Create one above!</td></tr>
            {% endfor %}
        </table>
    </div>

    <!-- EMBEDDED CONSOLE PREVIEW -->
    {% if active_port %}
    <div class="card">
        <h2>💻 Live Console View (Port: {{ active_port }})</h2>
        <p>Login with username <b>admin</b> and the password you configured.</p>
        <iframe src="http://{{ host }}:{{ active_port }}"></iframe>
    </div>
    {% endif %}
</div>
</body>
</html>
"""

@app.route('/')
def index():
    host = request.host.split(':')[0]
    active_port = request.args.get('active_port')
    return render_template_string(HTML_TEMPLATE, sandboxes=sandboxes, host=host, active_port=active_port)

@app.route('/create', methods=['POST'])
def create_sandbox():
    name = request.form['name'].strip()
    distro = request.form['distro']
    port = request.form['port'].strip()
    password = request.form['password'].strip()
    packages = request.form.get('packages', '').strip()

    base_rootfs = os.path.join(ROOTFS_DIR, distro)
    clone_rootfs = os.path.join(ROOTFS_DIR, name)
    base_conf = os.path.join(DISTRO_CONF_DIR, f"{distro}.sh")
    clone_conf = os.path.join(DISTRO_CONF_DIR, f"{name}.sh")

    # 1. Clone configuration & rootfs safely
    if not os.path.exists(clone_rootfs):
        subprocess.run(["cp", base_conf, clone_conf])
        subprocess.run(["cp", "-r", base_rootfs, clone_rootfs])

    # 2. Apply package modifiers inside the clone
    if packages:
        if distro == "alpine":
            pkg_cmd = f"apk update && apk add {packages}"
        else:
            pkg_cmd = f"apt update && apt install -y {packages}"
        subprocess.run(["proot-distro", "login", name, "--", "sh", "-c", pkg_cmd])

    # 3. Launch ttyd web console bound strictly to the clone
    auth_str = f"admin:{password}"
    proc = subprocess.Popen([
        "ttyd", "-p", port, "-c", auth_str,
        "proot-distro", "login", name
    ])

    sandboxes[name] = {"port": port, "distro": distro, "pid": proc.pid}
    return f"<script>window.location.href='/?active_port={port}';</script>"

@app.route('/delete', methods=['POST'])
def delete_sandbox():
    name = request.form['name']
    if name in sandboxes:
        # Kill the ttyd process
        try:
            os.kill(sandboxes[name]['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass
        del sandboxes[name]

    # Delete cloned folder and config
    clone_rootfs = os.path.join(ROOTFS_DIR, name)
    clone_conf = os.path.join(DISTRO_CONF_DIR, f"{name}.sh")
    subprocess.run(["rm", "-rf", clone_rootfs])
    subprocess.run(["rm", "-f", clone_conf])

    return "<script>window.location.href='/';</script>"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)