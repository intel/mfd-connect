# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for rpyc server sample."""

import argparse
import logging

from rpyc import SlaveService
from rpyc.utils.server import ThreadedServer

from mfd_connect.util.rpc_system_info_utils import DEFAULT_RPYC_6_0_0_RESPONDER_PORT

BACKLOG = 65536
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)


def run() -> None:
    """
    Run RPyC server with arguments.

    Add log as file if path is given
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_RPYC_6_0_0_RESPONDER_PORT,
        help="Port to bind to",
    )
    parser.add_argument("-l", "--log", type=str, default=None, help="Path to log file")
    parser.add_argument(
        "--ssl-keyfile",
        type=str,
        default=None,
        help="Path to SSL key file.",
    )
    parser.add_argument(
        "--ssl-certfile",
        type=str,
        default=None,
        help="Path to SSL certificate file.",
    )
    args = parser.parse_args()
    authenticator = None
    if args.log:
        fh = logging.FileHandler(args.log)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    if args.ssl_keyfile:
        from rpyc.utils.authenticators import SSLAuthenticator

        authenticator = SSLAuthenticator(keyfile=args.ssl_keyfile, certfile=args.ssl_certfile)
    server = ThreadedServer(SlaveService, port=args.port, logger=logger, backlog=BACKLOG, authenticator=authenticator)
    logger.info("RPyC server initializing")
    server.start()
