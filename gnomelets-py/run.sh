#!/usr/bin/env bash
# run.sh — launch desktop-pets, stripping snap library conflicts
cd "$(dirname "$0")"
exec env -i \
  HOME="$HOME" \
  PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  DISPLAY="$DISPLAY" \
  XAUTHORITY="$XAUTHORITY" \
  DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
  python3 desktop-pets.py "$@"
