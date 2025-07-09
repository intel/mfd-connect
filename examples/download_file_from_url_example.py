# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Download file from url examples."""

import logging

from mfd_connect import LocalConnection

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(message)s", datefmt="%I:%M:%S"
)

url = "https://www.artifactory-server.com/path/to/file.txt"
headers = {"X-JFrog-Art-Api":"my_personal_token"}

# 1. Authenticate via headers
connection = LocalConnection()  # it can be any connection object from MFD-Connect
connection.download_file_from_url(
    url=url,
    headers=headers,
    destination_file=connection.path("C:\\Users\\user\\Downloads\\file.txt"),
)

# 2. Authenticate via username/password
connection.download_file_from_url(
    url=url,
    username="my_username",
    password="***",
    destination_file=connection.path("C:\\Users\\user\\Downloads\\file.txt"),
)
