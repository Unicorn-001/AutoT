"""
File: performance_tracker.py
Project: AutoT

Purpose:
    Track execution time of AutoT processing stages.

    Separates wall-clock stage timings from accumulated
    per-stock worker workload.
"""

import time


class PerformanceTracker:
    def __init__(self) -> None:
        self.timings = {}

    def start(self, name: str) -> None:
        self.timings[name] = {
            "start": time.perf_counter(),
            "elapsed": 0.0,
        }

    def stop(self, name: str) -> None:
        if name not in self.timings:
            return

        self.timings[name]["elapsed"] = (
            time.perf_counter()
            - self.timings[name]["start"]
        )

    def print_report(self) -> None:
        print("\n========== PERFORMANCE REPORT ==========")

        wall_clock_timings = {}
        worker_timings = {}

        worker_stages = {
            "indicators",
            "strategies",
            "backtest",
        }

        for name, timing in self.timings.items():
            elapsed = timing["elapsed"]

            if "_" in name:
                stage = name.rsplit("_", 1)[-1]

                if stage in worker_stages:
                    worker_timings[stage] = (
                        worker_timings.get(stage, 0.0)
                        + elapsed
                    )
                    continue

            wall_clock_timings[name] = elapsed

        print("\nWall-clock stages:")

        wall_clock_total = 0.0

        for stage, elapsed in wall_clock_timings.items():
            wall_clock_total += elapsed
            print(
                f"{stage:<25}: "
                f"{elapsed:.2f} sec"
            )

        print("----------------------------------------")
        print(
            f"{'Measured wall-clock total':<25}: "
            f"{wall_clock_total:.2f} sec"
        )

        if worker_timings:
            print("\nWorker workload:")
            print(
                "(Accumulated across stocks; "
                "parallel times overlap)"
            )

            worker_total = 0.0

            for stage, elapsed in worker_timings.items():
                worker_total += elapsed
                print(
                    f"{stage:<25}: "
                    f"{elapsed:.2f} sec"
                )

            print("----------------------------------------")
            print(
                f"{'Total worker workload':<25}: "
                f"{worker_total:.2f} sec"
            )

        print("========================================")
