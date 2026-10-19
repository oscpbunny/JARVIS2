import subprocess

def set_volume(level):
    subprocess.run(["osascript", "-e", f"set volume output volume {level}"])

def media_play_pause():
    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 100']) # play/pause key or Spotify/Music

print("Testing volume...")
