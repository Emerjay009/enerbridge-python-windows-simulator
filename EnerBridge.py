from __future__ import annotations
import base64, hashlib, hmac, json, secrets, sys, time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import smtplib
from email.message import EmailMessage

APP_NAME = "EnerBridge"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = BASE_DIR / "users.json"
ROOM_NAMES = ["Classroom 1", "Classroom 2", "Classroom 3"]

#Gmail Notification System (for approved administrators)
GMAIL_SENDER = "coffeestudiosph@gmail.com"
GMAIL_APP_PASSWORD = "qvxy zesc pssl cnyb"


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, digest_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class UserStore:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        if not USERS_FILE.exists():
            self.save([])

    def load(self):
        try:
            with USERS_FILE.open("r", encoding="utf-8") as f:
                value = json.load(f)
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save(self, users):
        DATA_DIR.mkdir(exist_ok=True)
        tmp = USERS_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
        tmp.replace(USERS_FILE)

    def find(self, username):
        return next((u for u in self.load() if u["username"].casefold() == username.casefold()), None)

    def create(self, username, full_name, password, role="teacher", approved=False, notification_email=""):
        users = self.load()
        if any(u["username"].casefold() == username.casefold() for u in users):
            raise ValueError("That username already exists.")
        users.append({"username": username, "full_name": full_name, "password_hash": hash_password(password),
                      "role": role, "approved": bool(approved), "notification_email": notification_email.strip(), "email_notifications": True, "created_at": now_text()})
        self.save(users)

    def update_user(self, username, **changes):
        users = self.load()
        for user in users:
            if user["username"].casefold() == username.casefold():
                user.update(changes)
                self.save(users)
                return
        raise ValueError("User account not found.")

    def delete(self, username):
        self.save([u for u in self.load() if u["username"].casefold() != username.casefold()])


class RegisterDialog(tk.Toplevel):
    def __init__(self, parent, store):
        super().__init__(parent)
        self.store = store
        self.title("Register teacher/professorr account")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        frm = ttk.Frame(self, padding=18)
        frm.grid(sticky="nsew")
        ttk.Label(frm, text="Create an EnerBridge account", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.name = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.confirm = tk.StringVar()
        for r, label, var, show in [(1, "Full name", self.name, ""), (2, "Username", self.username, ""), (3, "Password", self.password, "●"), (4, "Confirm password", self.confirm, "●")]:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            ttk.Entry(frm, textvariable=var, show=show, width=30).grid(row=r, column=1, sticky="ew", pady=4)
        ttk.Label(frm, text="New accounts must be approved by an administrator.", wraplength=340).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 12))
        ttk.Button(frm, text="Submit registration", command=self.submit).grid(row=6, column=0, columnspan=2, sticky="ew")
        self.bind("<Return>", lambda _e: self.submit())

    def submit(self):
        name, username, password = self.name.get().strip(), self.username.get().strip(), self.password.get()
        if not name or not username or not password:
            messagebox.showerror("Missing information", "Complete all fields.", parent=self); return
        if len(username) < 3:
            messagebox.showerror("Invalid username", "Username must contain at least 3 characters.", parent=self); return
        if len(password) < 8:
            messagebox.showerror("Weak password", "Use at least 8 characters.", parent=self); return
        if password != self.confirm.get():
            messagebox.showerror("Password mismatch", "The passwords do not match.", parent=self); return
        try:
            self.store.create(username, name, password, "teacher", False)
        except ValueError as e:
            messagebox.showerror("Registration failed", str(e), parent=self); return
        messagebox.showinfo("Registration submitted", "Your account was created and is awaiting administrator approval.", parent=self)
        self.destroy()


class EnerBridgeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.store = UserStore()
        self.current_user = None
        self.rooms = {name: {"occupied": False, "door_open": False, "light_on": False, "fan_on": False,
                             "scheduled": False, "voltage": 12.0, "current": 0.0, "power": 0.0,
                             "energy_wh": 0.0, "updated_at": "Not yet updated"} for name in ROOM_NAMES}
        self.alerts = []
        self.email_sent_for = set()
        self.last_tick = time.monotonic()
        self.title(f"{APP_NAME} | Standalone Desktop Prototype")
        self.geometry("1050x720")
        self.minsize(900, 600)
        self.configure(bg="#f3f5f8")
        self.style = ttk.Style(self)
        try: self.style.theme_use("clam")
        except tk.TclError: pass
        self.style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#17324d")
        self.style.configure("Card.TLabelframe", padding=12)
        self.style.configure("Card.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        self.show_login()

    def show_login(self):
        for child in self.winfo_children(): child.destroy()
        users = self.store.load()
        if not any(u.get("role") == "admin" for u in users):
            self.show_first_admin_setup()
            return
        outer = ttk.Frame(self, padding=30)
        outer.place(relx=.5, rely=.48, anchor="center")
        ttk.Label(outer, text="EnerBridge", style="Title.TLabel").grid(row=0, column=0, columnspan=2, pady=(0, 4))
        ttk.Label(outer, text="Building energy management · Desktop simulator").grid(row=1, column=0, columnspan=2, pady=(0, 22))
        self.login_user = tk.StringVar(); self.login_pass = tk.StringVar()
        ttk.Label(outer, text="Username").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 12))
        user_entry = ttk.Entry(outer, textvariable=self.login_user, width=30); user_entry.grid(row=2, column=1, pady=5)
        ttk.Label(outer, text="Password").grid(row=3, column=0, sticky="w", pady=5, padx=(0, 12))
        pass_entry = ttk.Entry(outer, textvariable=self.login_pass, show="●", width=30); pass_entry.grid(row=3, column=1, pady=5)
        ttk.Button(outer, text="Log in", command=self.login).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 5))
        ttk.Button(outer, text="Register as teacher", command=lambda: RegisterDialog(self, self.store)).grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(outer, text="Accounts are stored locally. Sensor data resets when the app closes.", wraplength=340).grid(row=6, column=0, columnspan=2, pady=(16, 0))
        pass_entry.bind("<Return>", lambda _e: self.login()); user_entry.focus_set()

    def show_first_admin_setup(self):
        outer = ttk.Frame(self, padding=30)
        outer.place(relx=.5, rely=.48, anchor="center")
        ttk.Label(outer, text="Welcome to EnerBridge", style="Title.TLabel").grid(row=0, column=0, columnspan=2, pady=(0, 6))
        ttk.Label(outer, text="Create the first local administrator account.").grid(row=1, column=0, columnspan=2, pady=(0, 18))
        self.admin_name = tk.StringVar(); self.admin_user = tk.StringVar(); self.admin_email = tk.StringVar(); self.admin_pass = tk.StringVar(); self.admin_confirm = tk.StringVar()
        fields = [("Full name", self.admin_name, ""), ("Username", self.admin_user, ""), ("Email Address", self.admin_email, ""), ("Password (8+ chars)", self.admin_pass, "●"), ("Confirm password", self.admin_confirm, "●")]
        for i, (label, var, show) in enumerate(fields, start=2):
            ttk.Label(outer, text=label).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 12))
            ttk.Entry(outer, textvariable=var, show=show, width=30).grid(row=i, column=1, pady=5)
        ttk.Label(outer, text="Email notifications are sent to approved administrators.", wraplength=340).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(outer, text="Create administrator", command=self.create_first_admin).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def create_first_admin(self):
        name, username, email, password = self.admin_name.get().strip(), self.admin_user.get().strip(), self.admin_email.get().strip(), self.admin_pass.get()
        if not name or not username or "@" not in email or "." not in email.rsplit("@", 1)[-1] or len(password) < 8 or password != self.admin_confirm.get():
            messagebox.showerror("Check details", "Enter a name, username, valid notification email, password of at least 8 characters, and matching confirmation."); return
        try: self.store.create(username, name, password, "admin", True, email)
        except ValueError as e: messagebox.showerror("Could not create administrator", str(e)); return
        messagebox.showinfo("Administrator created", "Your administrator account is ready. Please log in.")
        self.show_login()

    def login(self):
        username = self.login_user.get().strip()
        user = self.store.find(username)
        if not user or not verify_password(self.login_pass.get(), user.get("password_hash", "")):
            messagebox.showerror("Login failed", "Incorrect username or password."); return
        if not user.get("approved", False):
            messagebox.showwarning("Approval pending", "Your account is waiting for administrator approval."); return
        self.current_user = user
        self.show_main()

    def logout(self):
        self.current_user = None
        self.show_login()

    def show_main(self):
        for child in self.winfo_children(): child.destroy()
        header = ttk.Frame(self, padding=(18, 12)); header.pack(fill="x")
        ttk.Label(header, text="EnerBridge", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"{self.current_user['full_name']} · {self.current_user['role'].title()}").pack(side="right", padx=(12, 0))
        ttk.Button(header, text="Log out", command=self.logout).pack(side="right")
        ttk.Label(self, text="Standalone classroom energy-management prototype · Simulated signals only", padding=(20, 0)).pack(anchor="w")
        self.notebook = ttk.Notebook(self); self.notebook.pack(fill="both", expand=True, padx=14, pady=14)
        self.dashboard_tab = ttk.Frame(self.notebook, padding=14)
        self.sim_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.add(self.sim_tab, text="GPIO Simulator")
        if self.current_user.get("role") == "admin":
            self.approvals_tab = ttk.Frame(self.notebook, padding=14)
            self.notebook.add(self.approvals_tab, text="User Approvals")
            self.build_approvals()
        self.build_dashboard(); self.build_simulator(); self.refresh_dashboard()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_dashboard(self):
        for w in self.dashboard_tab.winfo_children(): w.destroy()
        ttk.Label(self.dashboard_tab, text="Building overview", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 10))
        cards = ttk.Frame(self.dashboard_tab); cards.pack(fill="x", pady=(0, 12))
        self.metric_labels = {}
        for key, label in [("occupied", "Occupied rooms"), ("loads", "Rooms with loads on"), ("power", "Total power"), ("alerts", "Active alerts")]:
            box = ttk.LabelFrame(cards, text=label, style="Card.TLabelframe"); box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            val = ttk.Label(box, text="0", font=("Segoe UI", 18, "bold")); val.pack(anchor="w")
            self.metric_labels[key] = val
        table_frame = ttk.LabelFrame(self.dashboard_tab, text="Room status", padding=8); table_frame.pack(fill="both", expand=True)
        cols = ("room", "occupancy", "door", "light", "fan", "schedule", "voltage", "current", "power")
        self.room_tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=7)
        headings = {"room":"Room", "occupancy":"Occupancy", "door":"Door", "light":"Light", "fan":"Fan", "schedule":"Scheduled", "voltage":"Voltage (V)", "current":"Current (A)", "power":"Power (W)"}
        widths = {"room":130,"occupancy":90,"door":80,"light":70,"fan":70,"schedule":85,"voltage":90,"current":90,"power":90}
        for c in cols: self.room_tree.heading(c, text=headings[c]); self.room_tree.column(c, width=widths[c], anchor="center")
        self.room_tree.pack(fill="both", expand=True)
        ttk.Label(self.dashboard_tab, text="Recent alerts (cleared when the application closes)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 4))
        self.alert_list = tk.Listbox(self.dashboard_tab, height=4); self.alert_list.pack(fill="x")

    def build_simulator(self):
        ttk.Label(self.sim_tab, text="Simulated sensor inputs", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(self.sim_tab, text="Change inputs to mimic sensor readings. No Raspberry Pi, GPIO pins, or physical loads are used.", wraplength=850).pack(anchor="w", pady=(0, 12))
        self.sim_vars = {}
        for room in ROOM_NAMES:
            state = self.rooms[room]
            frame = ttk.LabelFrame(self.sim_tab, text=room, padding=12); frame.pack(fill="x", pady=6)
            vars_ = {k: tk.BooleanVar(value=state[k]) for k in ("occupied", "door_open", "light_on", "fan_on", "scheduled")}
            self.sim_vars[room] = vars_
            for col, (key, label) in enumerate([("occupied", "Occupied"), ("door_open", "Door open"), ("light_on", "Light ON"), ("fan_on", "Fan ON"), ("scheduled", "Within schedule")]):
                ttk.Checkbutton(frame, text=label, variable=vars_[key], command=lambda r=room: self.apply_simulation(r)).grid(row=0, column=col, padx=7, pady=4, sticky="w")
            ttk.Label(frame, text="Voltage (V)").grid(row=1, column=0, sticky="w", pady=(10, 0))
            voltage = tk.StringVar(value=str(state["voltage"]))
            current = tk.StringVar(value="0.00")
            self.sim_vars[room]["voltage_entry"] = voltage; self.sim_vars[room]["current_entry"] = current
            ttk.Entry(frame, textvariable=voltage, width=9).grid(row=1, column=1, sticky="w", pady=(10, 0))
            ttk.Label(frame, text="Current (A)").grid(row=1, column=2, sticky="e", pady=(10, 0))
            ttk.Entry(frame, textvariable=current, width=9).grid(row=1, column=3, sticky="w", pady=(10, 0))
            ttk.Button(frame, text="Apply reading", command=lambda r=room: self.apply_simulation(r, read_fields=True)).grid(row=1, column=4, padx=8, pady=(10, 0))
        ttk.Button(self.sim_tab, text="Reset all simulated rooms", command=self.reset_simulation).pack(anchor="e", pady=10)

    def apply_simulation(self, room, read_fields=False):
        state, vars_ = self.rooms[room], self.sim_vars[room]
        for key in ("occupied", "door_open", "light_on", "fan_on", "scheduled"):
            state[key] = vars_[key].get()
        if read_fields:
            try:
                voltage = float(vars_["voltage_entry"].get()); current = float(vars_["current_entry"].get())
                if voltage < 0 or current < 0: raise ValueError
                state["voltage"], state["current"] = voltage, current
            except ValueError:
                messagebox.showerror("Invalid reading", "Voltage and current must be non-negative numbers."); return
        else:
            # Useful defaults for a simple demo when a simulated load is switched on.
            if state["light_on"] or state["fan_on"]:
                if state["current"] <= 0: state["current"] = (0.08 if state["light_on"] else 0) + (0.25 if state["fan_on"] else 0)
            else:
                state["current"] = 0.0
            vars_["current_entry"].set(f"{state['current']:.2f}")
        state["power"] = state["voltage"] * state["current"]
        state["updated_at"] = now_text()
        if (state["light_on"] or state["fan_on"]) and not state["scheduled"]:
            msg = f"{room}: electrical load is ON outside the schedule."
            if not any(a["message"] == msg for a in self.alerts):
                alert_time = now_text()
                self.alerts.insert(0, {"time": alert_time, "message": msg})
                if msg not in self.email_sent_for:
                    self.email_sent_for.add(msg)
                    self.send_admin_notification(room, alert_time, msg, state)
        else:
            cleared_message = f"{room}: electrical load is ON outside the schedule."
            self.alerts = [a for a in self.alerts if a["message"] != cleared_message]
            self.email_sent_for.discard(cleared_message)
        self.refresh_dashboard()

    def send_admin_notification(self, room, alert_time, message, state):
        """Email approved administrators using the settings at the top of main.py."""
        sender = GMAIL_SENDER.strip()
        app_password = GMAIL_APP_PASSWORD.replace(" ", "").strip()
        recipients = sorted({u.get("notification_email", "").strip() for u in self.store.load()
                             if u.get("role") == "admin" and u.get("approved") and
                             u.get("email_notifications", True) and "@" in u.get("notification_email", "")})
        if not recipients or not app_password:
            return
        msg = EmailMessage()
        msg["Subject"] = f"EnerBridge Alert: {room} load outside schedule"
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.set_content(
            "EnerBridge has detected a simulated off-schedule electrical load.\n\n"
            f"Classroom: {room}\nDetected at: {alert_time}\nAlert: {message}\n"
            f"Voltage: {state['voltage']:.2f} V\nCurrent: {state['current']:.2f} A\n"
            f"Calculated power: {state['power']:.2f} W\n\n"
            "This message comes from the EnerBridge desktop simulator; readings are simulated, not physical sensor measurements."
        )
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=12) as smtp:
                smtp.login(sender, app_password)
                smtp.send_message(msg)
        except Exception as exc:
            # Keep the in-app alert even if mail delivery is unavailable.
            print(f"EnerBridge email notification failed: {exc}")

    def reset_simulation(self):
        for room in ROOM_NAMES:
            for key in ("occupied", "door_open", "light_on", "fan_on", "scheduled"): self.sim_vars[room][key].set(False)
            self.sim_vars[room]["voltage_entry"].set("12.0"); self.sim_vars[room]["current_entry"].set("0.00")
            self.rooms[room].update({"occupied":False,"door_open":False,"light_on":False,"fan_on":False,"scheduled":False,"voltage":12.0,"current":0.0,"power":0.0,"energy_wh":0.0,"updated_at":now_text()})
        self.alerts.clear(); self.refresh_dashboard()

    def refresh_dashboard(self):
        if not hasattr(self, "room_tree") or not self.room_tree.winfo_exists(): return
        occupied = sum(s["occupied"] for s in self.rooms.values())
        loads = sum(s["light_on"] or s["fan_on"] for s in self.rooms.values())
        power = sum(s["power"] for s in self.rooms.values())
        self.metric_labels["occupied"].config(text=str(occupied))
        self.metric_labels["loads"].config(text=str(loads))
        self.metric_labels["power"].config(text=f"{power:.2f} W")
        self.metric_labels["alerts"].config(text=str(len(self.alerts)))
        for item in self.room_tree.get_children(): self.room_tree.delete(item)
        for room, s in self.rooms.items():
            self.room_tree.insert("", "end", values=(room, "Yes" if s["occupied"] else "No", "Open" if s["door_open"] else "Closed", "ON" if s["light_on"] else "OFF", "ON" if s["fan_on"] else "OFF", "Yes" if s["scheduled"] else "No", f"{s['voltage']:.2f}", f"{s['current']:.2f}", f"{s['power']:.2f}"))
        self.alert_list.delete(0, "end")
        for alert in self.alerts[:10]: self.alert_list.insert("end", f"{alert['time']}  |  {alert['message']}")

    def build_approvals(self):
        ttk.Label(self.approvals_tab, text="Registration approvals", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(self.approvals_tab, text="Select a pending teacher account, then approve or reject it.").pack(anchor="w", pady=(0, 8))
        self.users_tree = ttk.Treeview(self.approvals_tab, columns=("username", "name", "role", "created"), show="headings", height=12)
        for c, title, width in [("username", "Username", 160), ("name", "Full name", 240), ("role", "Role", 100), ("created", "Registered", 180)]:
            self.users_tree.heading(c, text=title); self.users_tree.column(c, width=width, anchor="w")
        self.users_tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(self.approvals_tab); buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="Approve selected", command=self.approve_selected).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Reject / delete selected", command=self.reject_selected).pack(side="left")
        self.refresh_users()

    def refresh_users(self):
        if not hasattr(self, "users_tree") or not self.users_tree.winfo_exists(): return
        for item in self.users_tree.get_children(): self.users_tree.delete(item)
        for u in self.store.load():
            if u.get("role") != "admin" and not u.get("approved", False):
                self.users_tree.insert("", "end", values=(u["username"], u["full_name"], u["role"], u.get("created_at", "")))

    def selected_username(self):
        selected = self.users_tree.selection()
        if not selected: messagebox.showwarning("Select an account", "Choose a pending account first."); return None
        return self.users_tree.item(selected[0], "values")[0]

    def approve_selected(self):
        username = self.selected_username()
        if username:
            self.store.update_user(username, approved=True)
            self.refresh_users(); messagebox.showinfo("Account approved", f"{username} can now log in.")

    def reject_selected(self):
        username = self.selected_username()
        if username and messagebox.askyesno("Delete registration", f"Permanently delete the pending account '{username}'?"):
            self.store.delete(username); self.refresh_users()

    def on_close(self):
        # Sensor state and alerts are intentionally memory-only.
        self.destroy()


def main():
    app = EnerBridgeApp()
    app.mainloop()

if __name__ == "__main__":
    main()
