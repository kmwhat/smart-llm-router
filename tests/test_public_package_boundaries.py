import unittest
from pathlib import Path

from smart_llm_router.router import _clean_transcript_locally


class PublicPackageBoundaryTests(unittest.TestCase):
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
