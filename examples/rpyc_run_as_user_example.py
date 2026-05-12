# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT

"""Example: Windows run-as-user and local account management over RPyCConnection."""

from mfd_connect import RPyCConnection

# Configure connection to Windows host with running RPyC server.
conn = RPyCConnection(ip="10.10.10.10")

# Temporary local account used for the demo.
username = "mfd_temp_user"
password = "pass"

try:
    # Create local user.
    create_result = conn.create_user(username=username, password=password)
    print("CREATE USER")
    print(f"return_code: {create_result.return_code}")

    # Execute command as created user.
    run_result = conn.execute_command_as_user(
        command="whoami",
        user=username,
        password=password,
        domain=".",
        timeout=60,
    )
    print("RUN AS USER")
    print(f"stdout: {run_result.stdout}")
    print(f"stderr: {run_result.stderr}")
    print(f"return_code: {run_result.return_code}")
finally:
    # Delete temporary user even if command execution fails.
    delete_result = conn.delete_user(username=username, expected_return_codes={0, 2})
    print("DELETE USER")
    print(f"return_code: {delete_result.return_code}")
