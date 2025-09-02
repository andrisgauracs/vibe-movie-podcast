bash -lc '
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y ffmpeg git
# install uv if missing
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  . ~/.bashrc || true
fi
# install your project deps
uv pip install -r requirements.txt
# get VibeVoice and install it
if [ ! -d VibeVoice ]; then
  git clone https://github.com/microsoft/VibeVoice.git
fi
uv pip install -e ./VibeVoice
echo "Install complete."
'
