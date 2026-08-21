#!/usr/bin/env python3
"""
Launcher script for Indian Trading Strategy Dashboard backend and UI server.
"""

import sys
from pathlib import Path

# Add dashboard directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from app import run_server

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
