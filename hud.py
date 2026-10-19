#!/usr/bin/env python3
"""Jarvis Floating Native Desktop HUD."""
import sys
import webview

def create_hud():
    # Create floating, frameless, semi-transparent window
    window = webview.create_window(
        title="JARVIS CORTEX HUD",
        url="http://127.0.0.1:8790",
        width=520,
        height=520,
        resizable=True,
        frameless=False,
        easy_drag=True,
        on_top=True,  # Float on top of all windows
        background_color="#0a0a0f"
    )
    webview.start()

if __name__ == "__main__":
    create_hud()
