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
uv pip install huggingface_hub

echo "[4/7] Hugging Face authentication"
echo "Please login to Hugging Face to access the VibeVoice-1.5B model."
hf auth login

echo "[5/7] download VibeVoice-1.5B model from Hugging Face"
mkdir -p vibevoice_model
cd vibevoice_model
hf download microsoft/VibeVoice-1.5B --local-dir .
cd ..

# Set environment variable for model directory
if ! grep -q "VIBEVOICE_DIR=" ~/.bashrc 2>/dev/null; then
  echo "export VIBEVOICE_DIR=\$PWD/vibevoice_model" >> ~/.bashrc
fi
if ! grep -q "VIBEVOICE_MODEL=" ~/.bashrc 2>/dev/null; then
  echo "export VIBEVOICE_MODEL=microsoft/VibeVoice-1.5B" >> ~/.bashrc
else
  sed -i "s#^export VIBEVOICE_MODEL=.*#export VIBEVOICE_MODEL=microsoft/VibeVoice-1.5B#" ~/.bashrc
fi

export VIBEVOICE_DIR="$PWD/vibevoice_model"
export VIBEVOICE_MODEL="microsoft/VibeVoice-1.5B"

echo "[6/7] report torch and CUDA"
uv run python - <<PY
import torch
print("device 0:", torch.cuda.get_device_name(0))
PY

echo "[7/7] try FlashAttention 2 wheel, then source"
uv pip install -U pip setuptools wheel packaging cmake ninja pybind11 psutil
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

uv pip install "numpy<=2.2" --force-reinstall

echo "Install complete."
'
