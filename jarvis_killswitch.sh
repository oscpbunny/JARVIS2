#!/bin/bash
# Jarvis Instant Emergency Killswitch
echo "🛑 Triggering Jarvis Killswitch..."
touch /tmp/jarvis.kill
sleep 0.5

# Ensure all daemon processes are terminated
pkill -f "always_online_jarvis.py" 2>/dev/null || true
rm -f /tmp/jarvis.kill
echo "✅ Jarvis core daemon and all audio/camera pipelines halted."
