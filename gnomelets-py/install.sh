#!/usr/bin/env bash
# install.sh — install desktop-pets so it runs from ANY terminal/directory
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/desktop-pets"
BIN="$HOME/.local/bin/desktop-pets"
AUTOSTART="$HOME/.config/autostart/desktop-pets.desktop"

echo "🐾 Installing Desktop Pets..."

# ── 1. Check Python + GTK ────────────────────────────────────────────────────
python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null \
  || { echo "❌ Missing PyGObject. Run: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"; exit 1; }
echo "✓ Python + GTK OK"

# ── 2. AppIndicator3 (system tray) ───────────────────────────────────────────
echo "📦 Installing AppIndicator3 for top-bar icon..."
sudo apt-get install -y gir1.2-ayatanaappindicator3-0.1 2>/dev/null \
  || sudo apt-get install -y gir1.2-appindicator3-0.1 2>/dev/null \
  || echo "⚠  AppIndicator3 not installed — will use StatusIcon fallback"

# ── 3. wmctrl (window collision) ─────────────────────────────────────────────
command -v wmctrl &>/dev/null \
  && echo "✓ wmctrl found" \
  || { echo "📦 Installing wmctrl..."; sudo apt-get install -y wmctrl 2>/dev/null || echo "⚠  wmctrl not installed — window-walking disabled"; }

# ── 4. Copy files to ~/.local/share/desktop-pets ─────────────────────────────
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/run.sh"
echo "✓ Copied to $INSTALL_DIR"

# ── 5. Create the `desktop-pets` launcher in ~/.local/bin ────────────────────
mkdir -p "$HOME/.local/bin"
cat > "$BIN" << 'EOF'
#!/usr/bin/env bash
exec "$HOME/.local/share/desktop-pets/run.sh" "$@"
EOF
chmod +x "$BIN"
echo "✓ Launcher created: $BIN"

# ── 6. Make sure ~/.local/bin is on PATH (permanently) ───────────────────────
add_to_path() {
  local FILE="$1"
  local LINE='export PATH="$HOME/.local/bin:$PATH"'
  # Only add if the file exists and the line isn't already there
  if [ -f "$FILE" ] && ! grep -qF '.local/bin' "$FILE"; then
    echo "" >> "$FILE"
    echo "# Added by desktop-pets installer" >> "$FILE"
    echo "$LINE" >> "$FILE"
    echo "✓ Added ~/.local/bin to PATH in $FILE"
  fi
}

add_to_path "$HOME/.bashrc"
add_to_path "$HOME/.zshrc"
add_to_path "$HOME/.profile"   # fallback for other shells / login sessions

# Also export for the current shell session so it works immediately
export PATH="$HOME/.local/bin:$PATH"

# ── 7. Autostart on login ─────────────────────────────────────────────────────
mkdir -p "$(dirname "$AUTOSTART")"
cat > "$AUTOSTART" << EOF
[Desktop Entry]
Type=Application
Name=Desktop Pets
Exec=$BIN
Hidden=false
X-GNOME-Autostart-enabled=true
EOF
echo "✓ Autostart enabled (starts on login)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "✅ Done! You can now run from ANY terminal:"
echo ""
echo "   desktop-pets"
echo ""
echo "   (If it says 'command not found', run:  source ~/.bashrc  or open a new terminal)"
