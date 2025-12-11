# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for custom PathLib."""

import logging
import re
import sys
import typing
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Union, Optional

from mfd_common_libs import add_logging_level, log_levels
from mfd_typing.os_values import OSType, OSName

from mfd_connect.exceptions import NotAFileError, ModuleFrameworkDesignError

logger = logging.getLogger(__name__)

add_logging_level(level_name="MODULE_DEBUG", level_value=log_levels.MODULE_DEBUG)

if typing.TYPE_CHECKING:
    from mfd_connect import Connection
    from typing import Iterable


def custom_path_factory(*args, **kwargs) -> "CustomPath":
    """
    Create a custom path based on the OS type.

    :param args: Positional arguments for path creation
    :param kwargs: Keyword arguments for path creation, including 'owner'
    :return: CustomPath object based on the OS type
    """
    owner = kwargs.get("owner")
    if owner.get_os_name() == OSName.EFISHELL:
        return CustomEFIShellPath(*args, **kwargs)
    elif owner.get_os_type() == OSType.WINDOWS:
        return CustomWindowsPath(*args, **kwargs)
    else:
        return CustomPosixPath(*args, **kwargs)


class CustomPath(PurePath):
    """Class for custom Path."""

    def __new__(cls, *args, **kwargs) -> "CustomPath":
        """
        Create a new CustomPath object.

        For Python 3.10 - Detect the OS type and create the appropriate path class.
        For Python 3.12 and later - Use the built-in PurePath functionality.
        :param cls: Class type to create
        :param args: Positional arguments for path creation
        :param kwargs: Keyword arguments for path creation, including 'owner'

        :raises Exception: If 'owner' is not provided in kwargs for SSHPath
        :return: Correct Path object
        """
        if sys.version_info < (3, 12):  # pragma: no cover
            owner = kwargs.get("owner")
            if owner is None:
                raise Exception("Connection is required in CustomPath.")
            if cls is CustomPath:
                if owner.get_os_name() == OSName.EFISHELL:
                    cls = CustomEFIShellPath
                else:
                    cls = CustomWindowsPath if owner.get_os_type() == OSType.WINDOWS else CustomPosixPath
            cls._owner = owner
            return cls._from_parts(args)
        else:
            return super().__new__(cls, *args, **kwargs)

    def __init__(self, *args, **kwargs) -> "CustomPath":
        """
        Initialize CustomPath.

        For Python 3.10 - Set _owner attribute if provided in kwargs (still keeping the object in kwargs).
        For Python 3.12+ - Set _owner attribute if it is not already set, and remove it from kwargs.

        :return: "CustomPath" object initialized with the provided arguments.
        """
        if sys.version_info >= (3, 12):
            if not hasattr(self, "_owner"):
                self._owner = kwargs.pop("owner")
                return super(CustomPath, self).__init__(*args, **kwargs)
        else:
            self._owner = kwargs.get("owner")

    if sys.version_info >= (3, 12):  # pragma: no cover

        def __truediv__(self, key: str) -> "CustomPath":
            """
            Create a new path by appending a key to the current path.

            :param key: The key to append to the path.
            :return: CustomPath object representing the new path.
            """
            try:
                return custom_path_factory(self, key, owner=self._owner)
            except TypeError:
                return NotImplemented

        def __rtruediv__(self, key: str) -> "CustomPath":  # pragma: no cover
            """
            Create a new path by prepending a key to the current path.

            :param key: The key to prepend to the path.
            :return: CustomPath object representing the new path.
            """
            try:
                return custom_path_factory(key, self, owner=self._owner)
            except TypeError:
                return NotImplemented

        def with_suffix(self, suffix: str) -> "CustomPath":
            """Return a new path with the file suffix changed.

            If the path has no suffix, add given suffix.
            If the given suffix is an empty string, remove the suffix from the path.

            :param suffix: The suffix to set for the path.
            :return: CustomPath object with the new suffix.
            """
            stem = self.stem
            if not stem:
                # If the stem is empty, we can't make the suffix non-empty.
                raise ValueError(f"{self!r} has an empty name")
            elif suffix and not (suffix.startswith(".") and len(suffix) > 1):
                raise ValueError(f"Invalid suffix {suffix!r}")
            else:
                return self.with_name(stem + suffix)

        def with_name(self, name: str) -> "CustomPath":
            """Return a new path with the file name changed."""
            if sys.version_info > (3, 13):
                p = self.parser
                if not name or p.sep in name or (p.altsep and p.altsep in name) or name == ".":
                    raise ValueError(f"Invalid name {name!r}")
                tail = self._tail.copy()
                if not tail:
                    raise ValueError(f"{self!r} has an empty name")
                tail[-1] = name
                return self._from_parsed_parts_py3_12(self.drive, self.root, tail)
            else:
                if not self.name:
                    raise ValueError("%r has an empty name" % (self,))
                f = self._flavour
                if not name or f.sep in name or (f.altsep and f.altsep in name) or name == ".":
                    raise ValueError("Invalid name %r" % (name))
                return self._from_parsed_parts_py3_12(self.drive, self.root, self._tail[:-1] + [name])
    else:

        def __truediv__(self, key: str) -> "CustomPath":
            try:
                child = super().__truediv__(key)
                child._owner = self._owner
                return child
            except TypeError:
                return NotImplemented

        def __rtruediv__(self, key: str) -> "CustomPath":
            try:
                child = super().__rtruediv__(key)
                child._owner = self._owner
                return child
            except TypeError:
                return NotImplemented

    @property
    def parent(self) -> "CustomPath":  # pragma: no cover
        """
        Get the logical parent of the path.

        :return: CustomPath object representing the parent directory.
        """
        if sys.version_info < (3, 12):
            drv = self._drv
            root = self._root
            parts = self._parts
            if len(parts) == 1 and (drv or root):
                return self
            return self._from_parsed_parts(drv, root, parts[:-1], self._owner)  # class method called
        else:
            drv = self.drive
            root = self.root
            tail = self._tail
            if not tail:
                return self
            return self._from_parsed_parts_py3_12(drv, root, tail[:-1])  # instance method called

    if sys.version_info < (3, 12):

        @classmethod
        def _from_parsed_parts(
            cls: "CustomPath", drv: str, root: str, parts: str, owner: "Connection" = None
        ) -> "CustomPath":
            """
            Create a new path from parsed parts.

            :param drv: Drive part of the path
            :param root: Root part of the path
            :param parts: Path parts
            :param owner: Connection object, required for creating CustomPath
            :return: CustomPath object
            """
            if owner is not None:
                self = cls.__new__(cls, owner=owner)
            else:
                self = object.__new__(cls)
            self._drv = drv
            self._root = root
            self._parts = parts
            return self

    def _from_parsed_parts_py3_12(self, drv: str, root: str, tail: str) -> "CustomPath":
        """
        Create a new path from parsed parts for Python 3.12 and later.

        :param drv: Drive part of the path
        :param root: Root part of the path
        :param tail: Tail parts of the path
        :return: CustomPath object
        """
        path = custom_path_factory(self._format_parsed_parts(drv, root, tail), owner=self._owner)
        path._drv = drv
        path._root = root
        path._tail_cached = tail
        return path

    def rmdir(self) -> None:
        """
        Remove a directory.

        :raises FileNotFoundError: if directory doesn't exist
        """
        if not self.exists():
            raise FileNotFoundError(f"{self} does not exist")

    def exists(self) -> bool:
        """Whether this path exists."""
        raise NotImplementedError("Exists method is not implemented.")

    def expanduser(self) -> "CustomPath":
        """Return a new path with expanded ~ and ~user constructs."""
        raise NotImplementedError("Expanduser method is not implemented.")

    def is_file(self) -> bool:
        """Whether this path is a regular file."""
        raise NotImplementedError("Is_file method is not implemented.")

    def is_dir(self) -> bool:
        """Whether this path is a directory."""
        raise NotImplementedError("Is_dir method is not implemented.")

    def chmod(self, mode: int) -> None:
        """
        Change the access permissions of a file.

        :param mode: Operating-system mode bitfield. eg. 0o775
        """
        raise NotImplementedError("Chmod method is not implemented.")

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        """
        Create a new directory at this path.

        :param mode: If mode is given, it is combined with the process’ umask value to determine the file mode
        and access flag

        :param parents: If parents is true, any missing parents of this path are created as needed; they are created
        with the default permissions without taking mode into account (mimicking the POSIX mkdir -p command).
                If parents is false (the default), a missing parent raises FileNotFoundError.

        :param exist_ok: If exist_ok is false (the default), FileExistsError is raised if the target directory
        already exists. If exist_ok is true, FileExistsError exceptions will be ignored
        (same behavior as the POSIX mkdir -p command), but only if the last path component is not an existing
        non-directory file.

        :raise FileNotFoundError: If parents is false (the default), a missing parent raises FileNotFoundError.
        :raise FileExistsError: If the path already exists, FileExistsError is raised.

        """
        raise NotImplementedError("Mkdir method is not implemented.")

    def rename(self, new_name: "CustomPath") -> "CustomPath":
        """
        Rename a file or directory, overwriting the destination.

        :param new_name: SSHPath object for new file
        :return: Object of new file
        """
        raise NotImplementedError("Rename method is not implemented.")

    def samefile(self, other_path: "CustomPath") -> bool:
        """Return whether other_path is the same or not as this file."""
        raise NotImplementedError("Samefile method is not implemented.")

    def read_text(self, encoding: Optional[str] = None, errors: Optional[str] = None) -> str:
        """
        Show the file as text.

        Encoding and errors not supported.
        :return: Read file string
        """
        raise NotImplementedError("Read_text method is not implemented.")

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        """Create this file with the given access mode, if it doesn't exist."""
        raise NotImplementedError("Touch method is not implemented.")

    def _get_verified_copy_target(self, target: Union["CustomPath", str]) -> "CustomPath":
        if not self.exists():
            raise FileNotFoundError(f"{self} does not exist!")
        if isinstance(target, str):
            target = CustomPath(target, owner=self._owner)
        if target.exists():
            raise FileExistsError(f"{target} already exist!")
        return target

    def write_text(self, data: str, encoding: str = None, errors: str = None, newline: str = None) -> int:
        """
        Write text to file.

        :param data: Text to write
        :param encoding: Encoding used to convert string to bytes
        :param errors: specifies how encoding and decoding errors are to be handled
        :param newline: Controls how line endings are handled
        :returns: Number of characters written
        """
        raise NotImplementedError("Write_text method is not implemented.")

    def unlink(self) -> None:
        """
        Remove file.

        :raises: NotAFileError when method is called not on a file path.
                 FileNotFoundError when file deleting already doesn't exist.
        """
        if not self.exists():
            raise FileNotFoundError(f"{self} does not exist")
        if not self.is_file():
            raise NotAFileError(f"{self} is not a file, please call 'rmdir' for deleting instead.")


class CustomPosixPath(CustomPath, PurePosixPath):
    """Class for Posix Path."""

    def exists(self) -> bool:  # noqa:D102
        outcome = self._owner.execute_command(f"ls {self}", expected_return_codes=None)
        output = outcome.stderr if outcome._stderr is not None else outcome.stdout
        if "permission denied".casefold() in output.casefold():
            raise ModuleFrameworkDesignError(f"Error occurred for CustomPosixPath.exists():\n{output}")
        return outcome.return_code == 0

    def expanduser(self) -> CustomPath:  # noqa:D102
        homedir = self._owner.execute_command(
            'echo $(getent passwd "$USER" | cut -d: -f6)', expected_return_codes=None
        ).stdout.strip()  # remove newline flag
        if sys.version_info < (3, 12):
            if not (self._drv or self._root) and self._parts and self._parts[0][:1] == "~":
                return CustomPosixPath(f"{str(self).replace('~', homedir)}", owner=self._owner)
            return self
        else:
            return CustomPosixPath(f"{str(self).replace('~', homedir)}", owner=self._owner)

    def is_file(self) -> bool:  # noqa:D102
        result = self._owner.execute_command(f"ls -la {self} ", expected_return_codes=None)
        return result.return_code == 0 and result.stdout[0] == "-"

    def is_dir(self) -> bool:  # noqa:D102
        result = self._owner.execute_command(f"ls -lad {self}", expected_return_codes=None)
        return result.return_code == 0 and result.stdout[0] == "d"

    def chmod(self, mode: int) -> None:  # noqa:D102
        self._owner.execute_command(f"chmod {mode:o} {self}", expected_return_codes=None)

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:  # noqa:D102
        if not exist_ok and self.exists():
            raise FileExistsError(f"{self} file exists")
        mkdir_command = f"mkdir {self}"
        if parents:
            mkdir_command += " -p"
        outcome = self._owner.execute_command(mkdir_command, expected_return_codes=None)
        output = outcome.stderr if outcome._stderr is not None else outcome.stdout
        if "cannot create directory".casefold() in output.casefold():
            raise ModuleFrameworkDesignError(f"Error occurred for CustomPosixPath.mkdir():\n{output}")
        self.chmod(mode)

    def rename(self, new_name: CustomPath) -> CustomPath:  # noqa:D102
        if new_name.exists():
            raise FileExistsError(f"{new_name} file exists")
        self._owner.execute_command(f"mv {self} {new_name}", expected_return_codes=None)
        return new_name

    def samefile(self, other_path: CustomPath) -> bool:  # noqa:D102
        return (
            self._owner.execute_command(
                f"diff {self} {other_path}", expected_return_codes=None, discard_stdout=True
            ).return_code
            == 0
        )

    def read_text(self, encoding: Optional[str] = None, errors: Optional["Iterable"] = None) -> str:  # noqa:D102
        proc = self._owner.start_process(f"cat {self}")
        return "".join(chunk for chunk in proc.get_stdout_iter())

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:  # noqa:D102
        if not exist_ok and self.is_file():
            raise FileExistsError(f"{self} file exists")
        create_file_command = f"touch {self}"
        self._owner.execute_command(create_file_command, expected_return_codes=None)
        self.chmod(mode)

    def rmdir(self) -> None:  # noqa:D102
        super(CustomPosixPath, self).rmdir()
        outcome = self._owner.execute_command(f"rm -rf {self}", expected_return_codes=None)
        output = outcome.stderr if outcome._stderr is not None else outcome.stdout
        if "permission denied".casefold() in output.casefold():
            raise ModuleFrameworkDesignError(f"Error occurred in CustomPosixPath.rmdir():\n{output}")

    def unlink(self) -> None:  # noqa:D102
        super(CustomPosixPath, self).unlink()
        self._owner.execute_command(f"rm -rf {str(self)}", expected_return_codes=None)

    def write_text(self, data: str, encoding: str = None, errors: str = None, newline: str = None) -> int:
        """
        Write text to file using echo.

        :param data: Text to write
        :param encoding: Encoding used to convert string to bytes
        :param errors: Not used
        :param newline: Not used
        :returns: Number of characters written
        """
        if encoding:
            command = f'echo -e "{data}" | iconv --to-code={encoding} > {self}'
        else:
            command = f'echo -e "{data}" > {self}'
        self._owner.execute_command(command, shell=True)
        return len(data)


class CustomWindowsPath(CustomPath, PureWindowsPath):
    """Class for Windows Path."""

    def expanduser(self) -> CustomPath:  # noqa:D102
        # remove newline flag by strip
        homedir = self._owner.execute_command("echo %USERPROFILE%", expected_return_codes=None).stdout.strip()
        if sys.version_info < (3, 11):
            if not (self._drv or self._root) and self._parts and self._parts[0][:1] == "~":
                return CustomWindowsPath(f"{str(self).replace('~', homedir)}", owner=self._owner)
            return self
        else:
            return CustomWindowsPath(f"{str(self).replace('~', homedir)}", owner=self._owner)

    def samefile(self, other_path: CustomPath) -> bool:  # noqa:D102
        return self._owner.execute_command(f"fc {self} {other_path} >NUL", expected_return_codes=None).return_code == 0

    def exists(self) -> bool:  # noqa:D102
        try:
            return (
                self._owner.execute_command(
                    f"dir {self}", expected_return_codes=None, custom_exception=FileNotFoundError
                ).return_code
                == 0
            )
        except FileNotFoundError as ex:
            logger.log(level=log_levels.MODULE_DEBUG, msg=ex)
            return False

    def is_file(self) -> bool:  # noqa:D102
        result = self._owner.execute_command(f"dir {self}", expected_return_codes=None)
        expected_outputs = ["1 File", "0 Dir"]
        return result.return_code == 0 and all(expected_output in result.stdout for expected_output in expected_outputs)

    def is_dir(self) -> bool:  # noqa:D102
        result = self._owner.execute_command(f"dir {self}", expected_return_codes=None)
        return result.return_code == 0 and f"Directory of {self}" in result.stdout

    def rename(self, new_name: CustomPath) -> CustomPath:  # noqa:D102
        if not self.exists():
            raise FileNotFoundError(f"{self} does not exist")
        if new_name.exists():
            raise FileExistsError(f"{new_name} path exists")
        self._owner.execute_command(f'ren "{self}" "{new_name.name}"', expected_return_codes=[0])
        return new_name

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:  # noqa:D102
        if mode:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Creating directory with mode is not implemented on Windows")
        if not exist_ok and self.is_file():
            raise FileExistsError(f"{self} path exists")
        if parents:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Creating parent path is not implemented on Windows")
        self._owner.execute_command(f"mkdir {self}", expected_return_codes=None)

    def read_text(self, encoding: Optional[str] = None, errors: Optional["Iterable"] = None) -> str:  # noqa:D102
        return self._owner.execute_command(f"type {self}", expected_return_codes=None).stdout

    def touch(self, mode: int = None, exist_ok: bool = True) -> None:  # noqa:D102
        if mode:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Creating directory with mode is not implemented on Windows")
        if not exist_ok and self.is_file():
            raise FileExistsError(f"{self} file exists")
        create_file_command = f"type nul >> {self}"
        self._owner.execute_command(create_file_command, expected_return_codes={0})

    def rmdir(self) -> None:  # noqa:D102
        super(CustomWindowsPath, self).rmdir()
        # This will remove your folder including all its subfolders and files within them
        self._owner.execute_command(f"rmdir /q /s {self}", shell=True, expected_return_codes=None)

    def unlink(self) -> None:  # noqa:D102
        super(CustomWindowsPath, self).unlink()
        self._owner.execute_command(f"del /f {self}", shell=True, expected_return_codes=None)

    def write_text(self, data: str, encoding: str = None, errors: str = None, newline: str = None) -> int:
        r"""
        Write text to file using Powershell.

        Interpret only line break characters \n and \r

        :param data: Text to write
        :param encoding: Specifies the type of encoding for the target file Default utf8NoBOM
        :param errors: Not used
        :param newline: Not used
        :returns: Number of characters written
        """
        # need to change line breakers into powershell format
        data = data.replace("\n", "`n").replace("\r", "`r")
        powershell_command = rf"\"{data}\" | Out-File {self}"
        if encoding:
            powershell_command += f" -encoding {encoding}"
        command = f'powershell -command "{powershell_command}"'
        self._owner.execute_command(command, shell=True)
        return len(data)


class CustomEFIShellPath(CustomWindowsPath):
    """Class for EFI Shell Path."""

    def rmdir(self) -> None:  # noqa:D102
        if not self.exists():
            raise FileNotFoundError(f"{self} does not exist")
        self._owner.execute_command(f"rm {self}", expected_return_codes=None)

    def exists(self) -> bool:  # noqa:D102
        return self._owner.execute_command(f"ls {self}", expected_return_codes=range(0, 254)).return_code == 0

    def expanduser(self) -> CustomPath:  # noqa:D102
        raise NotImplementedError("expanduser is not supported for EFISHELL")

    def is_file(self) -> bool:  # noqa:D102
        return "1 File" in self._owner.execute_command(f"ls {self}", expected_return_codes=range(0, 254)).stdout

    def is_dir(self) -> bool:  # noqa:D102
        return self._owner.execute_command(f"ls {self} -ad", expected_return_codes=range(0, 254)).return_code == 0

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:  # noqa:D102
        if mode:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Creating directory with mode is not implemented on EFISHELL")
        if not exist_ok and self.is_file():
            raise FileExistsError(f"{self} file exists")
        create_file_command = f"echo > {self}"
        self._owner.execute_command(create_file_command, expected_return_codes=None)

    def samefile(self, other_path: CustomPath) -> bool:  # noqa:D102
        return (
            "no differences"
            in self._owner.execute_command(f"comp {self} {other_path}", expected_return_codes=None).stdout
        )

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:  # noqa:D102
        if mode:
            logger.log(level=log_levels.MODULE_DEBUG, msg="Creating directory with mode is not implemented on EFISHELL")
        if not exist_ok and self.is_file():
            raise FileExistsError(f"{self} file exists")
        if not parents:
            logger.log(level=log_levels.MODULE_DEBUG, msg="In EFI Shell parent directories are created always")
        self._owner.execute_command(f"mkdir {self}", expected_return_codes=None)

    def rename(self, new_name: CustomPath) -> CustomPath:  # noqa:D102
        if new_name.exists():
            raise FileExistsError(f"{new_name} file exists")
        self._owner.execute_command(f"mv {self} {new_name}", expected_return_codes=None)
        return new_name

    def chmod(self, mode: int) -> None:  # noqa:D102
        raise NotImplementedError("Chmod is not supported for EFISHELL")

    def read_text(self, encoding: Optional[str] = None, errors: Optional["Iterable"] = None) -> str:  # noqa:D102
        # when cwd is as root directory, stdout contain part of prompt, need to check and exclude it from result
        pattern = re.compile(r"FS\d:")
        result = self._owner.execute_command(f"cat {self}", expected_return_codes=None)
        if pattern.search(result.stdout):
            return "\n".join(result.stdout.splitlines()[:-1])
        else:
            return result.stdout

    def write_text(self, data: str, encoding: str = None, errors: str = None, newline: str = None) -> int:
        r"""
        Write text to file using echo.

        Doesn't interpret special characters eg. \n

        :param data: Text to write
        :param encoding: Not used
        :param errors: Not used
        :param newline: Not used
        :returns: Number of characters written
        """
        command = f'echo "{data}" > {self}'
        self._owner.execute_command(command, shell=True)
        return len(data)

    def unlink(self) -> None:
        """
        Remove file.

        :raises: NotAFileError when method is called not on a file path.
                 FileNotFoundError when file deleting already doesn't exist.
        """
        raise NotImplementedError("Method: 'unlink' for file removing is not implemented.")
