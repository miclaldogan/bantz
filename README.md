<p align="center">
  <img src=".github/assets/bantz-logo.svg" alt="Bantz Logo" width="200"/>
</p>

<h1 align="center">🤖 Bantz</h1>

<p align="center">
  <strong>Your Local Iron Man Jarvis - Voice Assistant for Linux</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#roadmap">Roadmap</a> •
  <a href="#license">License</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0--alpha-blue" alt="Version"/>
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python"/>
  <img src="https://img.shields.io/badge/platform-Linux-orange" alt="Platform"/>
  <img src="https://img.shields.io/badge/license-Proprietary-red" alt="License"/>
</p>

---

## Demo

```
👤 "Hey Bantz, bugünkü haberlerde ne var?"
🤖 "Sizin için şimdi arıyorum efendim..."
   [tarayıcıda arama yapar]
🤖 "Sonuçlarınız burada."
   [ekranda transparent panel açılır, haberler listelenir]
👤 "3. haberi aç"
🤖 "Açıyorum efendim."
👤 "Bu CEO olayını anlayamadım, anlat bakalım"
🤖 "Hemen arıyorum... Bu haberde Tesla CEO'su..."
```

## Features

### Voice Control
- **Wake Word Detection** - "Hey Bantz" ya da "Bantz" ile aktifleştir
- **Push-to-Talk** - Space tuşu ile konuş
- **Continuous Listening** - Konuşma modunda wake word gerekmez
- **Turkish ASR** - Faster-Whisper ile hızlı Türkçe tanıma

### Browser Automation
- **Firefox Integration** - Gerçek profil ile çalışır (login'ler korunur)
- **Site-Specific Actions** - Google, YouTube, GitHub, LinkedIn desteği
- **Page Scanning** - Sayfa içeriğini analiz et
- **Smart Navigation** - "geri dön", "yenile", "kapat"

### Desktop Control
- **App Launcher** - "btop aç", "terminal aç"
- **File Manager** - "indirilenler klasörünü aç"
- **Notifications** - "bildirim göster: mesaj"
- **Window Management** - wmctrl ile pencere kontrolü

### LLM Integration
- **Ollama Backend** - Yerel LLM (qwen2.5:3b-instruct)
- **Command Rewriting** - ASR hatalarını düzelt
- **Conversational AI** - Doğal dil anlama

### Overlay UI
- **PyQt5 Overlay** - Transparent bilgi paneli
- **State Indicators** - Listening, Thinking, Speaking durumları
- **Results Display** - Arama sonuçlarını göster

## Installation

### Prerequisites

```bash
# System dependencies
sudo apt install wmctrl xdotool libportaudio2 firefox

# Ollama (for LLM)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b-instruct
```

### Install Bantz

```bash
# Clone repository
git clone https://github.com/miclaldogan/bantz.git
cd bantz

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with all features
pip install -e ".[all]"

# Or install specific components
pip install -e ".[voice]"    # Voice recognition
pip install -e ".[browser]"  # Browser automation
pip install -e ".[ui]"       # Overlay UI
pip install -e ".[llm]"      # LLM integration
```

### Firefox Extension

```bash
# Load extension in Firefox
# 1. Go to about:debugging
# 2. Click "This Firefox"
# 3. Click "Load Temporary Add-on"
# 4. Select bantz-extension/manifest.json
```

## Usage

### Quick Start

```bash
# Start with voice (wake word mode)
bantz

# Start with voice (push-to-talk mode)
bantz --ptt

# Text mode (no voice)
bantz --text

# With overlay UI
bantz --overlay
```

### Voice Commands

| Category | Example Commands |
|----------|-----------------|
| **Web Search** | "google'da python ara", "youtube'da müzik ara" |
| **Navigation** | "google'ı aç", "github'a git" |
| **Browser** | "sayfayı tara", "geri dön", "yenile" |
| **Apps** | "btop aç", "terminal aç", "spotify aç" |
| **Files** | "indirilenler klasörünü aç", "dosyayı aç: ~/notes.txt" |
| **System** | "bildirim göster: Merhaba" |
| **AI Chat** | "chatgpt'ye sor: Python nedir?" |

### Configuration

```bash
# Policy configuration (allowed/denied commands)
vim config/policy.json

# Site-specific profiles
vim config/site_profiles.json
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        BANTZ                                 │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │  Voice  │  │ Browser │  │   LLM   │  │ Overlay │        │
│  │  Loop   │  │ Bridge  │  │ Client  │  │   UI    │        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
│       │            │            │            │              │
│       ▼            ▼            ▼            ▼              │
│  ┌─────────────────────────────────────────────────┐        │
│  │              Router / NLU Engine                │        │
│  │         (Intent Classification + Dispatch)       │        │
│  └─────────────────────────────────────────────────┘        │
│       │            │            │            │              │
│       ▼            ▼            ▼            ▼              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │   PC    │  │ Browser │  │  Daily  │  │ Remind  │        │
│  │ Skills  │  │ Skills  │  │ Skills  │  │  Skills │        │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘        │
└─────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
    ┌─────────┐         ┌───────────┐
    │ xdotool │         │  Firefox  │
    │ wmctrl  │         │ Extension │
    └─────────┘         └───────────┘
```

## Roadmap

### Phase 0 - Core (Current Focus)
- [x] Voice recognition (Whisper)
- [x] Wake word detection
- [x] Browser automation (Firefox)
- [x] Basic NLU
- [ ] 🔨 News briefing system
- [ ] 🔨 Page summarization
- [ ] 🔨 Jarvis-style UI panel
- [ ] 🔨 Multi-step task execution

### Phase 1 - Enhanced
- [ ] Coding agent (file operations)
- [ ] Conversational memory
- [ ] Query clarification
- [ ] Live action streaming

### Phase 2 - Advanced
- [ ] LLM-based NLU
- [ ] Advanced TTS (emotions)
- [ ] System integration (tray, shortcuts)
- [ ] Plugin system

See [Issues](https://github.com/miclaldogan/bantz/issues) for detailed roadmap.

## Development

```bash
# Run in development mode
bantz --debug --text

# Run tests
pytest tests/

# Check logs
tail -f bantz.log.jsonl | jq
```

## ⚠️ Known Limitations

- **X11 Only**: Desktop automation requires X11 (Wayland limited support)
- **Firefox Only**: Browser automation works with Firefox
- **Linux Only**: Designed for Linux desktop
- **Alpha Stage**: Expect bugs and breaking changes

## 🔒 Security

- All processing is **local** (no cloud APIs)
- Voice data never leaves your machine
- LLM runs locally via Ollama
- See [SECURITY.md](SECURITY.md) for vulnerability reporting

## 📄 License

**Proprietary - All Rights Reserved**

This software is provided for **viewing and educational purposes only**.

- ✅ View and study the code
- ❌ Copy, modify, or distribute
- ❌ Use in your own projects
- ❌ Commercial use

See [LICENSE](LICENSE) for full terms.

## Acknowledgments

- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) - ASR
- [OpenWakeWord](https://github.com/dscripka/openWakeWord) - Wake word
- [Piper](https://github.com/rhasspy/piper) - TTS
- [Ollama](https://ollama.com/) - Local LLM

---

<p align="center">
  <strong>Built with ❤️ by <a href="https://github.com/miclaldogan">@miclaldogan</a></strong>
</p>

<p align="center">
  <em>"Emrinize amadeyim, efendim." - Bantz</em>
</p>
