#!/usr/bin/env python3
"""MCX commodity options desk API (/api/mcx-desk). Separate from the stock routes and from /api/mcx (the
Commodities tab of the stock dashboard). A background thread runs mcx_desk.tick() every minute while the server
runs (set MCX_DESK_LOOP=0 to disable)."""

import logging
import os
import threading
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from dashboard import mcx_desk


def _loop() -> None:
    while True:
        time.sleep(60 - time.time() % 60 + 5)        # ~5 s after each minute: the 5-min candle is in Kite by then
        try:
            mcx_desk.tick()
        except Exception as e:                       # keep the loop alive; the next minute retries
            logging.getLogger("uvicorn.error").warning("mcx desk tick failed: %s", e)


def _start() -> None:
    if os.environ.get("MCX_DESK_LOOP", "1") != "0":
        threading.Thread(target=_loop, name="mcx-desk", daemon=True).start()


router = APIRouter(prefix="/api/mcx-desk", tags=["mcx-desk"], on_startup=[_start])


@router.get("")
def desk() -> Dict[str, Any]:
    return mcx_desk.desk()


@router.get("/validation")
def validation() -> Dict[str, Any]:
    return mcx_desk.validation()


@router.post("/settings")
def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return mcx_desk.save_settings(patch)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@router.post("/tick")
def tick() -> Dict[str, Any]:
    return mcx_desk.tick()
