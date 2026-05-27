# Rentablez Hardware Fingerprint Agent

Boot-time hardware fingerprint collector. Detects part swaps on rental laptops by comparing each boot against a baseline captured at warehouse setup.

## What you need

- A laptop in its final shipped configuration (correct RAM, SSD, battery, etc.).
- The device token assigned to this laptop (format: `RTBZ-LAP-<5+ digits>`).
- Administrator/root access to the laptop.
- Internet helpful but not required — offline reports queue locally and send on next boot.

## macOS install

```bash
sudo ./setup_mac.sh
```

You'll be prompted for the device token. The script will:
1. Copy the agent into `/usr/local/rentablez/`.
2. Write `/etc/rentablez/config.json` with the token.
3. Register the LaunchDaemon and run it immediately, which captures the baseline.

Verify:
```bash
launchctl list | grep com.rentablez.agent
cat /var/lib/rentablez/baseline.json | python3 -m json.tool | head
tail /var/log/rentablez/agent.log
```

## Windows install

Open PowerShell as Administrator:
```powershell
cd path\to\rentablez-agent
.\setup_windows.ps1
```

The script installs Python 3.12 via winget if missing, then registers the agent as a Windows Service (wrapped with nssm).

Verify:
```powershell
sc query RentablezAgent
Get-Content C:\ProgramData\Rentablez\baseline.json | Select-Object -First 30
Get-Content C:\ProgramData\Rentablez\logs\agent.log -Tail 20
```

## Uninstall

`sudo ./uninstall_mac.sh` or `.\uninstall_windows.ps1` (as Administrator).

These preserve `baseline.json` so reinstalling on the same laptop reuses the original baseline. To fully wipe (e.g., before reselling), delete the state directory manually — instructions are printed at the end of the uninstall.

## Resetting the baseline

If a laptop legitimately had hardware replaced (warranty repair, RAM upgrade) and you want to re-establish the baseline:

**macOS:**
```bash
sudo rm /var/lib/rentablez/baseline.json
sudo launchctl kickstart -k system/com.rentablez.agent
```

**Windows:**
```powershell
Remove-Item C:\ProgramData\Rentablez\baseline.json
Restart-Service RentablezAgent
```

The next run writes a new baseline and reports it to the backend with `status: "baseline"` (auditable).

## Troubleshooting

| Symptom | Check |
|---|---|
| No reports reaching backend | `tail /var/log/rentablez/agent.log` (or Windows log path). Look for HTTP errors or `config load failed`. |
| Setup says token format invalid | The regex is `^RTBZ-LAP-\d{5,}$`. No extra spaces. |
| Service won't start (macOS) | `sudo launchctl print system/com.rentablez.agent` — look for `last exit code`. |
| Service won't start (Windows) | `Get-EventLog -LogName System -Source "Service Control Manager" -Newest 20` |
| Queue not draining | `cat /var/lib/rentablez/queue.json` — `attempts` and `last_attempt_at` show what's been tried. Next boot retries. |

## Development

Tests are pytest-based. From the repo root:
```bash
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/pytest -v
```

No third-party dependencies are needed by the agent itself — only Python stdlib. pytest is dev-only.

Source layout:
```
rentablez/
├── paths.py          per-OS file paths
├── normalize.py      serial-number normalization
├── config.py         config.json loader
├── diff.py           baseline-vs-current fingerprint comparison
├── report.py         JSON payload builder
├── queue.py          persistent JSON queue with retention
├── sender.py         HTTPS POST with retry classification
├── logger.py         rotating file logger
├── runner.py         boot-time orchestration
└── collectors/       per-OS hardware collectors
    ├── mac.py        system_profiler-based
    └── windows.py    PowerShell/WMI-based
rentablez_agent.py    entrypoint invoked by launchd / nssm
```

See `docs/superpowers/specs/2026-05-26-rentablez-agent-design.md` for the design rationale.
