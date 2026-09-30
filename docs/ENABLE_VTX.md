# Enable Intel VT-x on HP EliteBook 840 G4 (Windows 10 Pro)

This guide enables **Intel Virtualization Technology (VT-x)** in BIOS so Windows features (Hyper-V, **Virtual Machine Platform**, **WSL 2**) and **Docker Desktop** can use hardware virtualization.

Your machine previously reported **`VirtualizationFirmwareEnabled: False`**. That value only changes after you enable VT-x in BIOS and fully reboot into Windows.

---

## Before you start

- You must use the **physical keyboard** on the laptop during boot. This cannot be done remotely.
- Plan for a **full shutdown**, not only Restart (some HP firmware settings apply more reliably after shutdown).
- Have your Windows password ready after reboot.

---

## Step 1: Full shutdown

1. Save all work and close applications.
2. **Start** → **Power** → **Shut down** (not Sleep, not Restart).
3. Wait until the power LED and fan are off (unplug USB boot devices if you use any).

Optional (helps on some HP models): hold **Shift** while clicking **Shut down** to ensure a full shutdown.

---

## Step 2: Enter BIOS (HP EliteBook 840 G4)

1. Press the **power button** to turn the laptop on.
2. As soon as the **HP logo** appears, tap **F10** repeatedly until the BIOS Setup Utility opens.

   **If F10 does not work:**

   - At the HP logo, press **Esc** once, then press **F10** when the startup menu appears.

3. If prompted for a **BIOS administrator password**, enter it (some corporate laptops require IT).

---

## Step 3: Enable Virtualization Technology (VTx)

Menu names can vary slightly by BIOS version; use the closest match.

1. Open the **Advanced** tab (or **Security** → **System Security** on some builds).
2. Select **System Options** (sometimes **Built-in Device Options**).
3. Find **Virtualization Technology (VTx)** or **Intel Virtualization Technology**.
4. Set it to **Enabled**.
5. If you see **VT-d** (Intel VT for Directed I/O) and you use advanced virtualization, you may enable it too; **VT-x / VTx is the required one** for Docker and WSL2.

**Do not change** unrelated settings (Secure Boot, boot order) unless you know you need to.

---

## Step 4: Save and exit

1. Press **F10** (Save Changes and Exit), or use **File** → **Save Changes and Exit**.
2. Confirm **Yes**.
3. The laptop will reboot into Windows.

---

## Step 5: Enable Windows features (Administrator)

After Windows loads, open **PowerShell as Administrator** and run:

```powershell
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```

Optional (only if you use Hyper-V directly):

```powershell
dism /online /enable-feature /featurename:Microsoft-Hyper-V-All /all /norestart
```

**Reboot Windows** when DISM finishes.

For WSL 2 as default (after reboot, still Admin):

```powershell
wsl --set-default-version 2
```

If WSL is not installed yet:

```powershell
wsl --install
```

Follow prompts; reboot again if asked.

---

## Step 6: Verify with the project script

From the repo root (or any path):

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\wambua\Documents\AgentHub\scripts\verify-virtualization.ps1"
```

**Expected after successful BIOS change:**

- `[PASS] VirtualizationFirmwareEnabled (Win32_Processor)` with **Value: True**
- systeminfo line similar to **Hyper-V Requirements: ... A hypervisor has been detected ...** or firmware enabled **Yes** (exact wording varies by Windows build)

If firmware still shows **False**, VT-x is still off in BIOS or Secure Boot/firmware policy blocked the change—repeat Steps 1–4 and confirm **VTx = Enabled**.

---

## Step 7: Docker Desktop and compose test

1. Start **Docker Desktop** from the Start menu; wait until it reports **Running**.
2. In a terminal:

```powershell
docker version
docker info
```

3. In your project folder (where `docker-compose.yml` exists):

```powershell
docker compose up -d
docker compose ps
```

If Docker reports virtualization/WSL2 errors, re-run the verify script and confirm **VM Platform**, **WSL**, and **VT-x** are all enabled.

---

## Quick reference (HP EliteBook 840 G4)

| Action | Key / path |
|--------|------------|
| Enter BIOS | **F10** at HP logo (or **Esc**, then **F10**) |
| VT-x setting | **Advanced** → **System Options** → **Virtualization Technology (VTx)** → **Enabled** |
| Save | **F10** → Yes |
| Verify | `scripts\verify-virtualization.ps1` |

---

## Troubleshooting

- **No VTx option in BIOS:** Update BIOS from HP Support for EliteBook 840 G4, or check whether IT locked BIOS settings.
- **Option grayed out:** Corporate policy may require IT to enable virtualization.
- **Fast Startup:** Control Panel → Power Options → Choose what power buttons do → uncheck **Turn on fast startup**, then full shutdown and retry BIOS.
- **Still False in Windows:** Ensure you saved BIOS (F10) and booted Windows—not a stale hibernate/fast-start state.

---

*Artifact location: `C:\Users\wambua\Documents\AgentHub\docs\ENABLE_VTX.md`*
