#!/usr/bin/env python3
"""
Launcher for the Indian Trading Strategy Dashboard (FastAPI + uvicorn).

Serves the REST API and the classic static UI on one port. The React app
(dashboard/web) proxies /api to this server in dev; a production `npm run build`
can be served from here too.

Usage:  python3 dashboard/run_dashboard.py [port]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root on sys.path

if __name__ == "__main__":
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print("=" * 60)
    print("  Indian Trading Strategy Dashboard — FastAPI backend")
    print(f"  URL: http://localhost:{port}")
    print("  Concurrent plumbing (threadpool) · Zerodha diagnostics active")
    print("=" * 60)
    uvicorn.run("dashboard.api_server:app", host="0.0.0.0", port=port, log_level="info")
