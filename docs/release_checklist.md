# Release Checklist

1. Update the version number.
2. Run the test suite.
3. Start the development build with `python run.py`.
4. Confirm user data under `%APPDATA%\PaperRadar` is not overwritten.
5. Clean `build` and `dist`.
6. Run `build_scripts\build_exe.ps1`.
7. Run `build_scripts\build_installer.ps1`.
8. Install the generated setup package.
9. Test overwrite installation from the previous version.
10. Confirm old user Profiles are preserved.
11. Confirm `papers.sqlite` is preserved.
12. Check the desktop shortcut.
13. Check the Start Menu shortcut.
14. Check launch after install.
15. Update README if needed.
16. Commit changes.
17. Create a Git tag.
18. Create a GitHub Release and upload the installer.
