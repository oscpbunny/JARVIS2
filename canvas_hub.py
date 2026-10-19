#!/usr/bin/env python3
"""Local Canvas & Real-Time Drawing WebSocket Server for Jarvis."""
import asyncio
import json
from pathlib import Path
from aiohttp import web

CANVAS_HTML_PATH = Path(__file__).parent / "canvas.html"
connected_websockets = set()

async def index_handler(request):
    return web.FileResponse(CANVAS_HTML_PATH)

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_websockets.add(ws)
    try:
        async for msg in ws:
            pass
    finally:
        connected_websockets.remove(ws)
    return ws

async def broadcast_drawing(svg_or_command: dict):
    if not connected_websockets:
        return False
    payload = json.dumps(svg_or_command)
    for ws in list(connected_websockets):
        try:
            await ws.send_str(payload)
        except Exception:
            pass
    return True

if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
    web.run_app(app, host="127.0.0.1", port=8795)
