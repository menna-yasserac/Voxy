#!/usr/bin/env bash
# Installs Voxy as a desktop application (menu entry + icon).
# Usage:  bash install_voxy.sh
set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ASSETS="$DIR/voxy_v2/assets"

chmod +x "$DIR/voxy_launcher.sh"

# icons
for s in 16 32 48 64 128 256; do
  d="$HOME/.local/share/icons/hicolor/${s}x${s}/apps"
  mkdir -p "$d"
  cp "$ASSETS/voxy_icon_${s}.png" "$d/voxy.png"
done
mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
cp "$ASSETS/voxy_icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/voxy.png"

# menu entry
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/voxy.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Voxy
Comment=Linux AI Voice Assistant
Exec=$DIR/voxy_launcher.sh
Icon=voxy
Terminal=false
Categories=Utility;AudioVideo;
StartupWMClass=Voxy
DESK
chmod +x "$HOME/.local/share/applications/voxy.desktop"

# API key file (created once, you fill it in)
mkdir -p "$HOME/.config/voxy"
if [ ! -f "$HOME/.config/voxy/voxy.env" ]; then
  echo 'GROQ_API_KEY=PUT_YOUR_KEY_HERE' > "$HOME/.config/voxy/voxy.env"
  chmod 600 "$HOME/.config/voxy/voxy.env"
  echo "-> Edit ~/.config/voxy/voxy.env and put your real GROQ_API_KEY."
fi

command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "Done. Search for 'Voxy' in your applications menu."
