# OCCT tool - Operating System Compliance Control Tool

## 🛠️ OCCT Project — Setup Guide

This README will guide you through setting up the OCCT prototype on your own machine.  
Follow the steps below to create a local development environment and run the server.

---

## 📦 Prerequisites
- Python **3.9+**
- Git
- IDE or editor (VS Code, PyCharm, etc.)

---

## 🔹 1. Clone the Repository
Using VS Code, click "Clone Git Repository" and paste the following:

```bash
https://github.com/OCCT-Capstone/occt-tool.git
```

---

## 🔹 2. Create a Virtual Environment

Open the built-in terminal in VS Code: 

**macOS / Linux**
```bash
python3 -m venv env
source env/bin/activate
```

**Windows (PowerShell)**
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
python -m venv env
.\env\Scripts\activate
```

After this step, you should see `(env)` at the beginning of your terminal prompt.

---

## 🔹 3. Install Dependencies
With the environment activated, install the project requirements:

```bash
pip install -r requirements.txt
```

---

## 🔹 4. Run the Application
From the project root, run the backend server:

```bash
python -m backend.app
```

The Flask server will start and be available at:

👉 http://127.0.0.1:5000

---

## 🔹 5. Deactivate the Environment (Optional)
When you are done working:

```bash
deactivate
```

Deactivation is optional. Closing your terminal or IDE will also end the environment session.

---

## 📝 Notes
- Do not commit the `env/` folder. It is ignored in `.gitignore`.
- If you add new packages, update the requirements file so others can install them:
  ```bash
  pip freeze > requirements.txt
  ```
- The frontend (HTML/CSS) is served from the `frontend/` folder.
- The backend (`app.py`) is located in the `backend/` folder and runs the Flask server.

