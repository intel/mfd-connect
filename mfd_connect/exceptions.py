# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for all the Connection exceptions."""

from subprocess import CalledProcessError


class ModuleFrameworkDesignError(Exception):
    """
    Generic exception for Modular Framework Design.

    All the specific exception classes must inherit from it.
    """


class ConnectionCalledProcessError(CalledProcessError, ModuleFrameworkDesignError):
    """
    Raised if unexpected return code is returned by the executed command.

    Wrapper around subprocess.CalledProcessError, modifying error message so
    it doesn't look silly if zero return code is unexpected:

    Command 'foobar' returned non-zero exit status 0.
    <changed to>
    Command 'foobar' returned unexpected exit status 0.
    """

    def __str__(self):
        if self.returncode < 0:
            return super().__str__()
        else:
            std_out_err = f"stdout: {self.stdout}" if not self.stderr else f"stderr: {self.stderr}"
            return f"Command '{self.cmd}' returned unexpected exit status {self.returncode:d}.\n\n{std_out_err}"


class RemoteProcessTimeoutExpired(ModuleFrameworkDesignError):
    """
    RemoteProcess wait timeout error.

    Raised by RemoteProcess.wait() in case the process is still running after the timeout expired.
    """


class TransferFileError(ModuleFrameworkDesignError):
    """Raised when problem with transferring file occurs."""


class TransferDirectoryError(ModuleFrameworkDesignError):
    """Raised when problem with transferring directory occurs."""


class RemoteProcessInvalidState(ModuleFrameworkDesignError):
    """Raised when RemoteProcess is in an invalid state to perform an operation."""


class RemoteProcessStreamNotAvailable(ModuleFrameworkDesignError):
    """Raised if an attempt is made to access a non-existent output stream (stdout or stderr)."""


class SSHReconnectException(ModuleFrameworkDesignError):
    """Handling ssh reconnection failure."""


class SSHTunnelException(ModuleFrameworkDesignError):
    """Handling sshtunnel exceptions."""


class SolException(ModuleFrameworkDesignError):
    """Handling exceptions in SolConnection class."""


class SerialException(ModuleFrameworkDesignError):
    """Handling exceptions in SerialConnection class."""


class TelnetException(ModuleFrameworkDesignError):
    """Handling exceptions in TelnetConnection class."""


class OsNotSupported(ModuleFrameworkDesignError):
    """Raises when OS is not supported."""


class CPUArchitectureNotSupported(ModuleFrameworkDesignError):
    """Raises when CPU Architecture is not supported."""


class SSHRemoteProcessEndException(ModuleFrameworkDesignError):
    """Handle exceptions with stop/kill ssh process."""


class RPyCZeroDeployException(ModuleFrameworkDesignError):
    """Handle zero deploy rpyc exceptions."""


class IncorrectAffinityMaskException(ModuleFrameworkDesignError):
    """Handle exception for incorrect CPU affinity mask format."""


class SSHPIDException(ModuleFrameworkDesignError):
    """Handle problems with ssh pids."""


class PathExistsError(FileExistsError, ModuleFrameworkDesignError):
    """Handle exceptions to existing file or directory."""


class PathNotExistsError(FileNotFoundError, ModuleFrameworkDesignError):
    """Handle exceptions for checking path existing."""


class GatheringSystemInfoError(ModuleFrameworkDesignError):
    """Handle exceptions for gathering system details."""


class NotAFileError(ModuleFrameworkDesignError):
    """Handle exceptions when method dedicated for file is called on directory path."""


class UnavailableServerException(ModuleFrameworkDesignError):
    """Handle exceptions when server is unavailable."""


class ProcessNotRunning(ModuleFrameworkDesignError):
    """Handle exceptions when Process is not running."""


class RPyCDeploymentException(ModuleFrameworkDesignError):
    """Handle exceptions when deployment found issue."""


class MissingPortablePythonOnServerException(RPyCDeploymentException):
    """Handle exceptions when not found portable python on server."""


class WinRMException(ModuleFrameworkDesignError):
    """Handling exceptions in WinRM class."""


class PathException(ModuleFrameworkDesignError):
    """Handling exceptions related to Path."""


class PxsshException(ModuleFrameworkDesignError):
    """Handling exceptions in PxsshConnection class."""


class InteractiveSSHException(ModuleFrameworkDesignError):
    """Handling exceptions in InteractiveSSHConnection class."""


class CopyException(ModuleFrameworkDesignError):
    """Handling exceptions in copy operations."""
