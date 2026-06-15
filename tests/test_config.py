"""Tests for config package."""

import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ytsubviewer.config import (
    APP_VERSION,
    Settings,
    decrypt_value,
    encrypt_value,
    save_user_settings,
)
from ytsubviewer.config.crypto import _derive_encryption_key


class CryptoTests(unittest.TestCase):
    def test_derive_encryption_key_returns_bytes(self):
        key = _derive_encryption_key()
        self.assertIsInstance(key, bytes)

    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "test-api-key-12345"
        encrypted = encrypt_value(plaintext)
        self.assertNotEqual(encrypted, plaintext)
        decrypted = decrypt_value(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_same_input_different_output(self):
        """Fernet encryption includes random nonce, so same input produces different output."""
        a = encrypt_value("hello")
        b = encrypt_value("hello")
        self.assertNotEqual(a, b)


class SettingsTests(unittest.TestCase):
    def test_settings_load_returns_settings_instance(self):
        settings = Settings.load()
        self.assertIsInstance(settings, Settings)

    def test_settings_has_default_values(self):
        settings = Settings.load()
        self.assertIn(settings.provider_name, ["deepseek", "deepseek-test"])
        self.assertTrue(settings.model_name)  # Has some value

    def test_settings_ensure_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = Settings(
                project_root=Path(tmpdir),
                config_dir=Path(tmpdir) / "config",
                data_root=Path(tmpdir) / "data",
                workspace_dir=Path(tmpdir) / "workspace",
                jobs_dir=Path(tmpdir) / "workspace" / "jobs",
                cache_dir=Path(tmpdir) / "cache",
                temp_dir=Path(tmpdir) / "tmp",
                logs_dir=Path(tmpdir) / "logs",
                hf_home=Path(tmpdir) / "cache" / "hf",
                xdg_cache_home=Path(tmpdir) / "cache",
            )
            settings.ensure_directories()
            self.assertTrue(settings.data_root.exists())
            self.assertTrue(settings.jobs_dir.exists())
            self.assertTrue(settings.cache_dir.exists())

    def test_translation_controls(self):
        settings = Settings(
            translation_style_preset="default",
            translation_glossary_json='[{"source": "AI", "target": "人工智能"}]',
            translation_protected_terms_json="CUDA,GPU",
        )
        controls = settings.translation_controls()
        self.assertEqual(controls.style_preset, "default")
        self.assertEqual(len(controls.glossary), 1)
        self.assertEqual(len(controls.protected_terms), 2)


class SaveUserSettingsTests(unittest.TestCase):
    def test_save_and_load_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "settings.json"
            save_user_settings(
                provider_name="test-provider",
                model_name="test-model",
                base_url="https://test.example.com",
                path=config_path,
            )
            self.assertTrue(config_path.exists())

            import json
            data = json.loads(config_path.read_text())
            self.assertEqual(data["provider_name"], "test-provider")
            self.assertEqual(data["model_name"], "test-model")
            self.assertEqual(data["custom_base_url"], "https://test.example.com")


if __name__ == "__main__":
    unittest.main()
