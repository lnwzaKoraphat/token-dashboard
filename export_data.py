#!/usr/bin/env python3
"""Export Hermes token usage data to static JSON files for Cloudflare Pages."""
import json
import os
import shutil
import server


def export():
    base = server.default_base()
    print("Reading profiles from:", base)
    
    # 1. Generate usage data for both day and hour buckets
    day_data = server.build_usage(base, bucket="day", days=7)
    hour_data = server.build_usage(base, bucket="hour", days=7)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(script_dir, "static")

    # 2. Save into static/ folder
    for folder in (static_dir, script_dir):
        with open(os.path.join(folder, "data.json"), "w", encoding="utf-8") as f:
            json.dump(day_data, f, ensure_ascii=False, indent=2)
        with open(os.path.join(folder, "data_day.json"), "w", encoding="utf-8") as f:
            json.dump(day_data, f, ensure_ascii=False, indent=2)
        with open(os.path.join(folder, "data_hour.json"), "w", encoding="utf-8") as f:
            json.dump(hour_data, f, ensure_ascii=False, indent=2)

    # 3. Copy index.html to root as well so Cloudflare Pages serves it regardless of root setting
    shutil.copy2(os.path.join(static_dir, "index.html"), os.path.join(script_dir, "index.html"))
    print("Exported data.json, data_day.json, data_hour.json successfully.")


if __name__ == "__main__":
    export()
