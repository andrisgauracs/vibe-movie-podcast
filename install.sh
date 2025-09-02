bash -lc '
set -euo pipefail

echo "[1/8] apt packages"
sudo apt-get update -y
sudo apt-get install -y ffmpeg git build-essential ninja-build

echo "[2/8] install uv if missing"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  . ~/.bashrc || true
fi

echo "[3/8] install project deps"
uv pip install -r requirements.txt

echo "[4/8] clone VibeVoice if needed"
if [ ! -d VibeVoice ]; then
  git clone https://github.com/microsoft/VibeVoice.git
fi

echo "[5/8] install VibeVoice editable"
uv pip install -e ./VibeVoice

echo "[6/8] choose default VibeVoice model"
read -r -p "Use VibeVoice model: [L]arge, [S]mall-1.5B, [B]oth? [L/s/b]: " CHOICE
CHOICE=${CHOICE:-L}
case "$CHOICE" in
  L|l)
    VVMODEL="microsoft/VibeVoice-Large"
    VVFALLBACK="microsoft/VibeVoice-1.5B"
    ;;
  S|s)
    VVMODEL="microsoft/VibeVoice-1.5B"
    VVFALLBACK="microsoft/VibeVoice-Large"
    ;;
  B|b)
    VVMODEL="microsoft/VibeVoice-Large"
    VVFALLBACK="microsoft/VibeVoice-1.5B"
    ;;
  *)
    VVMODEL="microsoft/VibeVoice-Large"
    VVFALLBACK="microsoft/VibeVoice-1.5B"
    ;;
esac

# Persist env for new shells
if ! grep -q "VIBEVOICE_DIR=" ~/.bashrc 2>/dev/null; then
  echo "export VIBEVOICE_DIR=\$PWD/VibeVoice" >> ~/.bashrc
fi
if ! grep -q "VIBEVOICE_MODEL=" ~/.bashrc 2>/dev/null; then
  echo "export VIBEVOICE_MODEL=$VVMODEL" >> ~/.bashrc
else
  sed -i "s#^export VIBEVOICE_MODEL=.*#export VIBEVOICE_MODEL=$VVMODEL#" ~/.bashrc
fi
if ! grep -q "VIBEVOICE_FALLBACK_MODEL=" ~/.bashrc 2>/dev/null; then
  echo "export VIBEVOICE_FALLBACK_MODEL=$VVFALLBACK" >> ~/.bashrc
else
  sed -i "s#^export VIBEVOICE_FALLBACK_MODEL=.*#export VIBEVOICE_FALLBACK_MODEL=$VVFALLBACK#" ~/.bashrc
fi

export VIBEVOICE_DIR="$PWD/VibeVoice"
export VIBEVOICE_MODEL="$VVMODEL"
export VIBEVOICE_FALLBACK_MODEL="$VVFALLBACK"

echo "[7/8] report torch and CUDA"
uv run python - <<PY
import torch
print("torch:", torch.__version__)
print("cuda:", torch.version.cuda)
print("device count:", torch.cuda.device_count())
if torch.cuda.is_available():
    print("device 0:", torch.cuda.get_device_name(0))
PY

echo "[8/8] try FlashAttention 2 wheel, then source"
uv pip install -U pip setuptools wheel packaging cmake ninja pybind11
set +e
uv pip install "flash-attn==2.6.3" || uv pip install --no-build-isolation "flash-attn==2.6.3"
FA_STATUS=$?
set -e
if [ $FA_STATUS -ne 0 ]; then
  echo "flash-attn failed; setting SDPA fallback"
  if ! grep -q "TRANSFORMERS_ATTENTION_IMPLEMENTATION=sdpa" ~/.bashrc 2>/dev/null; then
    echo "export TRANSFORMERS_ATTENTION_IMPLEMENTATION=sdpa" >> ~/.bashrc
  fi
  export TRANSFORMERS_ATTENTION_IMPLEMENTATION=sdpa
else
  echo "flash-attn installed successfully."
fi

echo "Install complete."
'
