import requests
import json
import time
from datetime import datetime
import os

URL = "https://mds.bird.co/gbfs/v2/public/cascais/free_bike_status.json"

os.makedirs("data/snapshots", exist_ok=True)


while True:
    try:
        response = requests.get(URL, timeout=10).json()
        now = datetime.now()
        name = now.strftime("%Y-%m-%d_%H-%M") + ".json"
        path = os.path.join("data", "snapshots", name)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(response, f)
        os.chmod(path, 0o444)      # только чтение
        scooters = response["data"]["bikes"]

        print(f"{now} - amount of scooters: {len(scooters)}")

        time.sleep(60 - time.time() % 60)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)