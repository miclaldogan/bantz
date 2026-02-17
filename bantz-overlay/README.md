# Bantz Overlay HUD

Transparent, always-on-top desktop overlay for the Bantz AI assistant.

## Quick Start

```bash
cd bantz-overlay
npm install
npm run dev    # development mode (DevTools open)
npm start      # production mode
```

## Architecture

```
bantz-overlay/
├── src/
│   ├── main/
│   │   ├── main.js       # Electron main process — transparent window
│   │   └── preload.js    # Context bridge: renderer ↔ main
│   └── renderer/
│       ├── index.html    # Overlay DOM structure
│       ├── styles.css    # Base styles, glass morphism, CRT
│       └── renderer.js   # UI logic, message routing
└── package.json
```

## Features

- **Transparent frameless window** — full-screen, always-on-top
- **Click-through** — transparent areas pass clicks to desktop
- **Interactive zones** — HUD panel captures mouse events
- **Toggle** — `Super+Shift+B` to show/hide
- **X11 + Wayland** — auto-detects display server
- **IPC-ready** — preload bridge for daemon communication

## Display Server Notes

### X11
Transparency works out of the box with compositing (picom, compton, etc.).

### Wayland
Electron ≥28 uses Ozone platform. The app auto-sets `--ozone-platform=wayland`.
Some compositors may not support `alwaysOnTop` for non-shell surfaces.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Super+Shift+B` | Toggle overlay visibility |

## Related Issues

- #1397 (Epic)
- #1398 (This — Electron window scaffold)
- #1399 (IPC Unix socket client)
- #1400 (Base CSS, glass morphism)
