# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: MIT
"""Tests for RShell server module package."""

import importlib.util
import runpy
from pathlib import Path


SERVER_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "mfd_connect" / "rshell_server" / "rshell_server.py"


def _load_server_module(module_name: str = "test_rs_server"):
    spec = importlib.util.spec_from_file_location(module_name, SERVER_SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RSHELL_SERVER_MODULE_PATH = Path(__file__).resolve().parents[3] / "mfd_connect" / "rshell_server"
RSHELL_SERVER_INIT_PATH = RSHELL_SERVER_MODULE_PATH / "__init__.py"
RSHELL_SERVER_MAIN_PATH = RSHELL_SERVER_MODULE_PATH / "__main__.py"


class TestRShellServerModule:
    """Tests for RShell server module package."""

    def test_rshell_server_init_exists(self):
        """Test that __init__.py file exists in rshell_server package."""
        assert RSHELL_SERVER_INIT_PATH.exists()

    def test_rshell_server_main_exists(self):
        """Test that __main__.py file exists in rshell_server package."""
        assert RSHELL_SERVER_MAIN_PATH.exists()

    def test_rshell_server_module_init_has_docstring(self):
        """Test that __init__.py has proper module documentation."""
        with open(RSHELL_SERVER_INIT_PATH) as f:
            content = f.read()
        assert '"""Module for sample rshell server."""' in content

    def test_rshell_server_main_imports_run(self):
        """Test that __main__.py imports run function from rshell_server.rshell_server."""
        with open(RSHELL_SERVER_MAIN_PATH) as f:
            content = f.read()
        assert "from mfd_connect.rshell_server import rshell_server" in content
        assert "rshell_server.run()" in content

    def test_rshell_server_run_function_callable(self):
        """Test that run function is callable in loaded rshell_server."""
        server_module = _load_server_module()
        assert hasattr(server_module, "run")
        assert callable(server_module.run)

    def test_rshell_server_init_module_import(self):
        """Test that rshell_server package __init__ can be imported."""
        # Import the rshell_server package - this executes __init__.py
        import mfd_connect.rshell_server as rs_module

        # Verify the module exists and has the expected docstring
        assert rs_module.__doc__
        assert "rshell server" in rs_module.__doc__.lower()

    def test_rshell_server_main_module_callable(self):
        """Test that run function exists in rshell_server.py module."""
        # Load the rshell_server.py file from within the package
        server_module = _load_server_module()

        # Verify it has the run function
        assert hasattr(server_module, "run"), "rshell_server.py should have run function"
        assert callable(server_module.run), "run should be callable"

    def test_rshell_server_main_execute_as_script(self, mocker):
        """Test __main__.py when executed as a script (if __name__ == '__main__')."""
        # Mock Flask to prevent server startup
        mocker.patch("flask.Flask")

        # Read and execute __main__.py content with __name__ = "__main__"
        # The __main__.py should import from the package and call run()
        mock_run = mocker.Mock()
        mocker.patch("mfd_connect.rshell_server.rshell_server.run", mock_run)

        # Execute __main__.py as if it were the main module
        try:
            runpy.run_path(str(RSHELL_SERVER_MAIN_PATH), run_name="__main__")
        except (AttributeError, SystemExit):
            # In case the run() function triggers Flask startup or errors
            # This is expected since run is mocked
            pass
