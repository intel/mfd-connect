# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Unit tests for ssh_config_parser utility."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import paramiko
import pytest
from mfd_connect.util.ssh_config_parser import (
    SSHHostConfig,
    _parse_proxy_jump_hop,
    parse_ssh_config,
    resolve_host,
)


@pytest.fixture()
def ssh_config_file(tmp_path: Path) -> Path:
    """Create a temporary SSH config file with test entries."""
    config_content = textwrap.dedent("""\
        Host direct-host
            HostName 10.10.10.10
            User root
            StrictHostKeyChecking no
            IdentityFile /home/user/.ssh/id_rsa
            UserKnownHostsFile=/dev/null

        Host jump-host
            HostName 10.20.20.20
            User admin
            StrictHostKeyChecking no
            IdentityFile /home/user/.ssh/id_rsa

        Host tunneled-host
            HostName 192.168.0.1
            User root
            ProxyJump jump-host
            StrictHostKeyChecking no

        Host deep-host
            HostName 172.16.0.1
            User root
            ProxyJump tunneled-host
            StrictHostKeyChecking no

        Host custom-port
            HostName 10.30.30.30
            User deploy
            Port 2222

        Host circular-a
            HostName 10.0.0.1
            ProxyJump circular-b

        Host circular-b
            HostName 10.0.0.2
            ProxyJump circular-a

        Host comma-hop
            HostName 172.16.0.100
            User root
            ProxyJump jump-host,tunneled-host
            StrictHostKeyChecking no

        Host override-hop
            HostName 172.16.0.200
            User root
            ProxyJump deployer@jump-host:2222
            StrictHostKeyChecking no
    """)
    config_file = tmp_path / "config"
    config_file.write_text(config_content)
    return config_file


@pytest.fixture()
def parsed_config(ssh_config_file: Path) -> paramiko.SSHConfig:
    """Parse the temporary SSH config file."""
    return parse_ssh_config(ssh_config_file)


class TestParseSSHConfig:
    """Tests for parse_ssh_config function."""

    def test_parse_valid_config(self, ssh_config_file: Path) -> None:
        """Test parsing a valid SSH config file."""
        config = parse_ssh_config(ssh_config_file)
        assert isinstance(config, paramiko.SSHConfig)
        hostnames = config.get_hostnames()
        assert "direct-host" in hostnames
        assert "jump-host" in hostnames

    def test_parse_missing_config_raises_file_not_found(self, tmp_path: Path) -> None:
        """Test that missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="SSH config not found"):
            parse_ssh_config(tmp_path / "nonexistent")

    def test_parse_default_path(self, tmp_path: Path) -> None:
        """Test that default path is ~/.ssh/config."""
        with patch.object(Path, "home", return_value=tmp_path):
            ssh_dir = tmp_path / ".ssh"
            ssh_dir.mkdir()
            config_file = ssh_dir / "config"
            config_file.write_text("Host test\n    HostName 1.2.3.4\n")
            config = parse_ssh_config()
            assert "test" in config.get_hostnames()


class TestResolveHost:
    """Tests for resolve_host function."""

    def test_resolve_direct_host(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test resolving a direct host without ProxyJump."""
        result = resolve_host("direct-host", parsed_config)
        assert result.hostname == "10.10.10.10"
        assert result.user == "root"
        assert result.port == 22
        assert "/home/user/.ssh/id_rsa" in result.identity_file
        assert result.strict_host_key_checking is False
        assert result.proxy_jump is None
        assert result.proxy_chain == []

    def test_resolve_custom_port(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test resolving a host with custom port."""
        result = resolve_host("custom-port", parsed_config)
        assert result.hostname == "10.30.30.30"
        assert result.user == "deploy"
        assert result.port == 2222

    def test_resolve_single_proxy_jump(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test resolving a host with a single ProxyJump hop."""
        result = resolve_host("tunneled-host", parsed_config)
        assert result.hostname == "192.168.0.1"
        assert result.user == "root"
        assert result.proxy_jump == "jump-host"
        assert len(result.proxy_chain) == 1
        assert result.proxy_chain[0].hostname == "10.20.20.20"
        assert result.proxy_chain[0].user == "admin"

    def test_resolve_chained_proxy_jump(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test resolving a host with chained ProxyJump (2 hops)."""
        result = resolve_host("deep-host", parsed_config)
        assert result.hostname == "172.16.0.1"
        assert result.proxy_jump == "tunneled-host"
        assert len(result.proxy_chain) == 2
        # First hop is the immediate jump host
        assert result.proxy_chain[0].hostname == "192.168.0.1"
        # Second hop is the outermost gateway
        assert result.proxy_chain[1].hostname == "10.20.20.20"

    def test_resolve_circular_proxy_jump_raises_value_error(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test that circular ProxyJump raises ValueError."""
        with pytest.raises(ValueError, match="Circular ProxyJump detected"):
            resolve_host("circular-a", parsed_config)

    def test_resolve_unknown_host_raises_value_error(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test that unknown mnemonic raises ValueError."""
        with pytest.raises(ValueError, match="not found in SSH config"):
            resolve_host("nonexistent-host", parsed_config)

    def test_resolve_strict_host_key_checking_default(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test that StrictHostKeyChecking defaults to True."""
        result = resolve_host("custom-port", parsed_config)
        assert result.strict_host_key_checking is True

    def test_resolve_no_identity_file(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test resolving host without IdentityFile."""
        result = resolve_host("tunneled-host", parsed_config)
        assert result.identity_file == []

    def test_resolve_comma_separated_proxy_jump(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test resolving a host with comma-separated ProxyJump hops."""
        result = resolve_host("comma-hop", parsed_config)
        assert result.hostname == "172.16.0.100"
        # comma-hop -> ProxyJump jump-host,tunneled-host
        # In OpenSSH: connect to jump-host first, then tunneled-host, then target
        # proxy_chain[0] = tunneled-host (immediate predecessor)
        # proxy_chain[1] = jump-host (from tunneled-host's own ProxyJump)
        # proxy_chain[2] = jump-host (outermost gateway from comma list)
        assert len(result.proxy_chain) == 3
        assert result.proxy_chain[0].hostname == "192.168.0.1"  # tunneled-host
        assert result.proxy_chain[1].hostname == "10.20.20.20"  # jump-host (via tunneled)
        assert result.proxy_chain[2].hostname == "10.20.20.20"  # jump-host (direct)

    def test_resolve_proxy_jump_with_user_and_port_override(self, parsed_config: paramiko.SSHConfig) -> None:
        """Test that user@host:port in ProxyJump overrides user and port."""
        result = resolve_host("override-hop", parsed_config)
        assert result.hostname == "172.16.0.200"
        assert len(result.proxy_chain) == 1
        hop = result.proxy_chain[0]
        assert hop.hostname == "10.20.20.20"  # jump-host's HostName
        assert hop.user == "deployer"  # overridden from ProxyJump
        assert hop.port == 2222  # overridden from ProxyJump


class TestSSHHostConfig:
    """Tests for SSHHostConfig dataclass."""

    def test_defaults(self) -> None:
        """Test SSHHostConfig default values."""
        config = SSHHostConfig(hostname="1.2.3.4", user="root")
        assert config.port == 22
        assert config.identity_file == []
        assert config.strict_host_key_checking is True
        assert config.proxy_jump is None
        assert config.proxy_chain == []


class TestParseProxyJumpHop:
    """Tests for _parse_proxy_jump_hop helper."""

    def test_plain_mnemonic(self) -> None:
        """Test parsing a plain mnemonic without user or port."""
        mnemonic, user, port = _parse_proxy_jump_hop("jump-host")
        assert mnemonic == "jump-host"
        assert user is None
        assert port is None

    def test_user_at_host(self) -> None:
        """Test parsing user@host format."""
        mnemonic, user, port = _parse_proxy_jump_hop("admin@jump-host")
        assert mnemonic == "jump-host"
        assert user == "admin"
        assert port is None

    def test_host_with_port(self) -> None:
        """Test parsing host:port format."""
        mnemonic, user, port = _parse_proxy_jump_hop("jump-host:2222")
        assert mnemonic == "jump-host"
        assert user is None
        assert port == 2222

    def test_user_at_host_with_port(self) -> None:
        """Test parsing user@host:port format."""
        mnemonic, user, port = _parse_proxy_jump_hop("admin@jump-host:2222")
        assert mnemonic == "jump-host"
        assert user == "admin"
        assert port == 2222

    def test_non_numeric_port_treated_as_host(self) -> None:
        """Test that non-numeric port in host:text is left as part of mnemonic."""
        mnemonic, user, port = _parse_proxy_jump_hop("host:notaport")
        assert mnemonic == "host:notaport"
        assert user is None
        assert port is None
