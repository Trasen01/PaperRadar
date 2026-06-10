# Installation

## Windows Installer

Download `PaperRadar_Setup_vX.Y.Z.exe` and run it.

The installer places program files under:

```text
C:\Program Files\PaperRadar\
```

If you choose current-user installation in the installer, Inno Setup may use a per-user programs directory instead.

## User Data

PaperRadar stores user data under:

```text
%APPDATA%\PaperRadar\
```

This folder contains settings, research Profiles, the SQLite database, reports, and logs. Updating or uninstalling the program does not remove this folder by default.

## Complete Removal

To fully remove PaperRadar data after uninstalling the program, manually delete:

```text
%APPDATA%\PaperRadar\
```
