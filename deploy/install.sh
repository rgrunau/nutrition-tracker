#!/usr/bin/env bash
# Install (or refresh) the weekly systemd user timer for nutrition-tracker.
#
# Symlinks the unit files from this directory into the systemd user unit path,
# so later edits here take effect after `systemctl --user daemon-reload`.
# Re-runnable and idempotent.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$UNIT_DIR"
ln -sf "$DIR/nutrition-tracker.service" "$UNIT_DIR/nutrition-tracker.service"
ln -sf "$DIR/nutrition-tracker.timer"   "$UNIT_DIR/nutrition-tracker.timer"

systemctl --user daemon-reload
systemctl --user enable --now nutrition-tracker.timer

echo
echo "Installed. Next run:"
systemctl --user list-timers nutrition-tracker.timer --all --no-pager

cat <<'EOF'

Useful commands:
  systemctl --user list-timers nutrition-tracker.timer   # when it next fires
  systemctl --user start nutrition-tracker.service        # run once, now
  journalctl --user -u nutrition-tracker.service -n 20    # last run's output
  systemctl --user disable --now nutrition-tracker.timer  # stop scheduling

If the laptop is usually asleep/off at the scheduled time and you want the job
to run even when you are not logged in:
  sudo loginctl enable-linger "$USER"
EOF
