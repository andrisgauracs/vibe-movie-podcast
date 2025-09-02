bash -lc '
set -euo pipefail

echo "[1/7] apt packages"
sudo apt-get update -y
sudo apt-get install -y ffmpeg git build-essential ninja-build

echo "[2/7] install uv if missing"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  . ~/.bashrc || true
fi

echo "[3/7] install project deps"
uv pip install -r requirements.txt

echo "[4/7] clone VibeVoice if needed"
if [ ! -d VibeVoice ]; then
  git clone https://github.com/microsoft/VibeVoice.git
fi

echo "[5/7] install VibeVoice editable"
uv pip install -e ./VibeVoice

echo "[6/7] report torch and CUDA versions"
uv run python - <<PY
import torch
print("torch:", torch.__version__)
print("cuda:", torch.version.cuda)
print("device count:", torch.cuda.device_count())
if torch.cuda.is_available():
    print("device 0:", torch.cuda.get_device_name(0))
PY

echo "[7/7] try installing FlashAttention 2 wheel"
# prerequisites for building if we fall back
uv pip install -U pip setuptools wheel packaging cmake ninja pybind11

set +e
# try a prebuilt wheel first; if unavailable, try with no build isolation
uv pip install "flash-attn==2.6.3" || uv pip install --no-build-isolation "flash-attn==2.6.3"
FA_STATUS=$?
set -e

if [ $FA_STATUS -ne 0 ]; then
  echo "flash-attn install failed. Falling back to SDPA."
  if ! grep -q "TRANSFORMERS_ATTENTION_IMPLEMENTATION=sdpa" ~/.bashrc 2>/dev/null; then
    echo "export TRANSFORMERS_ATTENTION_IMPLEMENTATION=sdpa" >> ~/.bashrc
  fi
  export TRANSFORMERS_ATTENTION_IMPLEMENTATION=sdpa
else
  echo "flash-attn installed successfully."
fi
'