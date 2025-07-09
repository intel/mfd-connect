# Custom Pathlib
Module for manipulating path via alternative Connection (such as SSHConnection, SolConnection). Module autodetect correct path class.
## Usage
```python
conn = SSHConnection(username="", password='', ip="")
f = conn.path(r'~/logs.txt')
content = f.read_text()
print(content)
```
## Supported path
* PosixPath
* WindowsPath
* EFIShellPath

## Supported methods
```python
rmdir()
    """
    Remove a directory.

    :raises FileNotFoundError: if directory doesn't exist
    """
```
```python
exists()
    """Whether this path exists."""
```
```python
expanduser()
    """Return a new path with expanded ~ and ~user constructs."""
```
```python
is_file()
    """Whether this path is a regular file."""
```
```python
is_dir() 
    """Whether this path is a directory."""
```
```python
chmod(mode)
    """
    Change the access permissions of a file.

    :param mode: Operating-system mode bitfield.
    """
```
```python
mkdir(mode=0o777, parents: bool = False, exist_ok: bool = False)
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
```
```python
rename(new_name: 'SSHPath')
    """
    Rename a file or directory, overwriting the destination.

    :param new_name: SSHPath object for new file
    :return: Object of new file
    """
```
```python
samefile(other_path: 'SSHPath')
    """Return whether other_path is the same or not as this file."""
```
```python
read_text(encoding=None, errors=None)
    """Show the file as text."""
```
```python
touch(mode=0o666, exist_ok: bool = True):
    """Create this file with the given access mode, if it doesn't exist."""
```
```python
unlink()
    """
    Remove file.

    :raises: NotAFile error when method is called not on a file path.
             FileNotFoundError when file deleting already doesn't exist.
    """
```
```python
write_text(data: str, encoding: str = None, errors: str = None, newline: str = None):
    """
    Write text to file.
    
    :param data: Text to write
    :param encoding: Encoding used to convert string to bytes
    :param errors: specifies how encoding and decoding errors are to be handled
    :param newline: Controls how line endings are handled
    :returns: Number of characters written
    """
```

Supported encoding for **Windows**:
* ascii: Uses the encoding for the ASCII (7-bit) character set.
* bigendianunicode: Encodes in UTF-16 format using the big-endian byte order.
* bigendianutf32: Encodes in UTF-32 format using the big-endian byte order.
* oem: Uses the default encoding for MS-DOS and console programs.
* unicode: Encodes in UTF-16 format using the little-endian byte order.
* utf7: Encodes in UTF-7 format.
* utf8: Encodes in UTF-8 format.
* utf8BOM: Encodes in UTF-8 format with Byte Order Mark (BOM)
* utf8NoBOM: Encodes in UTF-8 format without Byte Order Mark (BOM)
* utf32: Encodes in UTF-32 format.

Some supported encoding for **Posix**, rest available with `iconv -l` command:
* UTF-7
* UTF-8
* UTF-16
* UTF-16BE
* UTF-16LE
* UTF-32
* UTF-32BE
* UTF-32LE
* UTF7
* UTF8
* UTF16
* UTF16BE
* UTF16LE
* UTF32
* UTF32BE
* UTF32LE
* VISCII
* WCHAR_T
* WIN-SAMI-2
* WINBALTRIM
* WINDOWS-31J
* WINDOWS-874
* WINDOWS-936
* WINDOWS-1250
* WINDOWS-1251
* WINDOWS-1252
* WINDOWS-1253
* WINDOWS-1254
* WINDOWS-1255
* WINDOWS-1256
* WINDOWS-1257
* WINDOWS-1258
* WINSAMI2
* WS2
* YU
