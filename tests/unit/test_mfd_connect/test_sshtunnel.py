"""Unit tests for sshtunnel key loading helpers."""

from pathlib import Path

import paramiko

import mfd_connect.sshtunnel as sshtunnel


class TestSSHTunnelForwarderKeyLoading:
    def test_get_keys_loads_supported_private_keys(self, mocker, tmp_path):
        key_dir = tmp_path / "keys"
        key_dir.mkdir()

        (key_dir / "id_rsa").write_text("rsa")
        (key_dir / "id_ecdsa").write_text("ecdsa")

        ed25519_supported = hasattr(paramiko, "Ed25519Key")
        if ed25519_supported:
            (key_dir / "id_ed25519").write_text("ed25519")

        mocker.patch.object(sshtunnel.SSHTunnelForwarder, "get_agent_keys", return_value=["agent-key"])
        read_private_key = mocker.patch.object(
            sshtunnel.SSHTunnelForwarder,
            "read_private_key_file",
            side_effect=lambda pkey_file, logger=None, key_type=None: f"{Path(pkey_file).name}:{key_type.__name__}",
        )

        keys = sshtunnel.SSHTunnelForwarder.get_keys(
            logger=None, host_pkey_directories=[str(key_dir)], allow_agent=True
        )

        expected_keys = ["agent-key", "id_rsa:RSAKey", "id_ecdsa:ECDSAKey"]
        if ed25519_supported:
            expected_keys.append("id_ed25519:Ed25519Key")

        assert keys == expected_keys
        assert read_private_key.call_count == len(expected_keys) - 1

    def test_read_private_key_file_tries_supported_key_types_in_order(self, monkeypatch, tmp_path):
        key_file = tmp_path / "id_test"
        key_file.write_text("dummy-key")

        calls = []

        class FakeRSAKey:
            @classmethod
            def from_private_key_file(cls, pkey_file, password=None):
                calls.append(cls.__name__)
                raise paramiko.SSHException("rsa failed")

        class FakeECDSAKey:
            @classmethod
            def from_private_key_file(cls, pkey_file, password=None):
                calls.append(cls.__name__)
                raise paramiko.SSHException("ecdsa failed")

        class FakeEd25519Key:
            @classmethod
            def from_private_key_file(cls, pkey_file, password=None):
                calls.append(cls.__name__)
                return object()

        monkeypatch.setattr(sshtunnel.paramiko, "RSAKey", FakeRSAKey, raising=False)
        monkeypatch.setattr(sshtunnel.paramiko, "ECDSAKey", FakeECDSAKey, raising=False)
        if hasattr(sshtunnel.paramiko, "Ed25519Key"):
            monkeypatch.setattr(sshtunnel.paramiko, "Ed25519Key", FakeEd25519Key, raising=False)

        loaded_key = sshtunnel.SSHTunnelForwarder.read_private_key_file(str(key_file), pkey_password="secret")

        assert loaded_key is not None
        if hasattr(sshtunnel.paramiko, "Ed25519Key"):
            assert calls == ["FakeRSAKey", "FakeECDSAKey", "FakeEd25519Key"]
        else:
            assert calls == ["FakeRSAKey", "FakeECDSAKey"]
