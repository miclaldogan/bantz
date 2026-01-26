#!/bin/bash
# Bantz systemd service setup script

set -e

BANTZ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_FILE="$BANTZ_DIR/config/bantz.service"
USER_SERVICE_DIR="$HOME/.config/systemd/user"

echo "🚀 Bantz Service Setup"
echo "   Bantz directory: $BANTZ_DIR"
echo ""

case "${1:-help}" in
    install)
        echo "📦 Installing Bantz service..."
        
        # Create user systemd directory
        mkdir -p "$USER_SERVICE_DIR"
        
        # Update service file with correct paths
        sed "s|/home/iclaldogan/Desktop/Bantz|$BANTZ_DIR|g" "$SERVICE_FILE" > "$USER_SERVICE_DIR/bantz.service"
        
        # Reload systemd
        systemctl --user daemon-reload
        
        echo "✅ Service installed!"
        echo ""
        echo "Commands:"
        echo "  Start:   systemctl --user start bantz"
        echo "  Stop:    systemctl --user stop bantz"
        echo "  Status:  systemctl --user status bantz"
        echo "  Enable:  systemctl --user enable bantz  (autostart on login)"
        echo "  Logs:    journalctl --user -u bantz -f"
        ;;
    
    uninstall)
        echo "🗑️  Uninstalling Bantz service..."
        
        # Stop and disable if running
        systemctl --user stop bantz 2>/dev/null || true
        systemctl --user disable bantz 2>/dev/null || true
        
        # Remove service file
        rm -f "$USER_SERVICE_DIR/bantz.service"
        
        # Reload systemd
        systemctl --user daemon-reload
        
        echo "✅ Service uninstalled!"
        ;;
    
    start)
        echo "▶️  Starting Bantz service..."
        systemctl --user start bantz
        systemctl --user status bantz --no-pager
        ;;
    
    stop)
        echo "⏹️  Stopping Bantz service..."
        systemctl --user stop bantz
        echo "✅ Stopped."
        ;;
    
    restart)
        echo "🔄 Restarting Bantz service..."
        systemctl --user restart bantz
        systemctl --user status bantz --no-pager
        ;;
    
    status)
        systemctl --user status bantz --no-pager || true
        ;;
    
    logs)
        journalctl --user -u bantz -f
        ;;
    
    enable)
        echo "🔧 Enabling Bantz autostart..."
        systemctl --user enable bantz
        echo "✅ Bantz will start automatically on login."
        ;;
    
    disable)
        echo "🔧 Disabling Bantz autostart..."
        systemctl --user disable bantz
        echo "✅ Autostart disabled."
        ;;
    
    help|*)
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  install    Install Bantz as a user service"
        echo "  uninstall  Remove Bantz service"
        echo "  start      Start Bantz service"
        echo "  stop       Stop Bantz service"
        echo "  restart    Restart Bantz service"
        echo "  status     Show service status"
        echo "  logs       Follow service logs"
        echo "  enable     Enable autostart on login"
        echo "  disable    Disable autostart"
        echo "  help       Show this help"
        ;;
esac
