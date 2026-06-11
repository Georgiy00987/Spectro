import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import spectro_main


with open("cfg/latest_brawler_data.json", encoding="utf-8") as f:
    spectro_main(json.load(f))
