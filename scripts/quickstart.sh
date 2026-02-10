#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Bantz Quickstart — sıfırdan çalışır hale getirme (Issue #665)
# Kullanım:  bash scripts/quickstart.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ ${NC} $*"; }
ok()    { echo -e "${GREEN}✅${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠️ ${NC} $*"; }
fail()  { echo -e "${RED}❌${NC} $*"; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       🚀 BANTZ Quickstart Kurulum        ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Python kontrolü ──────────────────────────────────────
info "Python sürümü kontrol ediliyor..."
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
    fail "Python3 bulunamadı. Lütfen yükleyin: sudo apt install python3 python3-venv"
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    fail "Python 3.10+ gerekli, mevcut: $PY_VER"
fi
ok "Python $PY_VER"

# ── 2. Sanal ortam ──────────────────────────────────────────
info "Sanal ortam hazırlanıyor..."
if [ ! -d ".venv" ]; then
    "$PYTHON" -m venv .venv
    ok "Yeni .venv oluşturuldu"
else
    ok "Mevcut .venv kullanılıyor"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# ── 3. Bağımlılıklar ────────────────────────────────────────
info "Bağımlılıklar yükleniyor..."
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]" 2>/dev/null || pip install --quiet -e .
ok "Pip paketleri yüklendi"

# ── 4. Env dosyası ───────────────────────────────────────────
ENV_DIR="$HOME/.config/bantz"
ENV_FILE="$ENV_DIR/env"

if [ ! -f "$ENV_FILE" ]; then
    info "Env dosyası oluşturuluyor: $ENV_FILE"
    mkdir -p "$ENV_DIR"
    cp config/bantz-env.example "$ENV_FILE"
    ok "Env dosyası kopyalandı → $ENV_FILE"
    warn "Lütfen düzenleyin: nano $ENV_FILE"
else
    ok "Env dosyası mevcut: $ENV_FILE"
fi

# ── 5. vLLM kontrolü ────────────────────────────────────────
VLLM_URL="${BANTZ_VLLM_URL:-http://localhost:8001}"
info "vLLM kontrol ediliyor ($VLLM_URL)..."

if curl -fsS "${VLLM_URL}/v1/models" &>/dev/null; then
    ok "vLLM çalışıyor"
else
    warn "vLLM erişilebilir değil: $VLLM_URL"
    echo ""
    echo "   vLLM başlatmak için:"
    echo "   1) Docker: docker compose up -d"
    echo "   2) Manuel:  vllm serve Qwen/Qwen2.5-3B-Instruct-AWQ --port 8001"
    echo ""
fi

# ── 6. Dizin yapısı ─────────────────────────────────────────
info "Dizin yapısı kontrol ediliyor..."
mkdir -p artifacts/{logs,results,tmp}
ok "artifacts/ dizini hazır"

# ── 7. Test ──────────────────────────────────────────────────
info "Hızlı test (smoke)..."
if python -m pytest tests/ -q -x --co -q 2>/dev/null | tail -1 | grep -q "test"; then
    ok "Test koleksiyonu başarılı"
else
    warn "Testler toplanamadı — bağımlılık eksik olabilir"
fi

# ── 8. Sonuç ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          ✅ BANTZ Hazır!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "Kullanım:"
echo "  source .venv/bin/activate"
echo "  python -m bantz              # Terminal modu"
echo "  python -m bantz --voice      # Sesli mod"
echo "  python -m bantz --wake       # Wake word modu"
echo "  python scripts/demo.py       # Demo çalıştır"
echo ""
echo "Dokümantasyon:"
echo "  docs/quickstart.md           # Hızlı başlangıç"
echo "  docs/architecture.md         # Mimari"
echo "  docs/env-reference.md        # Ortam değişkenleri"
echo "  docs/tool-catalog.md         # Tool kataloğu"
echo ""
