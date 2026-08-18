#!/usr/bin/env python3
"""
OmniOne Tray Application
Unified system tray controller for OmniRoute server + Claude Code integration.
Replaces all batch files with a single, reliable tray app.
"""

import sys
import os
import ctypes
import subprocess
import threading
import time
import json
import requests
from pathlib import Path
from typing import Optional, Tuple

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pystray", "pillow", "requests"])
    import pystray
    from PIL import Image, ImageDraw, ImageFont

# ─── Configuration ───
OMNIROUTE_VERSION = "3.8.49"
HEALTH_URL = "http://localhost:20128/api/monitoring/health"
# Users can set OMNIONE_WORKSPACE_ROOT to any folder containing their projects.
# The default keeps the app portable between Windows accounts.
WORKSPACE_ROOT = Path(
    os.environ.get("OMNIONE_WORKSPACE_ROOT", str(Path.home() / "Workspace"))
).expanduser()
OMNIROUTE_DIR = Path.home() / ".omniroute"
OMNIROUTE_LOGS = OMNIROUTE_DIR / "logs"
OMNIROUTE_PID_FILE = OMNIROUTE_DIR / "server" / ".pid"
OMNIROUTE_CACHE = OMNIROUTE_DIR / ".omnione-cli-path"

# Cached CLI path
_cached_cli_path: Optional[str] = None


def acquire_single_instance() -> bool:
    """Prevent duplicate OmniOne controllers from running on Windows."""
    if os.name != "nt":
        return True
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\OmniOneTrayController")
    if not mutex:
        return True
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    return True


def show_loading(stop_event: threading.Event) -> None:
    """Keep the console informative while the tray icon is being prepared."""
    frames = "|/-\\"
    index = 0
    while not stop_event.is_set():
        print(f"\r[OmniOne] Carregando {frames[index % len(frames)]}", end="", flush=True)
        index += 1
        stop_event.wait(0.15)


# ─── Utility Functions ───

def get_omniroute_cmd() -> str:
    """Resolve the omniroute command (same logic as batch files)."""
    global _cached_cli_path

    # 1. Check if 'omniroute' is in PATH
    try:
        result = subprocess.run(["where", "omniroute"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            _cached_cli_path = "omniroute"
            return "omniroute"
    except Exception:
        pass

    # 2. Check cached path
    if OMNIROUTE_CACHE.exists():
        try:
            cached = OMNIROUTE_CACHE.read_text(encoding="utf-8").strip()
            if cached and Path(cached).exists():
                _cached_cli_path = cached
                return f'node "{cached}"'
        except Exception:
            pass

    # 3. Find in npm cache
    try:
        localappdata = os.environ.get("LOCALAPPDATA", "")
        matches = list(Path(localappdata).glob("npm-cache/_npx/*/node_modules/omniroute/bin/omniroute.mjs"))
        if matches:
            _cached_cli_path = str(matches[0])
            OMNIROUTE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            OMNIROUTE_CACHE.write_text(_cached_cli_path, encoding="utf-8")
            return f'node "{_cached_cli_path}"'
    except Exception:
        pass

    # 4. Fallback to npx
    return f"npx --yes -p omniroute@{OMNIROUTE_VERSION} omniroute"


def run_cmd(cmd: str, cwd: Optional[Path] = None, timeout: int = 30) -> Tuple[int, str, str]:
    """Run command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


def check_server_health() -> bool:
    """Check if OmniRoute server is responding."""
    try:
        resp = requests.get(HEALTH_URL, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def get_server_pid() -> Optional[int]:
    """Get PID from OmniRoute PID file."""
    if OMNIROUTE_PID_FILE.exists():
        try:
            return int(OMNIROUTE_PID_FILE.read_text().strip())
        except Exception:
            pass
    return None


def start_server() -> Tuple[bool, str]:
    """Start OmniRoute server in daemon mode."""
    OMNIROUTE_LOGS.mkdir(parents=True, exist_ok=True)
    log_file = OMNIROUTE_LOGS / "serve-launch.log"

    cmd = get_omniroute_cmd()
    full_cmd = f'{cmd} serve --daemon > "{log_file}" 2>&1'

    # Run in background
    try:
        subprocess.Popen(full_cmd, shell=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    except Exception as e:
        return False, f"Failed to start process: {e}"

    # Wait for server to become healthy
    for _ in range(60):  # 120 seconds max
        time.sleep(2)
        if check_server_health():
            return True, "Server started successfully"

    return False, "Server did not respond in time. Check logs at: " + str(log_file)


def stop_server() -> Tuple[bool, str]:
    """Stop OmniRoute server, handling both daemon and foreground supervisor cases."""
    cmd = get_omniroute_cmd()

    # 1. Graceful stop
    code, out, err = run_cmd(f"{cmd} stop", timeout=15)

    # Wait a bit
    time.sleep(2)

    # 2. Check if server is actually stopped
    if not check_server_health():
        return True, "Server stopped successfully"

    # 3. Server came back - likely a foreground supervisor. Kill the process tree.
    try:
        # Find processes with 'omniroute' and 'serve' in command line
        ps_cmd = (
            'powershell -NoProfile -Command '
            '"$servers = @(Get-CimInstance Win32_Process | Where-Object { '
            '$_.CommandLine -and $_.CommandLine -match \'omniroute\' -and $_.CommandLine -match \'\\bserve\\b\' }); '
            'if ($servers.Count -eq 0) { exit 1 }; '
            'foreach ($p in $servers) { '
            'Write-Host (\'[..] Killing PID \' + $p.ProcessId + \' (\' + $p.Name + \')\'); '
            'taskkill /PID $p.ProcessId /T /F 2>&1 | Out-Null }; exit 0"'
        )
        code, out, err = run_cmd(ps_cmd, timeout=15)
        time.sleep(2)

        if not check_server_health():
            return True, "Server stopped (killed supervisor process tree)"

        return False, "Server still responding after kill attempt"
    except Exception as e:
        return False, f"Error killing supervisor: {e}"


def launch_claude_code(workspace: Path) -> bool:
    """Launch Claude Code connected to OmniRoute in its own visible terminal."""
    try:
        workspace = workspace.resolve(strict=True)
    except (OSError, RuntimeError):
        print(f"Workspace inválido ou inexistente: {workspace}")
        return False
    if not workspace.is_dir():
        print(f"Workspace não é uma pasta: {workspace}")
        return False

    cmd = get_omniroute_cmd()
    full_cmd = f'{cmd} launch -- --model auto/best-free'
    launcher = OMNIROUTE_LOGS / "omnione-launch-claude.cmd"

    try:
        OMNIROUTE_LOGS.mkdir(parents=True, exist_ok=True)
        launcher.write_text(
            "@echo off\n"
            "title OmniOne - Claude Code\n"
            "echo [OmniOne] Abrindo Claude Code...\n"
            f"call {full_cmd}\n"
            "echo.\n"
            "echo [OmniOne] Claude Code foi encerrado. Codigo: %errorlevel%\n"
            "pause\n",
            encoding="utf-8",
        )
        subprocess.Popen(
            ["cmd.exe", "/d", "/k", str(launcher)],
            cwd=str(workspace),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    except Exception as e:
        print(f"Failed to launch Claude Code: {e}")
        return False


def get_workspaces() -> list:
    """Get list of workspace directories."""
    if not WORKSPACE_ROOT.exists():
        return []
    try:
        return sorted((d for d in WORKSPACE_ROOT.iterdir() if d.is_dir()), key=lambda d: d.name.lower())
    except OSError:
        return []


# ─── Tray Icon Creation ───

def create_tray_icon(status: str = "unknown") -> Image.Image:
    """Create tray icon image based on status."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Colors based on status
    if status == "running":
        color = (0, 200, 0, 255)      # Green
        inner_color = (0, 255, 0, 180)
    elif status == "starting":
        color = (255, 165, 0, 255)    # Orange
        inner_color = (255, 200, 0, 180)
    elif status == "stopped":
        color = (200, 0, 0, 255)      # Red
        inner_color = (255, 0, 0, 180)
    else:
        color = (128, 128, 128, 255)  # Gray
        inner_color = (180, 180, 180, 180)

    # Draw outer circle
    margin = 4
    draw.ellipse([margin, margin, size-margin, size-margin], fill=color)

    # Draw inner circle
    inner_margin = 16
    draw.ellipse([inner_margin, inner_margin, size-inner_margin, size-inner_margin], fill=inner_color)

    # Draw "O" in center
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()

    text = "O"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 2
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    return img


# ─── Tray Application Class ───

class OmniOneTrayApp:
    def __init__(self):
        self.icon: Optional[pystray.Icon] = None
        self.server_status = "unknown"
        self.update_thread: Optional[threading.Thread] = None
        self.running = False

    def update_status(self):
        """Background thread to update server status and tray icon."""
        while self.running:
            # Do not overwrite the explicit "starting" state while the
            # background start/restart operation is waiting for health checks.
            if self.server_status == "starting":
                time.sleep(1)
                continue
            healthy = check_server_health()
            new_status = "running" if healthy else "stopped"

            if new_status != self.server_status:
                self.server_status = new_status
                if self.icon:
                    self.icon.icon = create_tray_icon(new_status)
                    self.update_menu()

            time.sleep(5)

    def update_menu(self):
        """Update the tray menu based on current status."""
        if not self.icon:
            return

        status_text = {
            "running": "🟢 OmniOne: ATIVO",
            "stopped": "🔴 OmniOne: PARADO",
            "starting": "🟡 OmniOne: INICIANDO...",
            "unknown": "⚪ OmniOne: DESCONHECIDO",
        }.get(self.server_status, "⚪ OmniOne: DESCONHECIDO")

        workspaces = get_workspaces()
        workspace_items = []

        def make_workspace_action(workspace: Path):
            def action(icon, item):
                self.on_launch_claude(workspace)
            return action

        for ws in workspaces:
            workspace_items.append(
                pystray.MenuItem(
                    f"📁 {ws.name}",
                    make_workspace_action(ws),
                    enabled=self.server_status == "running"
                )
            )

        if not workspace_items:
            workspace_items = [pystray.MenuItem("No workspaces found", None, enabled=False)]

        menu = pystray.Menu(
            pystray.MenuItem(status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "▶ Start Server" if self.server_status == "stopped" else "⏳ Starting..." if self.server_status == "starting" else "🔄 Restart Server",
                self.on_start_server,
                enabled=self.server_status != "starting"
            ),
            pystray.MenuItem(
                "■ Stop Server",
                self.on_stop_server,
                enabled=self.server_status == "running"
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Workspaces", pystray.Menu(*workspace_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📋 View Logs", self.on_view_logs),
            pystray.MenuItem("🌐 Open Dashboard", self.on_open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Exit", self.on_exit)
        )
        self.icon.menu = menu

    def on_start_server(self, icon=None, item=None):
        if self.server_status == "starting":
            return

        was_running = self.server_status == "running"
        self.server_status = "starting"
        self.icon.icon = create_tray_icon("starting")
        self.update_menu()

        def do_start():
            if was_running:
                stopped, stop_message = stop_server()
                if not stopped:
                    success, msg = False, stop_message
                else:
                    success, msg = start_server()
            else:
                success, msg = start_server()
            if success:
                self.server_status = "running"
            else:
                self.server_status = "stopped"
            self.icon.icon = create_tray_icon(self.server_status)
            self.update_menu()
            # Show notification
            if self.icon:
                self.icon.notify(msg, "OmniOne")

        threading.Thread(target=do_start, daemon=True).start()

    def on_stop_server(self, icon=None, item=None):
        def do_stop():
            self.icon.notify("Encerrando o servidor...", "OmniOne")
            success, msg = stop_server()
            if success:
                self.server_status = "stopped"
            else:
                self.server_status = "running"  # Still running
            self.icon.icon = create_tray_icon(self.server_status)
            self.update_menu()
            self.icon.notify(msg, "OmniOne")

        threading.Thread(target=do_stop, daemon=True).start()

    def on_launch_claude(self, workspace: Path):
        if self.server_status != "running":
            self.icon.notify("O servidor precisa estar ativo para abrir o Claude Code", "OmniOne")
            return

        def do_launch():
            success = launch_claude_code(workspace)
            if success:
                self.icon.notify(f"Claude Code aberto em {workspace.name}", "OmniOne")
            else:
                self.icon.notify("Não foi possível abrir o Claude Code", "OmniOne")

        threading.Thread(target=do_launch, daemon=True).start()

    def on_view_logs(self, icon=None, item=None):
        log_file = OMNIROUTE_LOGS / "serve-launch.log"
        if log_file.exists():
            try:
                os.startfile(str(log_file))
            except Exception:
                subprocess.Popen(["notepad.exe", str(log_file)])
        else:
            self.icon.notify("Nenhum arquivo de log encontrado", "OmniOne")

    def on_open_dashboard(self, icon=None, item=None):
        try:
            subprocess.Popen(f"{get_omniroute_cmd()} dashboard", shell=True)
        except Exception:
            import webbrowser
            webbrowser.open("http://localhost:20128")

    def on_exit(self, icon=None, item=None):
        self.running = False
        if self.icon:
            self.icon.stop()

    def run(self):
        self.running = True
        loading_done = threading.Event()
        loading_thread = threading.Thread(target=show_loading, args=(loading_done,), daemon=True)
        loading_thread.start()

        # Initial status check
        self.server_status = "running" if check_server_health() else "stopped"

        # Create icon
        self.icon = pystray.Icon(
            "OmniOne",
            create_tray_icon(self.server_status),
            "OmniOne Controller",
            menu=pystray.Menu()  # Will be set in update_menu
        )

        # Start status update thread
        self.update_thread = threading.Thread(target=self.update_status, daemon=True)
        self.update_thread.start()

        # Initial menu setup
        self.update_menu()
        loading_done.set()
        loading_thread.join(timeout=1)
        print(f"\r[OmniOne] Pronto. Servidor: {self.server_status.upper()}.")
        print("O OmniOne permanece aberto nesta janela e na bandeja do sistema.")
        print("Feche pelo menu 'Sair' da bandeja ou com Ctrl+C.")

        # Run the icon (blocks until exit)
        self.icon.run()


def main():
    if not acquire_single_instance():
        print("O OmniOne já está aberto. Procure o ícone na bandeja do sistema.")
        time.sleep(3)
        return
    app = OmniOneTrayApp()
    app.run()


if __name__ == "__main__":
    main()
