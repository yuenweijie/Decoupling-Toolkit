#!/bin/bash
# Double-click this file to update the calculator's benchmarks from URA.
# First time only: in Terminal run  chmod +x "run_ura_update.command"
cd "$(dirname "$0")"
/usr/bin/python3 ura_update.py
echo ""
read -p "Done. Press Enter to close."
