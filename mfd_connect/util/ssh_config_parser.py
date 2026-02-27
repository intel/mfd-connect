# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Utility for parsing ~/.ssh/config and resolving Host mnemonics."""

import getpass
from dataclasses import dataclass, field
from pathlib import Path

import paramiko


@dataclass
class SSHHostConfig:
    """Resolved SSH config for a single Host mnemonic."""

    hostname: str
    user: str
    port: int = 22
    identity_file: list[str] = field(default_factory=list)
    strict_host_key_checking: bool = True
    proxy_jump: str | None = None
    proxy_chain: list["SSHHostConfig"] = field(default_factory=list)


def parse_ssh_config(config_path: str | Path | None = None) -> paramiko.SSHConfig:
    """Parse an SSH config file.

    :param config_path: Path to SSH config file. Defaults to ~/.ssh/config.
    :return: Parsed paramiko SSHConfig object.
    :raises FileNotFoundError: If config file does not exist.
    """
    if config_path is None:
        config_path = Path.home() / ".ssh" / "config"
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"SSH config not found: {config_path}")
    ssh_config = paramiko.SSHConfig()
    with open(config_path) as f:
        ssh_config.parse(f)
    return ssh_config


def _parse_proxy_jump_hop(hop_spec: str) -> tuple[str, str | None, int | None]:
    """Parse a single ProxyJump hop specification.

    Handles formats like ``host``, ``user@host``, ``host:port``,
    and ``user@host:port`` as allowed by OpenSSH.

    :param hop_spec: Single hop string from a ProxyJump value.
    :return: Tuple of (mnemonic_or_host, user_override, port_override).
    """
    user_override: str | None = None
    port_override: int | None = None
    spec = hop_spec.strip()
    if "@" in spec:
        user_override, spec = spec.split("@", 1)
    if ":" in spec:
        host_part, port_str = spec.rsplit(":", 1)
        try:
            port_override = int(port_str)
            spec = host_part
        except ValueError:
            pass  # Not a port number, treat whole thing as host
    return spec, user_override, port_override


def resolve_host(
    mnemonic: str,
    ssh_config: paramiko.SSHConfig,
    _visited: set[str] | None = None,
) -> SSHHostConfig:
    """Recursively resolve a Host mnemonic from SSH config.

    Resolves hostname, user, port, identity files, StrictHostKeyChecking
    and ProxyJump chains from the parsed SSH config.

    :param mnemonic: Host alias from ~/.ssh/config.
    :param ssh_config: Parsed paramiko SSHConfig.
    :param _visited: Internal set for circular ProxyJump detection.
    :return: Fully resolved SSHHostConfig with proxy chain.
    :raises ValueError: If mnemonic not found or circular ProxyJump detected.
    """
    if _visited is None:
        _visited = set()
    if mnemonic in _visited:
        raise ValueError(f"Circular ProxyJump detected: {mnemonic}")
    _visited.add(mnemonic)

    lookup = ssh_config.lookup(mnemonic)
    hostname = lookup.get("hostname", mnemonic)

    # If hostname equals the mnemonic and there is no explicit config entry,
    # the mnemonic was not found in the config file.
    available_hosts = ssh_config.get_hostnames()
    if mnemonic not in available_hosts and hostname == mnemonic:
        raise ValueError(f"Host mnemonic '{mnemonic}' not found in SSH config")

    user = lookup.get("user", getpass.getuser())
    port = int(lookup.get("port", 22))
    identity_file = lookup.get("identityfile", [])
    strict = lookup.get("stricthostkeychecking", "yes") != "no"
    proxy_jump_raw = lookup.get("proxyjump")

    host_config = SSHHostConfig(
        hostname=hostname,
        user=user,
        port=port,
        identity_file=identity_file,
        strict_host_key_checking=strict,
        proxy_jump=proxy_jump_raw,
    )

    if proxy_jump_raw:
        hops = [h.strip() for h in proxy_jump_raw.split(",")]
        chain: list[SSHHostConfig] = []
        for hop_spec in reversed(hops):
            mnemonic, user_override, port_override = _parse_proxy_jump_hop(hop_spec)
            hop_config = resolve_host(mnemonic, ssh_config, set(_visited))
            if user_override:
                hop_config.user = user_override
            if port_override is not None:
                hop_config.port = port_override
            chain.append(hop_config)
            chain.extend(hop_config.proxy_chain)
        host_config.proxy_chain = chain

    return host_config
