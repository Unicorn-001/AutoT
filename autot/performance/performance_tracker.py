"""
File: performance_tracker.py
Project: AutoT

Purpose:
    Track execution time of AutoT processing stages.
"""

import time


class PerformanceTracker:
    def __init__(self) -> None:
        self.timings = {}

    def start(self, name: str) -> None:
        self.timings[name] = {
            "start": time.time(),
            "elapsed": 0.0,
        }

    def stop(self, name: str) -> None:
        if name not in self.timings:
            return

        self.timings[name]["elapsed"] = (
            time.time() - self.timings[name]["start"]
        )

    def print_report(self) -> None:
        print("\n========== PERFORMANCE REPORT ==========")

        total = 0.0

        for name, timing in self.timings.items():
            elapsed = timing["elapsed"]
            total += elapsed
            print(f"{name:<25}: {elapsed:.2f} sec")

        print("----------------------------------------")
        print(f"{'Total measured':<25}: {total:.2f} sec")
        print("========================================")