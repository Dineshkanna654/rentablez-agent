# Rentablez Hardware Fingerprint Agent — Design

**Date:** 2026-05-26
**Status:** Approved for implementation planning
**Author:** Rentablez

## 1. Purpose

A background agent that runs on every rental laptop (macOS and Windows). On each boot, it collects a hardware fingerprint, compares it against a baseline captured on the first boot, and reports the result to the Rentablez backend. Its sole job is to detect and report part swaps (RAM, SSD, battery, display, etc.) that may occur during a rental.

## 2. Goals

- Detect hardware part swaps with high confidence and specific attribution (which component, old value, new value).
- Survive offline periods — queue results locally and drain when internet returns.
- Install once at the warehouse and run untouched for the laptop's entire life across multiple rentals.
- Ship as plain Python scripts plus a one-shot setup shell/PowerShell script per platform. No installer binaries, no signing, no `.dmg`, no `.exe`.

## 3. Non-goals (v1)

- No auto-update mechanism. New versions are installed manually by warehouse staff.
- No tray icon, GUI, or user-facing surface after installation.
- No real-time tamper detection — boot-time only.
- No claim / activation flow — the device token is entered manually at install time.
- No remote command execution, kill switches, or screen locking.
- No anti-tamper hardening beyond standard OS service permissions.
- No code signing, no notarization, no installer packaging. The script and setup files are distributed as-is (e.g. internal git repo or shared drive). Warehouse staff run them directly with `sudo` / Administrator.

## 4. Architecture

### 4.1 Components

```
Renter's laptop                                  Rentablez backend
─────────────────────────                        ──────────────────
                                                 
  Boot                                           
   │                                             
   ▼                                             
  ┌──────────────────────┐                       ┌───────────────────────┐
  │ rentablez-agent      │  HTTPS (when online)  │ POST /devices/checkin │
  │  (LaunchDaemon /     │ ─────────────────────►│                       │
  │   Windows Service)   │                       │ Stores baseline,      │
  │                      │                       │ diffs subsequent      │
  │  reads config.json   │                       │ reports, alerts ops   │
  │  reads/writes        │                       │ on SWAPPED status.    │
  │  baseline.json,      │                       └───────────────────────┘
  │  current.json,       │                       
  │  queue.json          │                       
  └──────────────────────┘                       
```

A single executable runs as a privileged background service. There is no second process and no user-facing UI.

### 4.2 Filesystem layout

**macOS:**
```
/usr/local/rentablez/rentablez_agent.py   (the script itself, mode 0755, root:wheel)
/Library/LaunchDaemons/com.rentablez.agent.plist
/etc/rentablez/config.json                (mode 0600, root:wheel)
/var/lib/rentablez/baseline.json          (mode 0600, root:wheel)
/var/lib/rentablez/current.json           (mode 0600, root:wheel)
/var/lib/rentablez/queue.json             (mode 0600, root:wheel)
/var/log/rentablez/agent.log              (mode 0644, root:wheel)
```

**Windows:**
```
C:\Rentablez\rentablez_agent.py                  (the script itself)
HKLM\System\CurrentControlSet\Services\RentablezAgent  (Windows Service)
C:\ProgramData\Rentablez\config.json             (ACL: SYSTEM + Administrators only)
C:\ProgramData\Rentablez\baseline.json
C:\ProgramData\Rentablez\current.json
C:\ProgramData\Rentablez\queue.json
C:\ProgramData\Rentablez\logs\agent.log
```

Python interpreter: macOS ships with Python 3 at `/usr/bin/python3`, used directly. Windows: setup script installs Python 3 via `winget install Python.Python.3.12` if not already present, then uses `C:\Python312\python.exe`.

### 4.3 Identity

Each laptop is identified by a `device_token` — a SKU-style string assigned by Rentablez (e.g. `RTBZ-LAP-00042`). It is:

- Entered manually during installation by the warehouse manager.
- Stored in `config.json` and never rotated.
- Sent with every report as the primary key the backend uses to identify the laptop.

The hardware serial number is also collected and reported but is not the identity — the device_token is.

## 5. Boot-time flow

```
                        Boot
                          │
                          ▼
              ┌────────────────────────┐
              │ Service starts         │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ Load config.json       │
              │ → device_token,        │
              │   endpoint             │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │ Collect fingerprint    │
              │ (existing collector    │
              │  code, unchanged)      │
              └───────────┬────────────┘
                          │
                          ▼
                ┌─────────────────────┐
                │ baseline.json       │
                │ exists?             │
                └─────┬────────┬──────┘
                  NO  │        │  YES
                      ▼        ▼
       ┌──────────────────┐  ┌──────────────────┐
       │ Save fingerprint │  │ Load baseline    │
       │ as baseline.json │  │ Diff vs current  │
       │ Build report:    │  └────────┬─────────┘
       │  status=baseline │           │
       └─────────┬────────┘           ▼
                 │             ┌─────────────────┐
                 │             │ Any differences │
                 │             │ in strong-ID    │
                 │             │ fields?         │
                 │             └─┬──────────┬────┘
                 │             NO│          │YES
                 │               ▼          ▼
                 │       ┌──────────┐  ┌──────────────┐
                 │       │ Report   │  │ Report       │
                 │       │ status=  │  │ status=      │
                 │       │ ok       │  │ SWAPPED +    │
                 │       └────┬─────┘  │ changes[]    │
                 │            │        └──────┬───────┘
                 │            │               │
                 └────────────┴───────┬───────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ Save report to         │
                          │ queue.json (sent=false)│
                          └───────────┬────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ Drain queue:           │
                          │  for each unsent row,  │
                          │  POST to endpoint;     │
                          │  on 2xx mark sent.     │
                          │  on failure leave it.  │
                          └───────────┬────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ Write current.json     │
                          │ (latest snapshot, for  │
                          │  debugging)            │
                          └───────────┬────────────┘
                                      │
                                      ▼
                                    Exit
```

The service runs once at boot, then exits. It is not a long-running daemon. `launchd` and Windows Service Control Manager are responsible for invoking it at every boot.

## 6. Comparison logic

### 6.1 Strong-ID fields (always compared, mismatch = SWAPPED)

These are hardware-burned identifiers that should never change for a given laptop:

| Component | Fields compared |
|---|---|
| Machine | `serial_number`, `hardware_uuid` (mac) / `system_uuid` (win) |
| RAM modules | per-slot `serial`, `part_number`, `manufacturer` |
| Storage | per-disk `serial`, `model` |
| Battery | `serial`, `manufacturer`, `device_name` |
| Display | `edid_serial`, `edid_vendor`, `edid_product` |
| GPU | `device_id`, `vendor_id` (PCI IDs — change means card replaced) |
| Network | per-interface MAC address (built-in adapters only) |
| Bluetooth | controller `address` |

### 6.2 Weak-ID fields (collected, NOT compared)

Cycle count, firmware version, OS version, driver version, audio endpoint names, and similar fields change naturally over time. They are included in the report for forensic context but never trigger a SWAPPED status on their own.

### 6.3 Diff algorithm

1. For each strong-ID field, look up the baseline value and the current value.
2. If the baseline has the field and the current is missing it → record as `{old: <val>, new: null, reason: "component_removed"}`.
3. If the current has the field and the baseline is missing it → record as `{old: null, new: <val>, reason: "component_added"}`.
4. If both have it and values differ → record as `{old: <val>, new: <val>, reason: "value_changed"}`.
5. If the `changes[]` array is non-empty → status is `SWAPPED`. Otherwise → `ok`.

**String normalization before comparison:** strip leading/trailing whitespace, collapse internal runs of whitespace to a single space, and uppercase hex-looking serials. Some sources (notably Windows WMI `Win32_PhysicalMemory.SerialNumber`) return values padded with spaces or with inconsistent casing; without normalization these would falsely trigger SWAPPED.

For list-valued components (RAM modules, storage disks, displays), match items between baseline and current by slot/position first; if positions are ambiguous, by serial.

## 7. Report payload

### 7.1 First boot (baseline)

```json
{
  "device_token": "RTBZ-LAP-00042",
  "agent_version": "1.0.0",
  "collected_at": "2026-05-26T10:00:00Z",
  "status": "baseline",
  "os": { ... },
  "fingerprint": { ...full collector output... }
}
```

### 7.2 Subsequent boot, no swap

```json
{
  "device_token": "RTBZ-LAP-00042",
  "agent_version": "1.0.0",
  "collected_at": "2026-05-27T08:14:00Z",
  "status": "ok"
}
```

The full fingerprint is NOT resent on every boot — only the changes are interesting, and the backend already has the baseline.

### 7.3 Subsequent boot, swap detected

```json
{
  "device_token": "RTBZ-LAP-00042",
  "agent_version": "1.0.0",
  "collected_at": "2026-05-27T08:14:00Z",
  "status": "SWAPPED",
  "changes": [
    {
      "component": "ram_modules[0]",
      "field": "serial",
      "old": "SK_Hynix_4F2A8B",
      "new": "Samsung_9C3D1E",
      "reason": "value_changed"
    },
    {
      "component": "storage[0]",
      "field": "serial",
      "old": "Z1ABC123",
      "new": "Z9XYZ789",
      "reason": "value_changed"
    }
  ],
  "current_fingerprint": { ...full collector output... }
}
```

When `SWAPPED`, the full current fingerprint is included so ops can see the new state in full.

## 8. Local storage format

### 8.1 `config.json`

```json
{
  "device_token": "RTBZ-LAP-00042",
  "endpoint": "https://api.rentablez.com/devices/checkin",
  "installed_at": "2026-05-20T14:30:00Z"
}
```

Written by the setup script. Not modified by the agent at runtime.

### 8.2 `baseline.json`

The full fingerprint from first boot. Written once, never modified. If this file is deleted, the next boot will recreate it from the current state — this is a feature (lets ops reset the baseline by removing the file) but the new baseline is also reported to the backend with `status: "baseline"` so it's auditable.

### 8.3 `current.json`

Overwritten on every boot with the latest fingerprint. Used for local debugging only; not authoritative.

### 8.4 `queue.json`

A simple JSON array of pending reports:

```json
[
  {
    "id": "rpt_2026-05-26T10:00:00Z",
    "payload": { ... full report ... },
    "attempts": 0,
    "last_attempt_at": null,
    "sent": false
  }
]
```

Atomic writes: write to `queue.json.tmp`, then `rename()` over `queue.json`. This is safe on both APFS and NTFS.

## 9. Network behavior

### 9.1 Sending

- HTTP POST to `endpoint` (from config) with `Authorization: Bearer <device_token>`.
- Timeout: 30 seconds per request.
- On `2xx` → mark report as `sent: true` in queue.
- On `4xx` (other than 408/429) → mark report as `sent: true` (it's broken, no point retrying) and log loudly.
- On `5xx`, `408`, `429`, or network error → leave as unsent, increment `attempts`.

### 9.2 Offline handling

If the laptop boots without internet, the report sits in `queue.json` indefinitely. The agent only runs at boot, so the queue is drained on the next boot when internet may be available. There is no in-session polling — if the laptop is online during boot, we send; if not, we wait until the next boot.

### 9.3 Queue retention

- Keep up to 100 unsent reports. When the queue is full and a new report needs to be added, drop the *newest* `status: "ok"` report — never drop `baseline` or `SWAPPED` reports, and prefer keeping older entries over newer ones since the oldest unsent report is often the most diagnostically valuable (e.g. the original swap detection).
- If the queue is full and the new report is itself `ok`, drop the new one rather than evicting anything older.
- Reports marked `sent: true` are pruned 7 days after their `last_attempt_at` to keep the file small.

## 10. Service definitions

### 10.1 macOS — LaunchDaemon

`/Library/LaunchDaemons/com.rentablez.agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.rentablez.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/usr/local/rentablez/rentablez_agent.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>/var/log/rentablez/agent.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/rentablez/agent.log</string>
</dict>
</plist>
```

`RunAtLoad: true` + `KeepAlive: false` is exactly the "run once at boot, then exit" behavior. The plist is owned by `root:wheel`, mode `0644`.

### 10.2 Windows — Service

Registered with `sc.exe` during setup. Because we're running a Python script (not a native service binary), the service is wrapped with `nssm` (Non-Sucking Service Manager) which is bundled alongside the setup script:

```
nssm.exe install RentablezAgent "C:\Python312\python.exe" "C:\Rentablez\rentablez_agent.py"
nssm.exe set RentablezAgent Start SERVICE_AUTO_START
nssm.exe set RentablezAgent ObjectName LocalSystem
nssm.exe set RentablezAgent DisplayName "Rentablez Hardware Monitor"
nssm.exe set RentablezAgent AppExit Default Exit
```

`AppExit Default Exit` tells nssm: when the script exits 0, leave the service stopped (don't restart it). The Service Control Manager will start it again on the next boot. This gives us the "run once at boot, then exit" behavior with a plain Python script.

Mac equivalent (`launchd`): no wrapper needed. The plist invokes `/usr/bin/python3 /usr/local/rentablez/rentablez_agent.py` directly, `KeepAlive: false` gives the same one-shot semantics.

## 11. Distribution and setup

### 11.1 Repository layout

A single git repo, distributed internally (private GitHub, shared drive, or USB stick to the warehouse):

```
rentablez-agent/
├── rentablez_agent.py          ← the agent itself (runs on every boot)
├── setup_mac.sh                ← one-shot installer for macOS
├── setup_windows.ps1           ← one-shot installer for Windows
├── uninstall_mac.sh
├── uninstall_windows.ps1
├── com.rentablez.agent.plist   ← LaunchDaemon template
├── vendor/
│   └── nssm.exe                ← bundled for Windows service wrapping
└── README.md                   ← warehouse runbook
```

### 11.2 Setup script behavior — macOS (`setup_mac.sh`)

Run as: `sudo ./setup_mac.sh`

1. Verify running as root. If not, abort.
2. Verify `python3` is available (it is, by default, on every supported macOS version).
3. Prompt: **"Enter device token (provided by Rentablez):"** — read input, validate against `RTBZ-LAP-\d{5,}`, re-prompt on mismatch.
4. `mkdir -p /usr/local/rentablez /etc/rentablez /var/lib/rentablez /var/log/rentablez`.
5. Copy `rentablez_agent.py` to `/usr/local/rentablez/`, `chmod 755`, `chown root:wheel`.
6. Write `/etc/rentablez/config.json` with the entered token, `chmod 600`, `chown root:wheel`.
7. Copy the LaunchDaemon plist to `/Library/LaunchDaemons/`, `chmod 644`, `chown root:wheel`.
8. `launchctl bootstrap system /Library/LaunchDaemons/com.rentablez.agent.plist`.
9. `launchctl kickstart system/com.rentablez.agent` — runs the agent immediately so the baseline is captured right now, not on next reboot.
10. Print the device token back to the operator for visual confirmation.

### 11.3 Setup script behavior — Windows (`setup_windows.ps1`)

Run as: open PowerShell as Administrator, then `.\setup_windows.ps1`.

1. Verify running as Administrator. If not, abort.
2. Check for Python 3.10+ on `PATH`. If missing, run `winget install -e --id Python.Python.3.12 --silent`.
3. Prompt: **"Enter device token (provided by Rentablez):"** — validate format, re-prompt on mismatch.
4. Create directories: `C:\Rentablez`, `C:\ProgramData\Rentablez`, `C:\ProgramData\Rentablez\logs`.
5. Set NTFS ACLs on `C:\ProgramData\Rentablez` so only `SYSTEM` and `Administrators` can read/write.
6. Copy `rentablez_agent.py` to `C:\Rentablez\`.
7. Write `C:\ProgramData\Rentablez\config.json` with the entered token.
8. Copy bundled `vendor\nssm.exe` to `C:\Rentablez\`.
9. Run the `nssm install` / `nssm set` block from §10.2 to register the service.
10. `nssm start RentablezAgent` — runs the agent immediately so the baseline is captured now.
11. Print the device token back to the operator for visual confirmation.

### 11.4 Operator responsibility

The warehouse manager is responsible for ensuring the laptop is in its final shipped configuration (correct RAM, SSD, battery, display, etc.) **before** running the setup script. The state at setup time *is* the baseline. There is no separate "rebaseline" command — to reset the baseline, the operator deletes `baseline.json` and re-runs the agent.

### 11.5 Uninstall

`sudo ./uninstall_mac.sh` / `.\uninstall_windows.ps1` (as Administrator):

- Stop and unregister the service.
- Remove the agent script and config.
- **Leaves `baseline.json` in place** so re-running setup on the same laptop preserves the original baseline.

To fully wipe (e.g. before reselling the laptop): operator additionally deletes `/var/lib/rentablez/` or `C:\ProgramData\Rentablez\`.

### 11.6 Trust model

Without code signing, anything running `rentablez_agent.py` is unverified. The mitigations:

- Distribution channel is internal-only (private repo / direct hand-off). The script never travels over a public download path.
- File permissions on `/usr/local/rentablez/rentablez_agent.py` and `C:\Rentablez\rentablez_agent.py` are root/Administrator-only writable. A non-admin renter cannot tamper with the script after install.
- Backend treats every report as untrusted regardless — diff happens server-side too, and `SWAPPED` always triggers human review.

## 12. Error handling

| Failure | Behavior |
|---|---|
| Hardware collection fails (subprocess error) | Log error, skip this boot's report, exit 0. Try again next boot. |
| `config.json` missing or invalid | Log error, exit 1. No reports sent. Warehouse must re-run setup script. |
| `baseline.json` corrupted | Treat as missing → recreate from current state, send a new `status: "baseline"` report (so ops sees the reset). |
| `queue.json` corrupted | Move to `queue.json.broken-<timestamp>`, start fresh. Lost reports are accepted — boot fingerprints are not so precious that we should crash over a corrupt queue. |
| Network unreachable | Reports stay in queue. No retry within the boot — wait for next boot. |
| Backend returns 401 | Log it, mark the report as sent (no point retrying a bad token). Token rotation is out of scope for v1; warehouse must re-run setup to update the token. |
| Clock is wildly wrong (e.g. unset) | Use the timestamp anyway. Backend can flag absurd timestamps. |

All errors are logged to `agent.log` with timestamps. Log file is rotated at 10 MB, keeps 5 generations.

## 13. Testing

### 13.1 Unit tests (cross-platform)

- Diff algorithm: synthetic baseline + current with every flavor of change (added, removed, modified, list reorder, weak-field-only).
- Queue operations: enqueue, drain success, drain failure, corruption recovery, retention limit.
- Config loading: missing file, malformed JSON, missing token.
- Report builder: baseline shape, ok shape, SWAPPED shape.

### 13.2 Integration tests (per platform)

- Fresh-install scenario: empty filesystem, run agent, assert baseline written + baseline report queued.
- Second-boot match: baseline present, no hardware change, assert `ok` report.
- Second-boot mismatch: baseline present, swap one strong-ID field in current collector output (via dependency injection), assert `SWAPPED` report with correct change entry.
- Offline scenario: mock network failure, run two boots, assert both reports queued; then succeed, assert both drained in order.

### 13.3 Manual acceptance tests

- Run `setup_mac.sh` on a real MacBook, verify baseline appears in backend and the LaunchDaemon is registered (`launchctl list | grep rentablez`).
- Run `setup_windows.ps1` on a real Windows laptop, verify baseline appears and the service is registered (`sc query RentablezAgent`).
- Physically swap RAM in a test laptop, reboot, verify `SWAPPED` report identifies the correct module slot and serial.
- Disconnect WiFi, reboot, verify queue accumulates; reconnect, reboot, verify drain.
- Run the uninstall script, verify service is gone and `baseline.json` survives; re-run setup, verify the same baseline is reused.

## 14. Backend contract (out of scope, documented for completeness)

The agent depends on one backend endpoint:

```
POST /devices/checkin
Authorization: Bearer <device_token>
Content-Type: application/json

→ 200 { "ok": true }              report accepted
→ 401                              bad token
→ 4xx (other)                      report rejected, do not retry
→ 5xx, 408, 429, network failure   transient, agent will retry
```

Backend responsibilities (not built by the agent team):
- Store baseline per `device_token` on receiving first `status: "baseline"`.
- On `status: "SWAPPED"`, store the new fingerprint, alert ops, optionally lock the deposit.
- On `status: "ok"`, just timestamp the last-seen.
- Idempotency: agent may resend the same report after a transient failure. Backend should dedupe on `(device_token, collected_at)`.

## 15. Security considerations

- Config and state files are root-only readable. A non-admin renter cannot read or alter the device token, baseline, or queue.
- The script itself lives in root/Administrator-only locations; a non-admin renter cannot tamper with it. Without code signing, anyone with admin access can replace it — this is an accepted limitation, mitigated by the internal-only distribution channel (see §11.6).
- Communication is HTTPS-only; certificate validation is on by default (no pinning in v1).
- The agent collects hardware identifiers, not user data. No filesystem scanning, no keystrokes, no screen capture.
- An attacker with physical access and root can defeat any local check — this is unavoidable. The defense is the backend-side diff: even if the attacker wipes `baseline.json`, the backend still has the original baseline and will flag the next report as a re-baseline event for ops to review.

## 16. Out-of-scope items, deferred

These are deliberately left out of v1 and may be added later:

- Auto-update mechanism.
- Tray icon / user-visible status.
- Remote configuration (changing endpoint or cadence without reinstall).
- More-than-boot cadence (hourly, on-demand).
- Token rotation.
- Multi-tenant or sub-fleet routing.
- Anti-tamper hardening (process protection, root-of-trust checks).
- Linux support.

## 17. Open questions for backend team

- Final endpoint URL and TLS / auth scheme.
- Token format — confirm `RTBZ-LAP-\d{5,}` regex matches actual SKU scheme.
- Whether `current_fingerprint` on `SWAPPED` should be the full collector output or a trimmed subset.
- Retention period for baseline records on the backend side.
