"""Bantz PC Skills - Desktop application control.

Provides safe, guardrailed control over desktop applications:
- Open/close applications (allowlist-based)
- Focus/switch windows
- Type text (with confirmation)
- Send keystrokes (with confirmation)

Uses Linux tools: xdg-open, gtk-launch, wmctrl, xdotool
"""
from __future__ import annotations

import subprocess
import shutil
import time
from typing import Optional, Tuple, List, Dict, Any


def _run(cmd: List[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ─────────────────────────────────────────────────────────────────
# Application Allowlist
# ─────────────────────────────────────────────────────────────────

# Apps that can be opened without confirmation
ALLOWED_APPS = {
    # Browsers
    "firefox": ["firefox"],
    "chrome": ["google-chrome", "chromium", "chromium-browser"],
    "brave": ["brave-browser", "brave"],
    
    # Communication
    "discord": ["discord"],
    "slack": ["slack"],
    "telegram": ["telegram-desktop", "telegram"],
    "whatsapp": ["whatsapp-nativefier", "whatsapp"],
    "teams": ["teams", "microsoft-teams"],
    "zoom": ["zoom", "zoom-client"],
    
    # Media
    "spotify": ["spotify"],
    "vlc": ["vlc"],
    "mpv": ["mpv"],
    
    # Productivity
    "vscode": ["code", "code-insiders"],
    "code": ["code", "code-insiders"],
    "obsidian": ["obsidian"],
    "notion": ["notion-app", "notion"],
    "libreoffice": ["libreoffice"],
    
    # File managers
    "files": ["nautilus", "nemo", "thunar", "dolphin", "pcmanfm"],
    "nautilus": ["nautilus"],
    "nemo": ["nemo"],
    
    # Terminals
    "terminal": ["gnome-terminal", "konsole", "xfce4-terminal", "alacritty", "kitty", "wezterm"],
    "gnome-terminal": ["gnome-terminal"],
    "konsole": ["konsole"],
    "alacritty": ["alacritty"],
    "kitty": ["kitty"],
    
    # System
    "settings": ["gnome-control-center", "systemsettings5", "xfce4-settings-manager"],
    "calculator": ["gnome-calculator", "kcalc", "galculator"],
    "screenshot": ["gnome-screenshot", "spectacle", "flameshot"],
    
    # Development
    "gitkraken": ["gitkraken"],
    "postman": ["postman"],
    "dbeaver": ["dbeaver"],
}

# Apps that require confirmation before opening
CONFIRM_APPS = {
    "htop": ["htop"],
    "btop": ["btop"],
    "system-monitor": ["gnome-system-monitor", "ksysguard"],
}

# Apps that are NEVER allowed
DENIED_APPS = {
    "sudo",
    "su",
    "pkexec",
    "gksudo",
    "kdesu",
    "rm",
    "dd",
    "mkfs",
    "fdisk",
    "parted",
    "gparted",
}


def _find_executable(app_name: str) -> Optional[str]:
    """Find the executable for an app from the allowlist."""
    app_lower = app_name.lower()
    
    # Check allowed apps
    if app_lower in ALLOWED_APPS:
        for cmd in ALLOWED_APPS[app_lower]:
            if shutil.which(cmd):
                return cmd
    
    # Check confirm apps
    if app_lower in CONFIRM_APPS:
        for cmd in CONFIRM_APPS[app_lower]:
            if shutil.which(cmd):
                return cmd
    
    # Direct executable check (only if in PATH and not denied)
    if app_lower not in DENIED_APPS and shutil.which(app_lower):
        return app_lower
    
    return None


def get_app_policy(app_name: str) -> str:
    """Get the policy decision for an app: 'allow', 'confirm', or 'deny'."""
    app_lower = app_name.lower()
    
    if app_lower in DENIED_APPS:
        return "deny"
    
    if app_lower in CONFIRM_APPS:
        return "confirm"
    
    if app_lower in ALLOWED_APPS:
        return "allow"
    
    # Unknown app - require confirmation
    return "confirm"


# ─────────────────────────────────────────────────────────────────
# App Control Functions
# ─────────────────────────────────────────────────────────────────

def open_app(app_name: str) -> Tuple[bool, str, Optional[str]]:
    """Open an application.
    
    Returns:
        (success, message, window_id or None)
    """
    app_lower = app_name.lower()
    
    # Check if denied
    if app_lower in DENIED_APPS:
        return False, f"❌ '{app_name}' güvenlik nedeniyle açılamaz.", None
    
    # Find executable
    executable = _find_executable(app_name)
    if not executable:
        return False, f"❌ '{app_name}' bulunamadı. Sistemde yüklü mü?", None
    
    try:
        # Launch the app (detached)
        subprocess.Popen(
            [executable],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Best-effort: wait briefly and try to find a window id
        window_id: Optional[str] = None
        if shutil.which("wmctrl"):
            for _ in range(5):
                time.sleep(0.2)
                ok, _, windows = list_windows()
                if ok:
                    for w in windows:
                        title = str(w.get("title", "")).lower()
                        if app_name.lower() in title or executable.lower() in title:
                            window_id = str(w.get("id"))
                            break
                if window_id:
                    break

        display_name = app_name.capitalize()
        return True, f"✅ {display_name} açıldı.", window_id
        
    except Exception as e:
        return False, f"❌ {app_name} açılamadı: {e}", None


def close_app(app_name: str) -> Tuple[bool, str]:
    """Close an application gracefully."""
    app_lower = app_name.lower()
    
    # Find the process name
    executable = _find_executable(app_name)
    if not executable:
        # Try direct name
        executable = app_lower
    
    try:
        # Use pkill with SIGTERM (graceful)
        result = subprocess.run(
            ["pkill", "-TERM", "-f", executable],
            capture_output=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return True, f"✅ {app_name.capitalize()} kapatıldı."
        else:
            return False, f"❌ {app_name.capitalize()} çalışmıyor veya kapatılamadı."
            
    except subprocess.TimeoutExpired:
        return False, f"❌ {app_name.capitalize()} kapatılırken zaman aşımı."
    except Exception as e:
        return False, f"❌ Hata: {e}"


def focus_app(app_name: str) -> Tuple[bool, str, Optional[str]]:
    """Bring an application window to focus."""
    if not shutil.which("wmctrl"):
        return False, "❌ wmctrl yüklü değil. `sudo apt install wmctrl` ile yükleyebilirsin.", None
    
    app_lower = app_name.lower()
    
    try:
        # Try to find and focus window by class/name
        result = subprocess.run(
            ["wmctrl", "-a", app_lower],
            capture_output=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Try to find the active window id (best-effort)
            _, _, windows = list_windows()
            for w in windows:
                if app_lower in str(w.get("title", "")).lower():
                    return True, f"✅ {app_name.capitalize()} öne alındı.", str(w.get("id"))
            return True, f"✅ {app_name.capitalize()} öne alındı.", None
        else:
            # Try with executable name
            executable = _find_executable(app_name)
            if executable:
                result = subprocess.run(
                    ["wmctrl", "-a", executable],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    _, _, windows = list_windows()
                    for w in windows:
                        title = str(w.get("title", "")).lower()
                        if app_lower in title or executable.lower() in title:
                            return True, f"✅ {app_name.capitalize()} öne alındı.", str(w.get("id"))
                    return True, f"✅ {app_name.capitalize()} öne alındı.", None
            
            return False, f"❌ {app_name.capitalize()} penceresi bulunamadı.", None
            
    except Exception as e:
        return False, f"❌ Hata: {e}", None


def list_windows() -> Tuple[bool, str, List[Dict[str, str]]]:
    """List all open windows."""
    if not shutil.which("wmctrl"):
        return False, "❌ wmctrl yüklü değil.", []
    
    try:
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return False, "❌ Pencereler listelenemedi.", []
        
        windows = []
        lines = result.stdout.strip().split('\n')
        
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(None, 3)
            if len(parts) >= 4:
                windows.append({
                    "id": parts[0],
                    "desktop": parts[1],
                    "host": parts[2],
                    "title": parts[3],
                })
        
        if not windows:
            return True, "📭 Açık pencere yok.", []
        
        lines = ["📋 Açık pencereler:"]
        for i, w in enumerate(windows, 1):
            title = w['title'][:40] + "..." if len(w['title']) > 40 else w['title']
            lines.append(f"  [{i}] {title}")
        
        return True, "\n".join(lines), windows
        
    except Exception as e:
        return False, f"❌ Hata: {e}", []


def type_text(text: str, press_enter: bool = False, window_id: Optional[str] = None) -> Tuple[bool, str]:
    """Type text using xdotool. Optionally target a specific window."""
    if not shutil.which("xdotool"):
        return False, "❌ xdotool yüklü değil. `sudo apt install xdotool` ile yükleyebilirsin."
    
    try:
        # Focus target window if specified
        if window_id:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                timeout=5
            )
        
        # Type the text
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", text],
            timeout=10
        )
        
        if press_enter:
            subprocess.run(
                ["xdotool", "key", "Return"],
                timeout=5
            )
            return True, f"✅ Yazıldı ve gönderildi: \"{text[:30]}{'...' if len(text) > 30 else ''}\""
        
        return True, f"✅ Yazıldı: \"{text[:30]}{'...' if len(text) > 30 else ''}\""
        
    except subprocess.TimeoutExpired:
        return False, "❌ Yazma işlemi zaman aşımına uğradı."
    except Exception as e:
        return False, f"❌ Hata: {e}"


def send_key(key: str, window_id: Optional[str] = None) -> Tuple[bool, str]:
    """Send a key press using xdotool. Optionally target a specific window."""
    if not shutil.which("xdotool"):
        return False, "❌ xdotool yüklü değil."
    
    # Map common key names
    key_map = {
        "enter": "Return",
        "gönder": "Return",
        "tab": "Tab",
        "escape": "Escape",
        "esc": "Escape",
        "backspace": "BackSpace",
        "delete": "Delete",
        "space": "space",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
    }
    
    mapped_key = key_map.get(key.lower(), key)
    
    try:
        # Focus target window if specified
        if window_id:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                timeout=5
            )
        
        subprocess.run(
            ["xdotool", "key", mapped_key],
            timeout=5
        )
        return True, f"✅ '{key}' tuşuna basıldı."
        
    except Exception as e:
        return False, f"❌ Hata: {e}"


# ─────────────────────────────────────────────────────────────────
# Advanced Mouse / Keyboard / Clipboard
# ─────────────────────────────────────────────────────────────────

def move_mouse(x: int, y: int, duration_ms: int = 0) -> Tuple[bool, str]:
    """Move mouse to absolute screen coordinates (x,y)."""
    if not shutil.which("xdotool"):
        return False, "❌ xdotool yüklü değil. `sudo apt install xdotool` ile yükleyebilirsin."

    try:
        if duration_ms and duration_ms > 0:
            # Simple smooth-ish movement by stepping
            steps = max(5, min(60, duration_ms // 20))
            # Use xdotool mousemove --sync which jumps; we emulate stepping by querying current pos
            cur = _run(["xdotool", "getmouselocation", "--shell"], timeout=2)
            cur_x, cur_y = None, None
            if cur.returncode == 0:
                for line in cur.stdout.splitlines():
                    if line.startswith("X="):
                        cur_x = int(line.split("=", 1)[1])
                    if line.startswith("Y="):
                        cur_y = int(line.split("=", 1)[1])
            if cur_x is None or cur_y is None:
                _run(["xdotool", "mousemove", str(int(x)), str(int(y))], timeout=5)
                return True, f"✅ İmleci ({x}, {y}) konumuna götürdüm."

            for i in range(1, steps + 1):
                ix = int(cur_x + (x - cur_x) * i / steps)
                iy = int(cur_y + (y - cur_y) * i / steps)
                _run(["xdotool", "mousemove", str(ix), str(iy)], timeout=2)
                time.sleep(duration_ms / 1000.0 / steps)
        else:
            _run(["xdotool", "mousemove", str(int(x)), str(int(y))], timeout=5)
        return True, f"✅ İmleci ({x}, {y}) konumuna götürdüm."
    except Exception as e:
        return False, f"❌ Hata: {e}"


def click_mouse(
    button: str = "left",
    x: Optional[int] = None,
    y: Optional[int] = None,
    double: bool = False,
) -> Tuple[bool, str]:
    """Click mouse. Optionally move to (x,y) first."""
    if not shutil.which("xdotool"):
        return False, "❌ xdotool yüklü değil. `sudo apt install xdotool` ile yükleyebilirsin."

    button_map = {"left": "1", "middle": "2", "right": "3"}
    btn = button_map.get(button.lower(), "1")

    try:
        if x is not None and y is not None:
            _run(["xdotool", "mousemove", str(int(x)), str(int(y))], timeout=5)
        if double:
            _run(["xdotool", "click", "--repeat", "2", "--delay", "80", btn], timeout=5)
            return True, "✅ Çift tık yaptım."
        _run(["xdotool", "click", btn], timeout=5)
        return True, "✅ Tıkladım."
    except Exception as e:
        return False, f"❌ Hata: {e}"


def scroll_mouse(direction: str = "down", amount: int = 3) -> Tuple[bool, str]:
    """Scroll mouse wheel up/down by repeating xdotool click 4/5."""
    if not shutil.which("xdotool"):
        return False, "❌ xdotool yüklü değil."

    direction = direction.lower().strip()
    amount = max(1, min(int(amount), 50))
    btn = "5" if direction in {"down", "aşağı", "asagi"} else "4"
    try:
        _run(["xdotool", "click", "--repeat", str(amount), btn], timeout=5)
        return True, f"✅ Kaydırdım ({direction}, {amount})."
    except Exception as e:
        return False, f"❌ Hata: {e}"


def hotkey(combo: str) -> Tuple[bool, str]:
    """Send a hotkey combination using xdotool, e.g. 'ctrl+alt+t'."""
    if not shutil.which("xdotool"):
        return False, "❌ xdotool yüklü değil."
    combo = combo.strip()
    if not combo:
        return False, "❌ Kısayol boş olamaz."
    try:
        _run(["xdotool", "key", "--clearmodifiers", combo], timeout=5)
        return True, f"✅ Kısayol gönderildi: {combo}"
    except Exception as e:
        return False, f"❌ Hata: {e}"


def clipboard_set(text: str) -> Tuple[bool, str]:
    """Set clipboard text (prefers pyperclip, falls back to xclip)."""
    text = str(text)
    try:
        try:
            import pyperclip  # type: ignore

            pyperclip.copy(text)
            return True, "✅ Panoya kopyaladım."
        except Exception:
            pass

        if shutil.which("xclip"):
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            assert p.stdin is not None
            p.stdin.write(text.encode("utf-8"))
            p.stdin.close()
            p.wait(timeout=2)
            return True, "✅ Panoya kopyaladım."
        return False, "❌ Clipboard için pyperclip veya xclip gerekli."
    except Exception as e:
        return False, f"❌ Hata: {e}"


def clipboard_get() -> Tuple[bool, str, str]:
    """Get clipboard text (prefers pyperclip, falls back to xclip)."""
    try:
        try:
            import pyperclip  # type: ignore

            val = pyperclip.paste() or ""
            return True, "✅ Panodaki metin:", str(val)
        except Exception:
            pass

        if shutil.which("xclip"):
            r = _run(["xclip", "-selection", "clipboard", "-o"], timeout=2)
            if r.returncode == 0:
                return True, "✅ Panodaki metin:", r.stdout
            return False, "❌ Panodan okunamadı.", ""

        return False, "❌ Clipboard için pyperclip veya xclip gerekli.", ""
    except Exception as e:
        return False, f"❌ Hata: {e}", ""


# ─────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────

def check_tools() -> Dict[str, bool]:
    """Check which tools are available."""
    return {
        "wmctrl": shutil.which("wmctrl") is not None,
        "xdotool": shutil.which("xdotool") is not None,
        "xdg-open": shutil.which("xdg-open") is not None,
    }
