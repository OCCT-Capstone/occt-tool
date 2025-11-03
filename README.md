# OCCT — OS Compliance Check Tool (Prototype)

A lightweight Windows-focused **OS compliance scanner** (Capstone prototype).  
It checks key host configurations and account activity, then shows evidence in a simple web UI.

**Please refer to the [User Manual](https://github.com/OCCT-Capstone/occt-tool/blob/main/OCCT%20User%20Manual%20(Prototype).pdf) for the full guide with screenshots.**

---

## What it does (at a glance)
- **Live Mode**: Run PowerShell collectors on the host to gather facts/events.
- **Sample Mode**: Safe demo with pre-seeded data (no host changes).
- **Controls**: YAML-driven checks (e.g., firewall defaults, local admin group).
- **UI**: Dashboard, control details, account activity, and evidence views.

## Downloads
>NOTE: This is a non-standard application and will require server side setup and provisioning from an elevated PowerShell instance.

- Download the latest zipped folder: [Here](https://github.com/OCCT-Capstone/occt-tool/archive/refs/heads/main.zip)
- Extract the folder before continuing

## Quick start (Windows)
```powershell
# PowerShell (Run as Admin)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
python -m venv env

.\env\Scripts\activate

pip install -r requirements.txt python -m backend.app

python -m backend.app

  ```
- The frontend (HTML/CSS) is served from the `frontend/` folder.
- The backend (`app.py`) is located in the `backend/` folder and runs the Flask server.

