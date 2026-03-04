# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Example usage of SSHConfigConnection with ~/.ssh/config Host mnemonics."""

from mfd_connect import SSHConfigConnection

# Direct host (no ProxyJump) — uses IdentityFile from config
conn = SSHConfigConnection(host="b1.a.host")
res = conn.execute_command("hostname", shell=True)
print(f"Connected to: {res.stdout.strip()}")
conn.disconnect()

# Single ProxyJump — imc goes through lp
conn = SSHConfigConnection(host="imc")
res = conn.execute_command("uname -a", shell=True)
print(f"IMC: {res.stdout.strip()}")
conn.disconnect()

# Chained ProxyJump — acc goes through imc, then lp
conn = SSHConfigConnection(host="acc")
res = conn.execute_command("cat /etc/os-release | head -1", shell=True)
print(f"ACC: {res.stdout.strip()}")
conn.disconnect()

# Password override (when no IdentityFile in config)
conn = SSHConfigConnection(host="sut", password="my_password")
res = conn.execute_command("whoami", shell=True)
print(f"SUT user: {res.stdout.strip()}")
conn.disconnect()

# Custom SSH config path
conn = SSHConfigConnection(host="my-host", config_path="/path/to/custom/config")
res = conn.execute_command("echo hello", shell=True)
print(f"Output: {res.stdout.strip()}")
conn.disconnect()
