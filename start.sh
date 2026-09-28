#!/usr/bin/env bash
# Maximo Delivery AI Suite - start the web control surface.
set -e
cd "$(dirname "$0")"
python run.py doctor
echo
echo "Starting the control surface on http://127.0.0.1:8800"
exec python run.py ui
