import os
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_llm_router.router import (
    _whisper_cpp_transcribe_command,
    asr_status,
)


class LocalAsrTests(unittest.TestCase):
    def test_asr_status_reports_no_gpu_opt_in(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMART_LLM_ASR_WHISPER_CPP_MODEL": "/tmp/model.bin",
                "SMART_LLM_ASR_WHISPER_CPP_NO_GPU": "true",
            },
            clear=True,
        ):
            with patch("smart_llm_router.router._command_path", return_value="/usr/local/bin/whisper-cli"):
                status = asr_status()

        self.assertTrue(status["backends"]["whisper_cpp"]["no_gpu"])

    def test_whisper_cpp_command_keeps_gpu_by_default(self) -> None:
        command = _whisper_cpp_transcribe_command(
            "/usr/local/bin/whisper-cli",
            "/tmp/model.bin",
            Path("/tmp/audio.wav"),
            "zh",
            Path("/tmp/output"),
            no_gpu=False,
        )

        self.assertNotIn("-ng", command)

    def test_whisper_cpp_command_adds_no_gpu_flag_when_enabled(self) -> None:
        command = _whisper_cpp_transcribe_command(
            "/usr/local/bin/whisper-cli",
            "/tmp/model.bin",
            Path("/tmp/audio.wav"),
            "zh",
            Path("/tmp/output"),
            no_gpu=True,
        )

        self.assertEqual(command[1], "-ng")
        self.assertEqual(command.count("-ng"), 1)


if __name__ == "__main__":
    unittest.main()
