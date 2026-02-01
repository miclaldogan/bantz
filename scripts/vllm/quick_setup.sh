#!/usr/bin/env bash
# Quick vLLM Setup Script
# Tek komutla vLLM'i kur ve test et

set -e

echo "🚀 vLLM Hızlı Kurulum"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Virtual environment kontrolü
if [ ! -d ".venv" ]; then
    echo "📦 Virtual environment oluşturuluyor..."
    python3.10 -m venv .venv
fi

# 2. Aktivasyon
source .venv/bin/activate

# 3. vLLM kurulumu
echo ""
echo "📥 vLLM kuruluyor... (Bu birkaç dakika sürebilir)"
pip install --upgrade pip setuptools wheel
pip uninstall -y vllm vllm-flash-attn || true
pip install vllm==0.6.6 --no-cache-dir
pip install "fsspec<=2025.10.0,>=2023.1.0"
true
# 4. Dependency fix
pip install --force-reinstall nvidia-cuda-nvrtc-cu12==12.4.127 nvidia-nvjitlink-cu12==12.4.127

# 5. Kurulum doğrulama
echo ""
echo "✅ Kurulum Doğrulanıyor..."
python -c "import vllm; print(f'vLLM {vllm.__version__} kuruldu')" || {
    echo "⚠️  vLLM import edilemedi, ancak kurulum tamamlandı"
    echo "   Sistemi yeniden başlatın: sudo reboot"
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Kurulum Tamamlandı!"
echo ""
echo "📝 Sonraki Adımlar:"
echo "   1. Sistemi yeniden başlat: sudo reboot"
echo "   2. Sunucuları başlat: ./scripts/vllm/start_dual.sh"
echo "   3. Test et: python scripts/health_check_vllm.py --all"
echo ""
echo "📖 Detaylı bilgi: docs/setup/vllm.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
