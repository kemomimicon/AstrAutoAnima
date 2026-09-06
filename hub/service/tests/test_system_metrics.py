from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from astr_auto_anima_hub import system_metrics


class SystemMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        system_metrics._previous_cpu = None

    def tearDown(self) -> None:
        system_metrics._previous_cpu = None

    def test_cpu_percent_uses_delta_between_samples(self) -> None:
        samples = [
            system_metrics._CpuTimes(idle=400, total=1000),
            system_metrics._CpuTimes(idle=430, total=1100),
        ]
        with patch.object(system_metrics, "_read_cpu_times", side_effect=samples):
            self.assertEqual(system_metrics._cpu_percent(), 0.0)
            self.assertEqual(system_metrics._cpu_percent(), 70.0)

    def test_gpu_parser_accepts_multiple_nvidia_smi_rows(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout=(
                "0, NVIDIA GeForce RTX 5090, 82, 32607, 16384, 16223, 61\n"
                "1, NVIDIA GeForce RTX 4090, 15, 24564, 4096, 20468, 48\n"
            ),
            stderr="",
        )
        with (
            patch.object(system_metrics.shutil, "which", return_value="nvidia-smi"),
            patch.object(system_metrics.subprocess, "run", return_value=completed),
        ):
            gpus = system_metrics._gpu_metrics()
        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0].name, "NVIDIA GeForce RTX 5090")
        self.assertEqual(gpus[0].utilization_percent, 82)
        self.assertEqual(gpus[0].memory_used_mib, 16384)
        self.assertEqual(gpus[1].temperature_c, 48)


if __name__ == "__main__":
    unittest.main()
