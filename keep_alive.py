"""
Keep-alive worker: pings Render every 10 minutes so it never sleeps.
Deploy this as a SECOND free service on Render (cron job).
"""
import time
import urllib.request

URL = "https://edura-converter.onrender.com/health"

while True:
    try:
        req = urllib.request.urlopen(URL, timeout=10)
        print(f"✅ Pinged — status {req.status}")
    except Exception as e:
        print(f"⚠️  Ping failed: {e}")
    time.sleep(600)  # every 10 minutes
