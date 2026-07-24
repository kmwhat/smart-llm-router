import unittest
from pathlib import Path

from smart_llm_router import __version__
from smart_llm_router.router import _clean_transcript_locally


class PublicPackageBoundaryTests(unittest.TestCase):
    def test_release_metadata_matches_package_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        readiness = (root / "RELEASE_READINESS.md").read_text(encoding="utf-8")
        self.assertIn(
            f"/releases/download/v{__version__}/smart_llm_router-{__version__}-py3-none-any.whl",
            readme,
        )
        self.assertIn(f"## {__version__} - ", changelog)
        current_readiness = readiness.split("## 0.6.0rc2", 1)[0]
        self.assertNotIn("not committed, pushed, tagged, or published", current_readiness)

    def test_shipped_docs_keep_quickstart_router_core_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        docs = [
            root / "README.md",
            root / "PROVIDER_SETUP.md",
            root / "codex-skill" / "smart-llm-router" / "SKILL.md",
            root / "codex-skill" / "hermes-smart-llm-router" / "SKILL.md",
            root / "hermes-skill" / "model-routing-foundation" / "SKILL.md",
        ]
        encoded_workload_examples = (
            "e6b0b4e5a2a8e5b1b1e6b0b4",
            "e4bfaee6ada3e68a80e69cafe59fb9e8aeade8bdace58699e7a8bf",
            "e695b0e68daee5ba93e7b4a2e5bc95e4bc98e58c96",
            "e5a48de59088e7b4a2e5bc95e5ba94e7bb93e59088e69fa5e8afa2e69da1e4bbb6e8aebee8aea1",
            "e5aea1e8aea1e69eb6e69e84e5b9b6e8aebee8aea1e5a49ae6ada5e9aaa4e4bc98e58c96e696b9e6a188",
            "e8a784e58892e38081e689a7e8a18ce5b9b6e5aea1e8aea1e7b3bbe7bb9fe58d87e7baa7",
        )
        forbidden = tuple(bytes.fromhex(value).decode("utf-8") for value in encoded_workload_examples) + (
            "smart-llm-router " + "image-generate",
            "smart-llm-router " + "transcript-correct",
            "smart-llm-router " + "remote-transcribe",
            "smart-llm-router " + "transcribe",
            "smart-llm-router " + "benchmark-vision",
            "smart-llm-router " + "embed",
            "smart-llm-router " + "rerank",
        )
        violations = []
        for path in docs:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    violations.append(f"{path.relative_to(root)}:{token}")
        self.assertEqual(violations, [])

        readme = (root / "README.md").read_text(encoding="utf-8")
        quickstart_section = readme.split("## 常用命令", 1)[1]
        quickstart_commands = quickstart_section.split("```bash", 1)[1].split("```", 1)[0]
        self.assertNotIn("--paid", quickstart_commands)
        self.assertNotIn("--allow-paid", quickstart_commands)
        self.assertNotIn("--provider", quickstart_commands)

    def test_shipped_files_do_not_contain_private_domain_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        files = [
            root / ".env.example",
            root / "CHANGELOG.md",
            root / "PROVIDER_SETUP.md",
            root / "README.md",
            root / "RELEASE_READINESS.md",
            root / "pyproject.toml",
        ]
        files.extend((root / "smart_llm_router").rglob("*.py"))
        files.extend((root / "codex-skill").rglob("*.md"))
        files.extend((root / "hermes-skill").rglob("*.md"))
        files.extend((root / "research").rglob("*.md"))
        encoded_tokens = (
            "e9a38ee6b0b4",
            "e6898be79bb8",
            "e585abe5ad97",
            "e5a587e997a8",
            "e6a285e88ab1",
            "e585ade788bb",
            "e7b4abe5beae",
            "e591bde79086",
        )
        forbidden = tuple(bytes.fromhex(value).decode("utf-8") for value in encoded_tokens) + (
            "FENG" + "SHUI_",
            "feng" + "shui",
            "qi" + "men",
            "palm" + "istry",
            "hand" + ".png",
        )
        violations = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    violations.append(f"{path.relative_to(root)}:{token}")
        self.assertEqual(violations, [])

    def test_local_transcript_cleanup_does_not_apply_domain_glossary(self) -> None:
        source_term = "金" + "门"
        text = f"讲者说{source_term}的历史需要结合地方资料核对。"
        cleaned, notes = _clean_transcript_locally(text)
        self.assertEqual(cleaned, text)
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
