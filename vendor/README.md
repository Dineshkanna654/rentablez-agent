# Vendored binaries

## nssm.exe

Source: https://nssm.cc/release/nssm-2.24.zip

To refresh:
1. Download the zip from the URL above.
2. Extract `nssm-2.24/win64/nssm.exe`.
3. Place it at `vendor/nssm.exe` in this repo.
4. Verify SHA-256 against the official release notes.

This binary is bundled because target Windows laptops will not have it pre-installed and we don't want the setup script to download from the internet (the laptop may be offline at setup time).
