#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Rynzler’s Garage & Casino Editor  –  a Test Drive Unlimited 2 / Project Paradise 2 save utility.

Developed from the tested tdu2_garage_gui.py. The save handling (decrypt / edit / encrypt / checksums)
still lives in tdu2_tool.py and is unchanged. SaveModel below keeps every original method and adds
house grouping, safer writing and the optional Driver.MustClearOnlineDatas repair.

Launch:      Launch_Rynzlers_Garage_and_Casino_Editor.bat   (or:  py Rynzlers_Garage_and_Casino_Editor.py)
Needs:       Python 3.8+ with tkinter (included in the python.org installer). No other packages.
Same folder: tdu2_tool.py, cars_database.json, houses_database.json, vehicle_classes.json
             (garage_list.csv is a reference list only; the program does not need it to run)
Headless:    py Rynzlers_Garage_and_Casino_Editor.py --check [path\to\PLAYERSAVE\DATA]

CLOSE THE GAME before saving. Keep your own backup of the whole profile folder as well.
"""
import os, re, sys, json, time, shutil, threading, queue, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tdu2_tool as tool          # noqa: E402  (save cipher / format logic – unchanged)

APP_NAME = "Rynzler’s Garage & Casino Editor"
APP_VERSION = "1.2.0"
GARAGE_LIST = os.path.join(HERE, "garage_list.csv")
REPAIR_FIELD = "Driver.MustClearOnlineDatas"
REPAIR_EXPECTED = 4          # the only value confirmed by in-game testing
REPAIR_TARGET = 0


def detect_profile(path):
    """Profile name = folder that contains PLAYERSAVE, or None if it can't be worked out."""
    parts = os.path.abspath(path).split(os.sep)
    for i in range(len(parts) - 1):
        if parts[i + 1].upper() == "PLAYERSAVE":
            return parts[i]
    return None


def _load_json(*names):
    """Returns (data, path, error). Looks next to the program and in a Database sub-folder."""
    for n in names:
        for base in (HERE, os.path.join(HERE, "Database")):
            p = os.path.join(base, n)
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8-sig") as f:
                        return json.load(f), p, None
                except Exception as ex:           # damaged file: report, don't crash
                    return None, p, f"{n} could not be read ({ex})"
    return None, None, f"{names[0]} not found next to the program"


def data_status():
    """[(file name, ok, detail)] for the external data files, so the About screen and --check can show them."""
    out = []
    db, p, err = _load_json("cars_database.json")
    out.append(("cars_database.json", err is None and isinstance(db, dict),
                err or f"{len(db):,} vehicle entries"))
    db, p, err = _load_json("houses_database.json")
    out.append(("houses_database.json", err is None and isinstance(db, dict),
                err or f"{len(db.get('houses', []))} houses (+{len(db.get('known_hcs') or {})} extra house IDs)"))
    db, p, err = _load_json("vehicle_classes.json")
    out.append(("vehicle_classes.json", err is None and isinstance(db, dict),
                err or f"{len(db.get('by_name') or {})} class badges by name, {len(db.get('by_archetype_id') or {})} by vehicle ID"))
    ok = os.path.exists(GARAGE_LIST)
    out.append(("garage_list.csv", ok, "reference list (optional)" if ok else "not found (optional reference list)"))
    return out


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s.replace(",", "")).strip()


# =====================================================================================
#                                     SAVE MODEL
# =====================================================================================
class SaveModel:
    """All editing logic, independent of any window. Works on the decrypted data in memory."""

    ARCH = "Garage[{i}].Car.Archetype"
    CARID = "Garage[{i}].Car.ID"
    HOUSE = "Garage[{i}].House"
    UPG = ("Acceleration", "Top Speed", "Braking")
    ODO = "Garage[{i}].Car.OdometerKms"

    def __init__(self, path, profile=None):
        self.path = path
        self.profile = profile or detect_profile(path)
        self.warnings = []
        if not self.profile:
            raise ValueError("Could not work out the profile name from the path (need ...\\<Profile>\\PLAYERSAVE\\DATA).")
        with open(path, "rb") as f:
            raw = f.read()
        pt, self.footer = tool.decrypt(raw, self.profile, "DATA")   # ValueError if wrong profile / damaged
        self.orig = bytes(pt)
        self.pt = bytearray(pt)
        self.fl = {p: (t, o) for p, t, o in tool.fields(pt)}
        slots = [int(m.group(1)) for p in self.fl for m in [re.match(r"^Garage\[(\d+)\]\.Car\.Archetype$", p)] if m]
        self.nslots = (max(slots) + 1) if slots else 0
        # --- vehicle database (full records kept; name map kept as before)
        db, _, err = _load_json("cars_database.json")
        if err:
            self.warnings.append(err)
        self.car_db = {}
        if isinstance(db, dict):
            for k, v in db.items():
                try:
                    self.car_db[int(k)] = v
                except (ValueError, TypeError):
                    pass
        self.cars = {k: v.get("name", f"ID {k}") for k, v in self.car_db.items()}
        # --- house database
        hdb, _, err = _load_json("houses_database.json")
        if err:
            self.warnings.append(err)
        self.house_db = {}
        if isinstance(hdb, dict):
            for h in hdb.get("houses", []):
                self.house_db[str(h.get("house_hc"))] = {
                    "name": h.get("name"), "island": h.get("island"), "level": h.get("level"),
                    "slots": h.get("slots"), "spot": h.get("spot_name"), "source": "houses"}
            for k, v in (hdb.get("known_hcs") or {}).items():
                self.house_db.setdefault(str(k), {
                    "name": v.get("name"), "island": v.get("island"), "level": v.get("level"),
                    "slots": v.get("slots"), "spot": v.get("spot"), "source": "known_hcs"})
        self.houses = {k: f'{v["name"]} ({v["island"]})' for k, v in self.house_db.items()}
        # --- class badges transcribed from screenshots
        cl, _, err = _load_json("vehicle_classes.json")
        if err:
            self.warnings.append(err)
        self.cls_by_id, self.cls_by_name = {}, {}
        if isinstance(cl, dict):
            self.cls_by_id = {int(k): v for k, v in (cl.get("by_archetype_id") or {}).items()}
            self.cls_by_name = cl.get("by_name") or {}

    # ---- low level
    def get(self, path):
        t, o = self.fl[path]
        return tool.rawval(bytes(self.pt), t, o)

    def has(self, path):
        return path in self.fl

    def put(self, path, text):
        t, o = self.fl[path]
        b = tool.parse(t, str(text))
        self.pt[o:o + len(b)] = b

    def changes(self):
        """[(path, before, after)] for every field that differs from what was loaded/last saved."""
        out = []
        cur = bytes(self.pt)
        if cur == self.orig:
            return out
        for p, (t, o) in self.fl.items():
            a, b = tool.rawval(self.orig, t, o), tool.rawval(cur, t, o)
            if a != b:
                out.append((p, a, b))
        return out

    def dirty(self):
        return bytes(self.pt) != self.orig

    # ---- garage (original behaviour)
    def car_name(self, arch):
        if arch == 0:
            return "(empty slot)"
        return self.cars.get(arch, f"Unknown car (ID {arch})")

    def house_label(self, slot):
        hc = self.get(self.HOUSE.format(i=slot))
        return self.houses.get(hc, f"House …{hc[-7:]}")

    def row(self, slot):
        arch = int(self.get(self.ARCH.format(i=slot)))
        return {
            "slot": slot, "house": self.house_label(slot), "arch": arch, "name": self.car_name(arch),
            "carid": self.get(self.CARID.format(i=slot)),
            "upg": tuple(int(self.get(f"Garage[{slot}].Car.Car Upgrades.{u}")) for u in self.UPG),
            "odo": float(self.get(self.ODO.format(i=slot))),
        }

    def rows(self, owned_only=True):
        r = [self.row(i) for i in range(self.nslots)]
        return [x for x in r if x["arch"] != 0] if owned_only else r

    def set_archetype(self, slot, arch):
        if not (0 < int(arch) < 2 ** 31):
            raise ValueError("Car ID must be a positive number.")
        if int(self.get(self.ARCH.format(i=slot))) == 0:
            raise ValueError("That slot is empty. This tool only changes cars you already own (adding cars is not supported).")
        self.put(self.ARCH.format(i=slot), int(arch))

    def set_upgrades(self, slot, accel, top, brake):
        for v in (accel, top, brake):
            if not (0 <= int(v) <= 4):
                raise ValueError("Upgrade levels must be between 0 and 4.")
        for u, v in zip(self.UPG, (accel, top, brake)):
            self.put(f"Garage[{slot}].Car.Car Upgrades.{u}", int(v))

    def set_odometer(self, slot, km):
        k = float(km)
        if k < 0:
            raise ValueError("Odometer can't be negative.")
        self.put(self.ODO.format(i=slot), repr(k))

    def max_upgrades_all(self):
        n = 0
        for r in self.rows(owned_only=True):
            if r["upg"] != (4, 4, 4):
                self.set_upgrades(r["slot"], 4, 4, 4)
                n += 1
        return n

    # ---- garage (new: grouping by house)
    def house_info(self, hc):
        return self.house_db.get(str(hc))

    def vehicle_class(self, arch, name):
        c = self.cls_by_id.get(arch) or self.cls_by_name.get(norm_name(name))
        if c is None and arch in self.car_db:
            c = self.cls_by_name.get(norm_name(self.car_db[arch].get("name", "")))
        return (c["class"], c["rank"]) if c else None

    def garage_groups(self, hide_empty_garages=True):
        """Vehicles grouped by the house they are stored in.
        Position numbers are the order of entries in the save for that house (see report: unverified in-game)."""
        groups, order = {}, []
        for i in range(self.nslots):
            hc = self.get(self.HOUSE.format(i=i))
            arch = int(self.get(self.ARCH.format(i=i)))
            if arch == 0 and hc in ("0", ""):
                continue                                        # unassigned filler entry
            if hc not in groups:
                groups[hc] = {"hc": hc, "info": self.house_info(hc), "rows": []}
                order.append(hc)
            r = self.row(i)
            r["hc"] = hc
            r["cls"] = self.vehicle_class(arch, r["name"]) if arch else None
            r["identified"] = (arch == 0) or (arch in self.car_db)
            r["pos"] = len(groups[hc]["rows"]) + 1
            groups[hc]["rows"].append(r)
        out = []
        for hc in order:
            g = groups[hc]
            g["occupied"] = sum(1 for r in g["rows"] if r["arch"] != 0)
            info = g["info"]
            g["name"] = info["name"] if info else f"Unrecognised house …{hc[-7:]}"
            g["island"] = (info["island"] if info else None)
            g["capacity"] = (info["slots"] if info else None)
            if hide_empty_garages and g["occupied"] == 0:
                continue
            out.append(g)
        out.sort(key=lambda g: ((g["island"] or "zz"), g["name"].lower(), g["hc"]))
        return out

    def unrecognised(self):
        return [r for r in self.rows(True) if r["arch"] not in self.car_db]

    # ---- casino / profile
    def preset_preview(self, name):
        new, ch = tool.compute_edits(bytes(self.pt), tool.PRESETS[name][1])
        return new, ch

    def apply_preset(self, name):
        new, ch = self.preset_preview(name)
        self.pt = bytearray(new)
        return ch

    def set_value(self, path, value):
        self.put(path, value)

    def level_like_fields(self):
        """Informational only: fields under Casino.* whose names mention 'level'."""
        return [(p, self.get(p)) for p in self.fl if p.lower().startswith("casino") and "level" in p.lower()]

    # ---- validation + saving
    def validate_before_write(self):
        """Raises ValueError unless the edited data is structurally identical to what was loaded."""
        data = bytes(self.pt)
        if len(data) != len(self.orig):
            raise ValueError("Edited data length differs from the loaded save – refusing to write.")
        fl2 = {p: (t, o) for p, t, o in tool.fields(data)}
        if fl2 != self.fl:
            raise ValueError("Edited data no longer parses to the same field layout – refusing to write.")
        # every byte outside the known fields must be untouched
        touched = set()
        for p, (t, o) in self.fl.items():
            touched.update(range(o, o + tool.TYPES[t][2]))
        for i, (a, b) in enumerate(zip(self.orig, data)):
            if a != b and i not in touched:
                raise ValueError("Bytes outside editable fields changed – refusing to write.")

    def _encrypt_verified(self):
        self.validate_before_write()
        data = bytes(self.pt)
        out = tool.encrypt(data, self.profile, "DATA", self.footer)
        chk, _ = tool.decrypt(out, self.profile, "DATA")
        if chk != data:
            raise RuntimeError("Verification failed - nothing written.")
        return out

    def save_new(self, out_path):
        out = self._encrypt_verified()
        with open(out_path, "wb") as f:
            f.write(out)
        return out_path

    def _write_with_backup(self, out):
        """Backup (verified) -> temp file -> atomic replace -> read back and verify. Auto-rolls back on failure."""
        raw_old = _read(self.path)
        bak = self.path + ".backup-" + time.strftime("%Y%m%d-%H%M%S")
        n = 1
        while os.path.exists(bak):
            n += 1
            bak = self.path + ".backup-" + time.strftime("%Y%m%d-%H%M%S") + f"-{n}"
        shutil.copy2(self.path, bak)
        if _read(bak) != raw_old:
            raise RuntimeError("Backup copy did not match the original – nothing was changed.")
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        try:
            chk, _ = tool.decrypt(_read(self.path), self.profile, "DATA")
            if chk != bytes(self.pt):
                raise ValueError("written file differs from intended data")
        except Exception as ex:
            shutil.copy2(bak, self.path)                        # roll back
            raise RuntimeError(f"Post-write verification failed ({ex}). The backup was put back automatically.")
        return bak

    def save_in_place(self):
        out = self._encrypt_verified()
        bak = self._write_with_backup(out)
        self.orig = bytes(self.pt)
        return bak

    def backups(self):
        return tool.list_backups(self.path)

    @staticmethod
    def restore_backup(path, profile, src):
        tool.decrypt(_read(src), profile, "DATA")       # must be a valid save
        safety = path + ".before-restore-" + time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, safety)
        shutil.copy2(src, path)
        return src, safety

    @staticmethod
    def restore_latest(path, profile):
        bs = tool.list_backups(path)
        if not bs:
            raise ValueError("No backups found next to this file.")
        return SaveModel.restore_backup(path, profile, bs[-1])

    def verify_report(self):
        """Verifies the file on disk (not the in-memory edits). Returns list of (ok, text)."""
        out = []
        raw = _read(self.path)
        pt, footer = tool.decrypt(raw, self.profile, "DATA")       # raises on any failure
        out.append((True, f"Decrypts correctly for profile “{self.profile}”; all chunk checksums valid ({len(pt):,} bytes)."))
        same = tool.encrypt(pt, self.profile, "DATA", footer) == raw
        out.append((same, "Re-encrypts byte-identically." if same else "Re-encrypt differs from the file (unexpected)."))
        out.append((True, f"{len(self.fl):,} editable fields, {self.nslots} garage entries."))
        return out

    # ---- optional repair: Driver.MustClearOnlineDatas 4 -> 0
    def inspect_repair(self):
        """Returns (state, message). state: 'offer' | 'nothing' | 'stop'."""
        if REPAIR_FIELD not in self.fl:
            return "stop", (f"The field {REPAIR_FIELD} was not found in this save, so the structure is not what this "
                            "repair expects. Nothing will be changed.")
        t, _ = self.fl[REPAIR_FIELD]
        if t not in (1, 2, 3, 4, 5, 6, 7, 8, 9):   # 1 = the save's one-byte flag type (this field uses it)
            return "stop", f"{REPAIR_FIELD} is not an integer field in this save. Nothing will be changed."
        v = int(float(self.get(REPAIR_FIELD)))
        if v == REPAIR_TARGET:
            return "nothing", f"{REPAIR_FIELD} is already {REPAIR_TARGET}. There is nothing to repair."
        if v == REPAIR_EXPECTED:
            return "offer", (f"{REPAIR_FIELD} is currently {v}, the value this repair was tested against. "
                             f"The proposed change is {v} → {REPAIR_TARGET}.")
        return "stop", (f"{REPAIR_FIELD} is currently {v}. The proposed repair has only been confirmed in-game for the "
                        f"value {REPAIR_EXPECTED}, so no change is offered for {v}.")

    def apply_repair(self):
        """Writes ONLY the one field, immediately, with backup and verification. Refuses if other edits are pending."""
        state, msg = self.inspect_repair()
        if state != "offer":
            raise ValueError(msg)
        if self.dirty():
            raise ValueError("You have unsaved edits. Save or discard them first so the repair changes only its own value.")
        self.put(REPAIR_FIELD, REPAIR_TARGET)
        ch = self.changes()
        if [c[0] for c in ch] != [REPAIR_FIELD]:
            self.pt = bytearray(self.orig)
            raise ValueError("Unexpected extra differences – repair cancelled, nothing written.")
        try:
            bak = self.save_in_place()
        except Exception:
            self.pt = bytearray(self.orig)
            raise
        return bak


# =====================================================================================
#                                    HEADLESS CHECK
# =====================================================================================
def run_check(save=None):
    print(f"{APP_NAME} v{APP_VERSION} – headless check")
    for rel in ("tdu2_tool.py", "cars_database.json", "houses_database.json", "vehicle_classes.json", "garage_list.csv"):
        print(f"  {'OK     ' if os.path.exists(os.path.join(HERE, rel)) else 'MISSING'} {rel}")
    for name, ok, detail in data_status():
        print(f"  {'OK     ' if ok else 'PROBLEM'} {name}: {detail}")
    if save:
        m = SaveModel(save)
        print(f"  save loaded: profile {m.profile}, {m.nslots} garage entries, warnings: {m.warnings or 'none'}")
        for g in m.garage_groups():
            print(f"  [{g['island']}] {g['name']} ({g['occupied']}/{g['capacity']})")
            for r in g["rows"]:
                print(f"     {r['pos']}. {r['name']}  arch {r['arch']}  upg {r['upg']}  odo {r['odo']:.1f}  class {r['cls']}")


# =====================================================================================
#                                         GUI
# =====================================================================================
BG0, BG1, BG2 = "#0c1014", "#171d24", "#1f262e"
ROW_A, ROW_B = "#232a32", "#1c2229"
SEL_L, SEL_R = (156, 34, 48), (46, 28, 34)
CYAN, SILVER, TEXT, MUTED = "#d7dde3", "#cfd5db", "#f1f3f5", "#8f98a2"
OK_C, WARN_C, ERR_C = "#4cc38a", "#e0a030", "#e05260"
EDGE = "#5a636d"
OPEN_BTN_W, OPEN_BTN_H = 300, 56         # home-page Open Save button
SAVE_BTN_W, SAVE_BTN_H = OPEN_BTN_W, OPEN_BTN_H   # header Save changes button: identical size


def upg_text(u):
    """Acceleration/Top speed/Braking exactly as stored, e.g. 3/2/1."""
    return "/".join(str(int(x)) for x in u)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hexc(c):
    return "#%02x%02x%02x" % c


def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog
    import tkinter.font as tkfont
    App(tk, ttk, filedialog, tkfont).run()


class App:
    VIEWS = (("home", "HOME"), ("garage", "GARAGE EDITOR"), ("casino", "CASINO & PLAYER"),
             ("repair", "CASINO DLC / TDU LIFE REPAIR"), ("about", "INFORMATION"))

    def __init__(self, tk, ttk, filedialog, tkfont):
        self.tk, self.ttk, self.fd, self.tkfont = tk, ttk, filedialog, tkfont
        self.model = None
        self.busy = False
        self.sel_slot = None
        self.cur_hc = None
        self.groups = []
        self._home_stats = None
        self._pulse = 0
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME}")
        self.root.geometry("1360x840")
        self.root.minsize(1100, 700)
        self.root.configure(bg=BG0)
        self._pick_font()
        self._style()
        self._chrome()
        self.views = {}
        for key, _ in self.VIEWS:
            f = tk.Frame(self.body, bg=BG0)
            self.views[key] = f
        self._build_home()
        self._build_garage()
        self._build_casino()
        self._build_repair()
        self._build_about()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.show("home")
        self.notify("info", "Open your PLAYERSAVE\\DATA file to begin. Close the game first.")
        self.root.after(60, self._tick)

    # ------------------------------------------------------------------ fonts / style
    def _pick_font(self):
        have = {f.lower(): f for f in self.tkfont.families()}
        self.family = "Helvetica"
        # closest practical stand-ins for the humanist TDU2 menu face (exact game font not available)
        for cand in ("Berlin Sans FB", "Trebuchet MS", "Segoe UI", "Century Gothic", "Verdana", "Helvetica"):
            if cand.lower() in have:
                self.family = have[cand.lower()]
                break
        # application title: Elsone Italic (TDU2 cover face) if installed, otherwise the menu font in italic
        self.title_family, self.title_native_italic, self.title_is_elsone = self.family, False, False
        for low, real in have.items():
            if low.startswith("elsone"):
                self.title_family, self.title_native_italic, self.title_is_elsone = real, "italic" in low, True
                if "italic" in low:
                    break

    def F(self, size, bold=False, italic=False):
        s = ["bold"] if bold else []
        if italic:
            s.append("italic")
        return (self.family, size, " ".join(s)) if s else (self.family, size)

    def FT(self, size):
        """Font for the application title only."""
        if self.title_is_elsone:
            return (self.title_family, size) if self.title_native_italic else (self.title_family, size, "italic")
        return (self.title_family, size, "bold italic")

    def _style(self):
        st = self.ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TCombobox", fieldbackground="#0f1317", background="#2b323a", foreground="#ffffff",
                     arrowcolor=SILVER, bordercolor=EDGE, lightcolor=EDGE, darkcolor=EDGE)
        st.map("TCombobox", fieldbackground=[("readonly", "#0f1317")], foreground=[("readonly", "#ffffff")])
        st.configure("Vertical.TScrollbar", background="#2b323a", troughcolor=BG1, bordercolor=BG1, arrowcolor=SILVER)
        self.root.option_add("*TCombobox*Listbox.background", "#0f1317")
        self.root.option_add("*TCombobox*Listbox.foreground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#a22a38")

    # ------------------------------------------------------------------ small widget helpers
    def btn(self, parent, text, cmd, kind="normal", width=None):
        tk = self.tk
        base = {"normal": "#2b323a", "accent": "#8e2a36", "danger": "#7a2233", "warn": "#6b5420"}[kind]
        hover = {"normal": "#3b434d", "accent": "#b83a4a", "danger": "#a1304a", "warn": "#8a6d2a"}[kind]
        b = tk.Button(parent, text=text, command=cmd, bg=base, fg="#f1f3f5", activebackground=hover,
                      activeforeground="#ffffff", relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
                      font=self.F(10, True), highlightthickness=1, highlightbackground=EDGE, width=width or 0)
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=base))
        return b

    def entry(self, parent, var, width=12):
        return self.tk.Entry(parent, textvariable=var, width=width, bg="#0f1317", fg="#ffffff",
                             insertbackground="#ffffff", relief="flat", highlightthickness=1,
                             highlightbackground=EDGE, highlightcolor=CYAN, font=self.F(11))

    def label(self, parent, text="", size=10, bold=False, fg=TEXT, bg=None, **kw):
        return self.tk.Label(parent, text=text, font=self.F(size, bold), fg=fg, bg=bg or parent.cget("bg"), **kw)

    def sep(self, parent, pady=8):
        f = self.tk.Frame(parent, bg=parent.cget("bg"), height=2)
        f.pack(fill="x", pady=pady)
        self.tk.Frame(f, bg="#7b848e", height=1).pack(fill="x")
        self.tk.Frame(f, bg="#0d1116", height=1).pack(fill="x")
        return f

    def card(self, parent, title, accent=CYAN):
        tk = self.tk
        outer = tk.Frame(parent, bg=BG1, highlightthickness=1, highlightbackground=EDGE)
        tk.Frame(outer, bg=accent, height=3).pack(fill="x")
        self.label(outer, title, 12, True, TEXT, BG1).pack(anchor="w", padx=16, pady=(10, 4))
        return outer

    # ------------------------------------------------------------------ chrome (nav, status)
    def _chrome(self):
        tk = self.tk
        top = tk.Frame(self.root, bg=BG1)
        top.pack(fill="x")
        row1 = tk.Frame(top, bg=BG1)          # brand (left) + actions (top right)
        row1.pack(fill="x")
        # actions are packed FIRST so they always keep their space and can never be pushed out of the window
        right = tk.Frame(row1, bg=BG1)
        right.pack(side="right", padx=14, pady=5)
        brand = tk.Frame(row1, bg=BG1)
        brand.pack(side="left", padx=18, pady=6)
        tk.Label(brand, text=APP_NAME.upper(), font=self.FT(14), fg="#ffffff", bg=BG1).pack(anchor="w")
        self.label(brand, "TEST DRIVE UNLIMITED 2  •  SAVE UTILITY", 8, True, MUTED, BG1).pack(anchor="w")
        nav = tk.Frame(top, bg=BG1)           # navigation tabs, unchanged, along the top of the application
        nav.pack(side="top", anchor="w", padx=14)
        self.nav = {}
        for key, text in self.VIEWS:
            holder = tk.Frame(nav, bg=BG1, cursor="hand2")
            holder.pack(side="left", padx=2)
            lb = tk.Label(holder, text=text, font=self.F(9, True), fg=MUTED, bg=BG1, padx=12, pady=10, cursor="hand2")
            lb.pack()
            ul = tk.Frame(holder, bg=BG1, height=3)
            ul.pack(fill="x")
            for w in (holder, lb):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
            self.nav[key] = (lb, ul)
        self.btn(right, "Open save…", self.open_file).pack(side="left", padx=3)
        # Save changes: same size as the home-page Open Save button (300 x 56 px) with the same white outline
        sv = tk.Frame(right, width=SAVE_BTN_W, height=SAVE_BTN_H, bg="#d5dbe1")
        sv.pack_propagate(False)
        sv.pack(side="left", padx=3)
        self.save_btn = tk.Button(sv, text="SAVE CHANGES", command=self.save_in_place, bg="#8e2a36", fg="#ffffff",
                                  activebackground="#b83a4a", activeforeground="#ffffff", relief="flat", bd=0,
                                  cursor="hand2", font=self.F(14, True))
        self.save_btn.pack(fill="both", expand=True, padx=2, pady=2)
        self.save_btn.bind("<Enter>", lambda e: self.save_btn.configure(bg="#b83a4a"))
        self.save_btn.bind("<Leave>", lambda e: self.save_btn.configure(bg="#8e2a36"))
        self.btn(right, "More ▾", self._more_menu).pack(side="left", padx=3)
        tk.Frame(self.root, bg=CYAN, height=1).pack(fill="x")
        self.body = tk.Frame(self.root, bg=BG0)
        self.body.pack(fill="both", expand=True)
        bar = tk.Frame(self.root, bg="#10151b")
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg=EDGE, height=1).pack(fill="x")
        inner = tk.Frame(bar, bg="#10151b")
        inner.pack(fill="x")
        self.spin = tk.Canvas(inner, width=22, height=22, bg="#10151b", highlightthickness=0)
        self.spin.pack(side="left", padx=(12, 2), pady=4)
        self.spin_arc = self.spin.create_arc(3, 3, 19, 19, start=0, extent=100, style="arc", outline=CYAN, width=3, state="hidden")
        self.status_icon = tk.Label(inner, text="ℹ", font=self.F(11, True), fg=CYAN, bg="#10151b")
        self.status_icon.pack(side="left")
        self.status_var = tk.StringVar()
        tk.Label(inner, textvariable=self.status_var, font=self.F(9), fg="#aab2ba", bg="#10151b", anchor="w").pack(side="left", padx=6, fill="x", expand=True)
        self.file_var = tk.StringVar(value="No save loaded")
        tk.Label(inner, textvariable=self.file_var, font=self.F(9), fg=MUTED, bg="#10151b").pack(side="right", padx=8)
        tk.Label(inner, text=f"v{APP_VERSION}", font=self.F(9, True), fg=SILVER, bg="#10151b").pack(side="right", padx=8)
        self._notify_job = None

    def _more_menu(self):
        tk = self.tk
        m = tk.Menu(self.root, tearoff=0, bg=BG2, fg=TEXT, activebackground="#a22a38", activeforeground="#fff")
        m.add_command(label="Save as new file…", command=self.save_new)
        m.add_command(label="Verify save file", command=self.verify)
        m.add_command(label="Open garage_list.csv (reference list)", command=self.open_garage_list)
        m.add_separator()
        m.add_command(label="Restore a backup…", command=self.restore)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        x = self.root.winfo_pointerx()
        y = self.root.winfo_pointery()
        m.tk_popup(x, y)

    def show(self, key):
        for k, f in self.views.items():
            f.pack_forget()
        self.views[key].pack(fill="both", expand=True)
        for k, (lb, ul) in self.nav.items():
            on = (k == key)
            lb.configure(fg="#ffffff" if on else MUTED)
            ul.configure(bg=CYAN if on else BG1)
        self.cur_view = key
        if key == "garage":
            self.refresh_garage()
        if key in ("casino", "repair"):
            self.refresh_values()
        if key == "home":
            self.root.after(30, self._draw_home)

    def notify(self, kind, text):
        icon, col = {"ok": ("✔", OK_C), "info": ("ℹ", CYAN), "warn": ("▲", WARN_C), "err": ("✖", ERR_C)}[kind]
        self.status_icon.configure(text=icon, fg=col)
        n = len(self.model.changes()) if self.model else 0
        self.status_var.set(text + (f"    •    unsaved changes: {n}" if n else ""))
        if self._notify_job:
            self.root.after_cancel(self._notify_job)
        self._notify_job = None

    def refresh_status_counts(self):
        if self.model is None:
            return
        n = len(self.model.changes())
        cur = self.status_var.get().split("    •    unsaved")[0]
        self.status_var.set(cur + (f"    •    unsaved changes: {n}" if n else ""))

    # ------------------------------------------------------------------ dialogs
    def _dialog(self, title, message, detail=None, buttons=(("OK", True, "accent"),), width=520):
        tk = self.tk
        top = tk.Toplevel(self.root)
        top.title(title)
        top.configure(bg=BG1)
        top.transient(self.root)
        top.resizable(False, False)
        tk.Frame(top, bg=CYAN, height=3).pack(fill="x")
        self.label(top, title, 13, True, "#fff", BG1).pack(anchor="w", padx=20, pady=(14, 4))
        self.label(top, message, 10, False, TEXT, BG1, wraplength=width - 40, justify="left").pack(anchor="w", padx=20, pady=4)
        if detail:
            box = tk.Text(top, height=min(12, detail.count("\n") + 2), width=int(width / 8), bg="#10151b", fg="#aab2ba",
                          relief="flat", font=self.F(9), wrap="word", highlightthickness=1, highlightbackground=EDGE)
            box.insert("1.0", detail)
            box.configure(state="disabled")
            box.pack(padx=20, pady=6, fill="x")
        res = [None]
        row = tk.Frame(top, bg=BG1)
        row.pack(fill="x", padx=20, pady=14)

        def done(v):
            res[0] = v
            top.destroy()
        for text, val, kind in reversed(buttons):
            self.btn(row, text, lambda v=val: done(v), kind).pack(side="right", padx=4)
        top.protocol("WM_DELETE_WINDOW", lambda: done(None))
        top.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - top.winfo_reqheight()) // 3
        top.geometry(f"+{x}+{y}")
        top.grab_set()
        self.root.wait_window(top)
        return res[0]

    def info(self, title, message, detail=None):
        self._dialog(title, message, detail)

    def confirm(self, title, message, detail=None, ok="Confirm", danger=False):
        return bool(self._dialog(title, message, detail,
                                 (("Cancel", False, "normal"), (ok, True, "danger" if danger else "accent"))))

    def fail(self, ex, what="That didn’t work"):
        self.notify("err", f"{what}: {ex}")
        self.info(what, str(ex))

    # ------------------------------------------------------------------ background tasks + spinner
    def run_task(self, label, work, done):
        if self.busy:
            return
        self.busy = True
        self.notify("info", label + "…")
        self.spin.itemconfigure(self.spin_arc, state="normal")

        def target():
            try:
                self.q.put((done, work(), None))
            except Exception as ex:
                self.q.put((done, None, ex))
        threading.Thread(target=target, daemon=True).start()

    def _tick(self):
        try:
            while True:
                done, res, err = self.q.get_nowait()
                self.busy = False
                self.spin.itemconfigure(self.spin_arc, state="hidden")
                done(res, err)
        except queue.Empty:
            pass
        if self.busy:
            self._spin_angle = (getattr(self, "_spin_angle", 0) - 24) % 360
            self.spin.itemconfigure(self.spin_arc, start=self._spin_angle)
        self._pulse = (self._pulse + 1) % 40
        self._pulse_selection()
        self.root.after(45, self._tick)

    def need_model(self):
        if self.busy:
            return False
        if not self.model:
            self.notify("warn", "Open a save file first (Open save…).")
            self.info("Open a save first", "Use “Open save…” and choose your …\\PLAYERSAVE\\DATA file.")
            return False
        return True

    # ================================================================== HOME
    def _build_home(self):
        tk = self.tk
        f = self.views["home"]
        self.home = tk.Canvas(f, bg=BG0, highlightthickness=0)
        self.home.pack(fill="both", expand=True)
        self.home.bind("<Configure>", lambda e: self._draw_home())
        self._home_btn_rects = []
        self.home.bind("<Button-1>", self._home_click)
        self.home.bind("<Motion>", self._home_move)
        self._home_hover = None

    def _home_summary(self):
        """(owned vehicles, garages in use, vehicles at Stage 4) for the loaded save, cached between redraws."""
        m = self.model
        if m is None:
            return None
        key = (id(m), hash(bytes(m.pt)))
        if self._home_stats is None or self._home_stats[0] != key:
            rows = m.rows(True)
            self._home_stats = (key, (len(rows), len(m.garage_groups()), sum(1 for r in rows if r["upg"] == (4, 4, 4))))
        return self._home_stats[1]

    def _draw_home(self):
        c = self.home
        w, h = c.winfo_width(), c.winfo_height()
        if w < 200 or h < 200:
            return
        c.delete("all")
        # ---- background: deep navy gradient with TDU2-style slanted speed stripes (unchanged look, now full height)
        bands = 24
        for i in range(bands):
            t = i / (bands - 1)
            c.create_rectangle(0, h * i / bands, w, h * (i + 1) / bands + 1,
                               fill=hexc(lerp((12, 15, 19), (30, 36, 44), t)), outline="")
        lean = h * 0.55
        for off, wd, col in ((0.04, 70, "#26292d"), (0.115, 16, "#3a3c42"), (0.60, 110, "#202226"),
                             (0.715, 9, "#595d64"), (0.755, 40, "#2a2c31"), (0.865, 7, "#7d1a2e"), (0.90, 22, "#34373c")):
            x0 = w * off - lean / 2
            c.create_polygon(x0, h, x0 + wd, h, x0 + wd + lean, 0, x0 + lean, 0, fill=col, outline="")
        # ---- title, the one obvious action (Open save), one status line
        cx, cy = w / 2, h * 0.46
        c.create_text(cx, cy - 92, text=APP_NAME.upper(), fill="#ffffff", font=self.FT(26))
        c.create_text(cx, cy - 58, text="TEST DRIVE UNLIMITED 2   •   GARAGE & CASINO SAVE UTILITY", fill=CYAN, font=self.F(10, True))
        bw, bh = OPEN_BTN_W, OPEN_BTN_H
        bx0, by0 = cx - bw / 2, cy - 14
        self._home_btn_rects = []
        on = (self._home_hover == "open")
        orect = (bx0, by0, bx0 + bw, by0 + bh)
        self._home_btn_rects.append((orect, "open"))
        c.create_rectangle(orect[0] + 3, orect[1] + 3, orect[2] + 3, orect[3] + 3, fill="#080b0e", outline="")
        c.create_rectangle(*orect, fill="#d82a4c" if on else "#a22a38", outline="#d5dbe1", width=2)
        c.create_text(cx, by0 + 21, text="OPEN SAVE…", fill="#ffffff", font=self.F(14, True))
        c.create_text(cx, by0 + 42, text="choose your  …\\PLAYERSAVE\\DATA  file", fill="#ffd9df", font=self.F(8))
        stats = self._home_summary()
        if stats:
            owned, gar, s4 = stats
            c.create_text(cx, by0 + bh + 34, fill="#ffffff", font=self.F(11, True),
                          text=f"{self.model.profile}   •   {owned} vehicles   •   {gar} garages in use   •   {s4} at Stage 4")
        else:
            c.create_text(cx, by0 + bh + 34, fill=MUTED, font=self.F(9),
                          text="Close the game first and keep your own backup of the profile folder. Every save writes a verified backup.")

    def _home_hit(self, e):
        for (x0, y0, x1, y1), key in self._home_btn_rects:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return key
        return None

    def _home_click(self, e):
        if self._home_hit(e) == "open":
            self.open_file()

    def _home_move(self, e):
        k = self._home_hit(e)
        if k != self._home_hover:
            self._home_hover = k
            self.home.configure(cursor="hand2" if k else "")
            self._draw_home()

    # ================================================================== GARAGE
    ROW_H = 58

    def _build_garage(self):
        tk = self.tk
        f = self.views["garage"]
        left = tk.Frame(f, bg=BG1, width=250)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.label(left, "HOUSES & GARAGES", 10, True, CYAN, BG1).pack(anchor="w", padx=14, pady=(12, 4))
        self.hide_empty = tk.BooleanVar(value=True)
        tk.Checkbutton(left, text="Hide garages with no cars", variable=self.hide_empty, command=self.refresh_garage,
                       bg=BG1, fg=SILVER, selectcolor=BG2, activebackground=BG1, activeforeground="#fff",
                       font=self.F(9)).pack(anchor="w", padx=10)
        wrap = tk.Frame(left, bg=BG1)
        wrap.pack(fill="both", expand=True, padx=8, pady=6)
        self.house_list = tk.Listbox(wrap, bg="#181a1d", fg=TEXT, selectbackground="#a22a38", selectforeground="#fff",
                                     relief="flat", highlightthickness=0, activestyle="none", font=self.F(10), exportselection=False)
        sb = self.ttk.Scrollbar(wrap, orient="vertical", command=self.house_list.yview)
        self.house_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.house_list.pack(side="left", fill="both", expand=True)
        self.house_list.bind("<<ListboxSelect>>", self._on_house_pick)
        self.btn(left, "Unrecognised vehicles…", self.show_unrecognised).pack(fill="x", padx=10, pady=(0, 10))

        right = tk.Frame(f, bg=BG0, width=400)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self._build_editor(right)

        mid = tk.Frame(f, bg=BG0)
        mid.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        self.gcanvas = tk.Canvas(mid, bg=BG0, highlightthickness=0)
        self.gcanvas.pack(fill="both", expand=True)
        self.gcanvas.bind("<Configure>", lambda e: self.draw_house())
        self.gcanvas.bind("<Button-1>", self._garage_click)
        self.gcanvas.bind("<MouseWheel>", lambda e: None)
        self.root.bind("<Up>", lambda e: self._move_sel(-1))
        self.root.bind("<Down>", lambda e: self._move_sel(1))
        self.root.bind("<Left>", lambda e: self._move_house(-1))
        self.root.bind("<Right>", lambda e: self._move_house(1))

    def _build_editor(self, parent):
        tk = self.tk
        p = tk.Frame(parent, bg=BG1, highlightthickness=1, highlightbackground=EDGE)
        p.pack(fill="both", expand=True, padx=(0, 12), pady=12)
        tk.Frame(p, bg=CYAN, height=3).pack(fill="x")
        actions = tk.Frame(p, bg=BG1)               # packed first so the buttons are never pushed out of view
        actions.pack(side="bottom", fill="x", pady=(0, 6))
        self.label(p, "SELECTED VEHICLE", 9, True, CYAN, BG1).pack(anchor="w", padx=16, pady=(10, 0))
        self.v_title = tk.StringVar(value="Select a vehicle")
        tk.Label(p, textvariable=self.v_title, font=self.F(14, True), fg="#fff", bg=BG1, wraplength=350, justify="left").pack(anchor="w", padx=16, pady=(2, 0))
        self.v_sub = tk.StringVar(value="Choose a house, then a numbered slot.")
        tk.Label(p, textvariable=self.v_sub, font=self.F(9), fg=MUTED, bg=BG1, wraplength=350, justify="left").pack(anchor="w", padx=16)
        self.v_note = tk.StringVar()
        tk.Label(p, textvariable=self.v_note, font=self.F(9), fg=WARN_C, bg=BG1, wraplength=350, justify="left").pack(anchor="w", padx=16, pady=(2, 0))
        self.sep(p).pack_configure(padx=16)
        grid = tk.Frame(p, bg=BG1)
        grid.pack(fill="x", padx=16)
        self.label(grid, "Change car to", 9, False, MUTED, BG1).grid(row=0, column=0, sticky="w")
        self.car_pick = tk.StringVar()
        self.combo = self.ttk.Combobox(grid, textvariable=self.car_pick, width=40)
        self.combo.grid(row=1, column=0, columnspan=3, sticky="we", pady=(0, 6))
        self.label(grid, "Archetype ID", 9, False, MUTED, BG1).grid(row=2, column=0, sticky="w")
        self.arch_var = tk.StringVar()
        self.entry(grid, self.arch_var, 12).grid(row=3, column=0, sticky="w", pady=(0, 6))
        self.label(grid, "Odometer (km)", 9, False, MUTED, BG1).grid(row=2, column=1, sticky="w", padx=(14, 0))
        self.odo_var = tk.StringVar()
        self.entry(grid, self.odo_var, 12).grid(row=3, column=1, sticky="w", padx=(14, 0), pady=(0, 6))
        self.upg_vars = [tk.StringVar(value="0") for _ in range(3)]
        for i, lab in enumerate(("Acceleration", "Top speed", "Braking")):
            self.label(grid, lab + " 0–4", 9, False, MUTED, BG1).grid(row=4, column=i, sticky="w", padx=(0 if i == 0 else 14, 0))
            self.entry(grid, self.upg_vars[i], 6).grid(row=5, column=i, sticky="w", padx=(0 if i == 0 else 14, 0))
        self.v_stats = tk.StringVar()
        tk.Label(p, textvariable=self.v_stats, font=self.F(9), fg=SILVER, bg=BG1, justify="left", anchor="w").pack(fill="x", padx=16, pady=(8, 0))
        self.sep(actions, 4).pack_configure(padx=16)
        for txt, cmd, kind in (("Apply to this slot", self.apply_slot, "accent"),
                               ("Stage 4 – this vehicle", lambda: self.quick_upg(4), "normal"),
                               ("Stage 4 – every vehicle in this garage", self.max_house, "normal"),
                               ("Stage 4 – all owned vehicles", self.max_all, "normal"),
                               ("Remove upgrades – this vehicle", lambda: self.quick_upg(0), "normal")):
            b = self.btn(actions, txt, cmd, kind)
            b.configure(pady=4)
            b.pack(fill="x", padx=16, pady=2)
        self.label(actions, "Changes stay in memory until you press “Save changes”.", 8, False, MUTED, BG1).pack(anchor="w", padx=16, pady=(4, 0))

    # ---- drawing helpers
    def _island_badge(self, c, x, y, island, size=46):
        pal = {"Ibiza": ("#1b6fd1", "#0d3f87", "IBIZA"), "Hawaii": ("#22a67f", "#0e6b57", "HAWAII")}.get(island, ("#59616b", "#2f363e", "?"))
        c.create_rectangle(x, y, x + size, y + size, fill=pal[0], outline="#cfd5db", width=2)
        c.create_rectangle(x + 2, y + size * 0.55, x + size - 2, y + size - 2, fill=pal[1], outline="")
        c.create_text(x + size / 2, y + 9, text=pal[2], fill="#ffffff", font=self.F(7, True))
        c.create_text(x + size / 2, y + size * 0.66, text="●" if island else "?", fill="#f1f3f5", font=self.F(12, True))

    def _upg_badge(self, c, x, y, stage, mixed=False, s=44):
        c.create_rectangle(x, y, x + s, y + s, fill="#2a313a", outline="#d5dbe1", width=1)
        col = "#e0431f" if stage == 4 else "#b8c0c8"
        for i in range(3):
            c.create_line(x + 6, y + 9 + i * 8, x + s - 12 - (2 - i) * 4, y + 9 + i * 8, fill=col, width=4)
        if not mixed:
            c.create_text(x + s - 9, y + s - 10, text=str(stage), fill="#fff", font=self.F(11, True))

    def _grad_row(self, c, x0, y0, x1, y1):
        steps = 40
        w = (x1 - x0) / steps
        for i in range(steps):
            t = i / (steps - 1)
            c.create_rectangle(x0 + i * w, y0, x0 + (i + 1) * w + 1, y1, fill=hexc(lerp(SEL_L, SEL_R, t)), outline="")

    # ---- garage content
    def _cur_group(self):
        for g in self.groups:
            if g["hc"] == self.cur_hc:
                return g
        return None

    def refresh_garage(self):
        if not self.model:
            self.groups = []
            self.house_list.delete(0, "end")
            self.draw_house()
            return
        keep = self.sel_slot
        self.groups = self.model.garage_groups(hide_empty_garages=bool(self.hide_empty.get()))
        self.house_list.delete(0, "end")
        for g in self.groups:
            isl = (g["island"] or "?")[:3].upper()
            cap = g["capacity"] if g["capacity"] is not None else "?"
            self.house_list.insert("end", f"{isl}  {g['name']}  ({g['occupied']}/{cap})")
        if not any(g["hc"] == self.cur_hc for g in self.groups):
            self.cur_hc = self.groups[0]["hc"] if self.groups else None
        for i, g in enumerate(self.groups):
            if g["hc"] == self.cur_hc:
                self.house_list.selection_clear(0, "end")
                self.house_list.selection_set(i)
                self.house_list.see(i)
        if keep is not None and not any(r["slot"] == keep for g in self.groups for r in g["rows"]):
            self.sel_slot = None
        g = self._cur_group()
        if self.sel_slot is None and g and g["rows"]:
            first = next((r for r in g["rows"] if r["arch"]), g["rows"][0])
            self.sel_slot = first["slot"]
        self.draw_house()
        self.fill_editor()

    def _on_house_pick(self, e):
        s = self.house_list.curselection()
        if s and s[0] < len(self.groups):
            self.cur_hc = self.groups[s[0]]["hc"]
            self.sel_slot = None
            g = self._cur_group()
            if g and g["rows"]:
                self.sel_slot = next((r for r in g["rows"] if r["arch"]), g["rows"][0])["slot"]
            self.draw_house()
            self.fill_editor()

    def _typing(self):
        w = self.root.focus_get()
        return bool(w is not None and w.winfo_class() in ("Entry", "TCombobox", "Text", "Listbox", "TEntry"))

    def _move_house(self, d):
        if self.cur_view != "garage" or not self.groups or self._typing():
            return
        idx = next((i for i, g in enumerate(self.groups) if g["hc"] == self.cur_hc), 0)
        idx = (idx + d) % len(self.groups)
        self.house_list.selection_clear(0, "end")
        self.house_list.selection_set(idx)
        self._on_house_pick(None)
        self.house_list.see(idx)

    def _move_sel(self, d):
        g = self._cur_group()
        if self.cur_view != "garage" or not g or self._typing():
            return
        rows = [r for r in g["rows"] if r["arch"]]
        if not rows:
            return
        idx = next((i for i, r in enumerate(rows) if r["slot"] == self.sel_slot), -1)
        self.sel_slot = rows[max(0, min(len(rows) - 1, idx + d))]["slot"]
        self.draw_house()
        self.fill_editor()

    def draw_house(self):
        c = self.gcanvas
        c.delete("all")
        self._sel_rect = None
        w = max(c.winfo_width(), 400)
        g = self._cur_group()
        if not self.model or not g:
            c.create_text(w / 2, 140, text="No garage to show yet" if self.model else "Open a save file to browse your garages",
                          fill=SILVER, font=self.F(16, True))
            c.create_text(w / 2, 175, text="Garages are grouped by the house each vehicle is stored in." if self.model
                          else "Use “Open save…” and choose …\\PLAYERSAVE\\DATA", fill=MUTED, font=self.F(10))
            return
        cap = g["capacity"]
        nrows = max(len(g["rows"]), cap or 0, 6)
        # header (in the style of the in-game list header)
        c.create_polygon(0, 78, 40, 8, w - 4, 8, w - 4, 78, fill="#1c1e21", outline="#9aa3ad", width=1)
        c.create_text(60, 44, text="◀", fill="#d5dbe1", font=self.F(16, True))
        self._island_badge(c, 92, 16, g["island"])
        c.create_text(156, 30, anchor="w", text=g["name"], fill="#ffffff", font=self.F(16, True))
        capt = f"{g['occupied']}/{cap}" if cap else f"{g['occupied']} vehicle(s)"
        sub = f"({capt} slots used)"
        if g["info"] is None:
            sub += "   –   house not in houses_database.json"
        c.create_text(156, 58, anchor="w", text=sub, fill=SILVER, font=self.F(10))
        c.create_text(w - 24, 44, text="▶", fill="#d5dbe1", font=self.F(16, True))
        top = 88
        c.create_rectangle(0, top, w - 4, top + nrows * self.ROW_H + 8, fill="#161b21", outline="#9aa3ad")
        self._sel_rect = None
        for i in range(nrows):
            y = top + 4 + i * self.ROW_H
            r = g["rows"][i] if i < len(g["rows"]) else None
            selected = bool(r and r["slot"] == self.sel_slot and r["arch"])
            if selected:
                self._grad_row(c, 4, y, w - 8, y + self.ROW_H - 2)
                self._sel_rect = c.create_rectangle(4, y, 9, y + self.ROW_H - 2, fill="#ff8aa0", outline="")
            else:
                c.create_rectangle(4, y, w - 8, y + self.ROW_H - 2, fill=ROW_A if i % 2 == 0 else ROW_B, outline="")
            cy = y + self.ROW_H / 2 - 1
            c.create_oval(18, cy - 22, 62, cy + 22, fill="#11161b", outline="#d5dbe1", width=2)
            c.create_text(40, cy, text=str(i + 1), fill="#ffffff", font=self.F(20, True))       # slot number: largest text
            if r and r["arch"]:
                u = r["upg"]
                self._upg_badge(c, 76, cy - 22, u[0], mixed=len(set(u)) > 1)
                name = r["name"]
                colr = "#ffffff" if selected else ("#f3d08a" if not r["identified"] else "#e3e7ea")
                nid = c.create_text(138, cy - 6, anchor="w", text=name, fill=colr, font=self.F(13, selected))
                nb = c.bbox(nid)
                c.create_text((nb[2] if nb else 138) + 12, cy - 5, anchor="w", text=upg_text(u),
                              fill="#ffffff" if selected else "#e9eef2", font=self.F(11, True))
                c.create_text(138, cy + 14, anchor="w", text=f"{r['odo']:,.0f} km   •   archetype {r['arch']}", fill="#9aa3ad", font=self.F(8))
                if not r["identified"]:
                    c.create_text(w - 22, cy, anchor="e", text="UNRECOGNISED ID", fill=WARN_C, font=self.F(8, True))
            else:
                c.create_rectangle(76, cy - 22, 120, cy + 22, fill="#12171d", outline="#343d48")
                c.create_text(138, cy, anchor="w", text="--", fill="#8a939d", font=self.F(13))
        yb = top + nrows * self.ROW_H + 18
        c.create_text(4, yb, anchor="nw", fill=MUTED, font=self.F(8),
                      text="Slot numbers follow the order of this house’s entries in the save. "
                           "Upgrade levels beside each name = Acceleration/Top speed/Braking.")
        c.configure(scrollregion=(0, 0, w, yb + 40))

    def _pulse_selection(self):
        if getattr(self, "cur_view", "") != "garage" or not getattr(self, "_sel_rect", None):
            return
        t = abs(20 - self._pulse) / 20.0
        try:
            self.gcanvas.itemconfigure(self._sel_rect, fill=hexc(lerp((255, 138, 160), (255, 214, 224), t)))
        except Exception:
            self._sel_rect = None

    def _garage_click(self, e):
        g = self._cur_group()
        if not g:
            return
        w = self.gcanvas.winfo_width()
        if e.y < 88:
            if e.x < 90:
                self._move_house(-1)
            elif e.x > w - 60:
                self._move_house(1)
            return
        i = int((e.y - 92) // self.ROW_H)
        if 0 <= i < len(g["rows"]) and g["rows"][i]["arch"]:
            self.sel_slot = g["rows"][i]["slot"]
            self.draw_house()
            self.fill_editor()

    def _sel_row(self):
        g = self._cur_group()
        if g:
            for r in g["rows"]:
                if r["slot"] == self.sel_slot:
                    return g, r
        return g, None

    def fill_editor(self):
        g, r = self._sel_row()
        if not r or not self.model:
            self.v_title.set("Select a vehicle")
            self.v_sub.set("Choose a house, then a numbered slot.")
            self.v_note.set("")
            self.v_stats.set("")
            return
        r = {**self.model.row(r["slot"]), "pos": r["pos"], "identified": r["identified"]}
        self.v_title.set(r["name"])
        loc = f"{g['name']} ({g['island'] or 'location unknown'})  •  slot {r['pos']}"
        self.v_sub.set(f"{loc}\nArchetype {r['arch']}  •  car ID {r['carid']}  •  save entry Garage[{r['slot']}]")
        notes = []
        if not r["identified"]:
            notes.append("This archetype ID is not in your vehicle database (identity unconfirmed).")
        self.v_note.set("  ".join(notes))
        rec = self.model.car_db.get(r["arch"], {})
        bits = []
        if rec.get("power_bhp"):
            bits.append(f"{rec['power_bhp']} bhp")
        if rec.get("top_speed"):
            bits.append(f"{rec['top_speed']:.0f} km/h")
        self.v_stats.set("   •   ".join(bits))
        self.car_pick.set("")
        self.arch_var.set(str(r["arch"]))
        for v, x in zip(self.upg_vars, r["upg"]):
            v.set(str(x))
        self.odo_var.set(f"{r['odo']:.1f}")
        if not self.combo.cget("values"):
            vals = [f"{k} – {v}" for k, v in sorted(self.model.cars.items(), key=lambda kv: kv[1].lower())]
            self.combo.configure(values=vals)

    def show_unrecognised(self):
        if not self.need_model():
            return
        bad, lines = [], []
        for g in self.model.garage_groups(False):
            for r in g["rows"]:
                if not r["identified"]:
                    bad.append(r)
                    lines.append(f"Archetype {r['arch']}  –  {g['name']}, slot {r['pos']} (save entry {r['slot']})")
        if not bad:
            self.info("Unrecognised vehicles", "Every owned vehicle’s archetype ID is in your vehicle database.")
            return
        self.info("Unrecognised vehicles",
                  f"{len(bad)} owned vehicle(s) have an archetype ID that is not in the vehicle database. "
                  "Their identity is not guessed here; add them to cars_database.json once confirmed.", "\n".join(lines))

    # ---- garage actions (all in memory until saved)
    def apply_slot(self):
        if not self.need_model():
            return
        if self.sel_slot is None:
            self.notify("warn", "Select a vehicle first.")
            return
        slot = self.sel_slot
        try:
            pick = self.car_pick.get().strip()
            new_arch = int(pick.split("–")[0].strip()) if pick else int(self.arch_var.get())
            cur = int(self.model.get(f"Garage[{slot}].Car.Archetype"))
            if self.model.cars and new_arch not in self.model.cars and new_arch != cur:
                if not self.confirm("Unknown car ID", f"{new_arch} is not in the vehicle database. Use it anyway?", ok="Use it"):
                    return
            ups = [int(v.get()) for v in self.upg_vars]
            odo = self.odo_var.get()
            self.model.set_archetype(slot, new_arch)
            self.model.set_upgrades(slot, *ups)
            self.model.set_odometer(slot, odo)
        except Exception as ex:
            self.fail(ex, "Vehicle not updated")
            return
        self.refresh_garage()
        self.notify("ok", f"Vehicle updated: {self.model.car_name(new_arch)} (in memory – press Save changes).")

    def quick_upg(self, n):
        if not self.need_model() or self.sel_slot is None:
            return
        try:
            self.model.set_upgrades(self.sel_slot, n, n, n)
        except Exception as ex:
            self.fail(ex)
            return
        self.refresh_garage()
        self.notify("ok", "Stage 4 upgrade applied to this vehicle." if n == 4 else "Upgrades removed from this vehicle.")

    def max_house(self):
        if not self.need_model():
            return
        g = self._cur_group()
        if not g:
            return
        rows = [r for r in g["rows"] if r["arch"]]
        if not self.confirm("Stage 4 – whole garage", f"Set all {len(rows)} vehicle(s) in {g['name']} to Stage 4 (4/4/4)?", ok="Apply"):
            return
        try:
            for r in rows:
                self.model.set_upgrades(r["slot"], 4, 4, 4)
        except Exception as ex:
            self.fail(ex)
            return
        self.refresh_garage()
        self.notify("ok", f"Stage 4 applied to {len(rows)} vehicle(s) in {g['name']} (in memory).")

    def max_all(self):
        if not self.need_model():
            return
        if self.confirm("Stage 4 – all owned vehicles", "Set ALL owned cars to upgrade level 4/4/4? (Stage 4 is the normal maximum.)", ok="Apply to all"):
            try:
                n = self.model.max_upgrades_all()
            except Exception as ex:
                self.fail(ex)
                return
            self.refresh_garage()
            self.notify("ok", f"Stage 4 applied to {n} vehicle(s) (in memory).")

    # ================================================================== CASINO & PLAYER
    def _build_casino(self):
        tk = self.tk
        f = self.views["casino"]
        wrap = tk.Frame(f, bg=BG0)
        wrap.pack(fill="both", expand=True, padx=28, pady=22)
        self.label(wrap, "CASINO & PLAYER EDITOR", 16, True, "#fff", BG0).pack(anchor="w")
        self.label(wrap, "Edits are made in memory. Press “Save changes” (top right) to write them, with an automatic backup.", 9, False, MUTED, BG0).pack(anchor="w", pady=(2, 12))
        row = tk.Frame(wrap, bg=BG0)
        row.pack(fill="x")
        self.val_labels = {}
        self.num_vars = {}
        for col, (path, title, hint) in enumerate((
                ("Driver.Money", "Player money", "Cash on hand"),
                ("Casino.money", "Casino chips", "Field: Casino.money"),
                ("Driver.NbCoupon", "Casino coupons", "Field: Driver.NbCoupon"))):
            c = self.card(row, title)
            c.grid(row=0, column=col, sticky="nsew", padx=6)
            row.grid_columnconfigure(col, weight=1)
            vl = tk.StringVar(value="–")
            self.val_labels[path] = vl
            tk.Label(c, textvariable=vl, font=self.F(20, True), fg="#fff", bg=BG1).pack(anchor="w", padx=16)
            self.label(c, hint, 8, False, MUTED, BG1).pack(anchor="w", padx=16)
            v = tk.StringVar()
            self.num_vars[path] = v
            line = tk.Frame(c, bg=BG1)
            line.pack(fill="x", padx=16, pady=12)
            self.entry(line, v, 14).pack(side="left")
            self.btn(line, "Set", lambda p=path, t=title: self.set_number(p, t), "accent").pack(side="left", padx=8)
        vip = self.card(wrap, "Casino VIP – Unlock Global Level 5")
        vip.pack(fill="x", padx=6, pady=14)
        self.label(vip, "Sets your Global Casino Level to 5, granting access to the VIP Terrace and its exclusive rewards, "
                        "including the Spyker C8 Aileron Spyder.", 10, False, TEXT, BG1, wraplength=900, justify="left").pack(anchor="w", padx=16)
        self.label(vip, "It does not directly give you the Spyker C8 Aileron Spyder, and it is not a separate VIP level.", 9, False, MUTED, BG1).pack(anchor="w", padx=16, pady=(2, 0))
        self.btn(vip, "Unlock Global Level 5…", lambda: self.preset("vip-access"), "accent").pack(anchor="w", padx=16, pady=12)
        adv = self.card(wrap, "Advanced casino presets (from the original editor)", accent="#7b848e")
        adv.pack(fill="x", padx=6)
        line = tk.Frame(adv, bg=BG1)
        line.pack(fill="x", padx=16, pady=(0, 12))
        self.btn(line, "Casino cosmetics…", lambda: self.preset("casino-cosmetics")).pack(side="left", padx=(0, 8))
        self.btn(line, "Reward-car flags (riskiest)…", lambda: self.preset("vip-car-flags"), "warn").pack(side="left")
        self.label(adv, "Reward-car flags do not add any car to your garage and touch the same area as the original Casino problem.", 8, False, MUTED, BG1).pack(anchor="w", padx=16, pady=(0, 10))

    def refresh_values(self):
        for path, v in getattr(self, "val_labels", {}).items():
            if self.model and self.model.has(path):
                try:
                    v.set(f"{int(float(self.model.get(path))):,}")
                except Exception:
                    v.set(self.model.get(path))
            else:
                v.set("–" if not self.model else "field not found")
        self._refresh_repair()

    def set_number(self, path, label):
        if not self.need_model():
            return
        try:
            if not self.model.has(path):
                raise ValueError(f"The field {path} was not found in this save.")
            raw = self.num_vars[path].get().replace(",", "").strip()
            try:
                v = int(raw)
            except ValueError:
                raise ValueError("Please enter a whole number.")
            if not (0 <= v <= 2147483647):
                raise ValueError("Value must be between 0 and 2,147,483,647.")
            self.model.set_value(path, v)
        except ValueError as ex:
            self.fail(ex, f"{label} not changed")
            return
        self.refresh_values()
        self.notify("ok", f"{label} set to {v:,} (in memory – press Save changes).")

    def preset(self, key):
        if not self.need_model():
            return
        try:
            desc, _ = tool.PRESETS[key]
            _, ch = self.model.preset_preview(key)
        except Exception as ex:
            self.fail(ex, "Preset unavailable")
            return
        if not ch:
            self.info("Nothing to do", "Everything in this preset is already set.")
            return
        lines = "\n".join(f"{p}:  {a} → {b}" for p, a, b in ch)
        if key == "vip-access":
            lvl = self.model.level_like_fields()
            lines += "\n\nCasino fields in this save whose names mention “level” (information only, not changed):\n" + (
                "\n".join(f"{p} = {v}" for p, v in lvl) if lvl else "none found")
            desc = ("Casino VIP – Unlock Global Level 5. Sets your Global Casino Level to 5 (VIP Terrace access) using the same "
                    "values as the original VIP preset (_vip_status and the VIP unlock bit). It does not directly give you the Spyker C8 Aileron Spyder.")
        if self.confirm("Apply in memory?", desc + "\n\nNothing is written to disk until you press Save changes.", lines, ok="Apply"):
            try:
                self.model.apply_preset(key)
            except Exception as ex:
                self.fail(ex)
                return
            self.refresh_values()
            self.notify("ok", f"Preset applied in memory ({len(ch)} field(s)). Press Save changes to write it.")

    # ================================================================== REPAIR (separate, optional)
    def _build_repair(self):
        tk = self.tk
        f = self.views["repair"]
        wrap = tk.Frame(f, bg=BG0)
        wrap.pack(fill="both", expand=True, padx=28, pady=22)
        self.label(wrap, "CASINO DLC / TDU LIFE REPAIR", 16, True, "#fff", BG0).pack(anchor="w")
        self.label(wrap, "OPTIONAL  •  PROPOSED REPAIR", 9, True, WARN_C, BG0).pack(anchor="w", pady=(2, 10))
        c = self.card(wrap, "What this does", accent=WARN_C)
        c.pack(fill="x", padx=6)
        self.label(c, f"This proposed repair changes one value, {REPAIR_FIELD}, from {REPAIR_EXPECTED} to {REPAIR_TARGET}. It was confirmed "
                      "in-game by the author only from the value 4 in one savegame. It is not a guaranteed fix for every Casino DLC or TDU Life "
                      "problem, and nothing else (Casino, MyLife, RewardCars, garage data) is touched.", 10, False, TEXT, BG1,
                   wraplength=950, justify="left").pack(anchor="w", padx=16, pady=(0, 6))
        self.label(c, "The tool checks the field first, makes a verified backup, changes only that value, re-encrypts and re-reads the file to verify it.",
                   9, False, MUTED, BG1, wraplength=950, justify="left").pack(anchor="w", padx=16, pady=(0, 12))
        s = self.card(wrap, "Inspection", accent=WARN_C)
        s.pack(fill="x", padx=6, pady=12)
        self.rep_state = tk.StringVar(value="Open a save file, then press Inspect.")
        tk.Label(s, textvariable=self.rep_state, font=self.F(11), fg=TEXT, bg=BG1, wraplength=950, justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        line = tk.Frame(s, bg=BG1)
        line.pack(anchor="w", padx=16, pady=(0, 12))
        self.btn(line, "Inspect save", self.inspect_repair).pack(side="left")
        self.rep_btn = self.btn(line, f"Apply proposed repair ({REPAIR_EXPECTED} → {REPAIR_TARGET})…", self.do_repair, "warn")
        self.rep_btn.pack(side="left", padx=10)
        self.rep_btn.configure(state="disabled")

    def _refresh_repair(self):
        if hasattr(self, "rep_btn") and not self.model:
            self.rep_state.set("Open a save file, then press Inspect.")
            self.rep_btn.configure(state="disabled")

    def inspect_repair(self):
        if not self.need_model():
            return
        state, msg = self.model.inspect_repair()
        self.rep_state.set(("✔ " if state == "offer" else "ℹ " if state == "nothing" else "▲ ") + msg)
        self.rep_btn.configure(state="normal" if state == "offer" else "disabled")
        self.notify("info" if state != "stop" else "warn", "Inspection complete.")

    def do_repair(self):
        if not self.need_model():
            return
        state, msg = self.model.inspect_repair()
        if state != "offer":
            self.inspect_repair()
            return
        if self.model.dirty():
            self.info("Unsaved edits pending", "Save or discard your other edits first, so the repair changes only its own value.")
            return
        if not self.confirm("Apply proposed repair?", msg + "\n\nA verified backup is made first. The game must be closed.",
                            ok="Apply repair", danger=True):
            return
        m = self.model

        def done(bak, err):
            if err:
                self.fail(err, "Repair not applied")
                return
            self.notify("ok", f"Repair applied and verified. Backup: {os.path.basename(bak)}")
            self.inspect_repair()
            self.info("Repair complete", f"{REPAIR_FIELD} is now {REPAIR_TARGET}. The saved file was re-read and verified.\nBackup: {bak}")
        self.run_task("Applying repair and verifying", m.apply_repair, done)

    # ================================================================== ABOUT
    def _build_about(self):
        tk = self.tk
        f = self.views["about"]
        wrap = tk.Frame(f, bg=BG0)
        wrap.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(wrap, text=APP_NAME.upper(), font=self.FT(16), fg="#fff", bg=BG0).pack(anchor="w")
        self.label(wrap, f"Version {APP_VERSION}   •   Test Drive Unlimited 2 / Project Paradise 2 save utility", 9, False, MUTED, BG0).pack(anchor="w", pady=(2, 10))
        self.label(wrap,
                   "• Edits vehicles you already own: archetype ID, upgrades 0–4 (Stage 4 = 4/4/4), odometer.\n"
                   "• Edits player money, casino chips and coupons, and the Casino VIP option (Global Casino Level 5).\n"
                   "• Cannot add or remove garage slots, edit text, or create cars from nothing.\n"
                   "• Every save to disk makes a verified backup first, validates the data and re-reads the written file. "
                   "Restore a backup from “More ▾”.\n"
                   "• Always close the game before saving, and keep your own backup of the whole profile folder.\n"
                   "• Vehicle class badges come from your screenshots; vehicles missing from the database show as unrecognised, never guessed.",
                   10, False, TEXT, BG0, wraplength=1000, justify="left").pack(anchor="w")
        self.sep(wrap, 12)
        self.label(wrap, "DATA FILES IN USE (loaded from this program's folder – replace them to update the lists)", 9, True, CYAN, BG0).pack(anchor="w")
        box = tk.Frame(wrap, bg=BG1, highlightthickness=1, highlightbackground=EDGE)
        box.pack(anchor="w", fill="x", pady=8)
        for name, ok, detail in data_status():
            line = tk.Frame(box, bg=BG1)
            line.pack(fill="x", padx=14, pady=3)
            tk.Label(line, text="✔" if ok else "▲", font=self.F(10, True), fg=OK_C if ok else WARN_C, bg=BG1, width=2).pack(side="left")
            tk.Label(line, text=name, font=self.F(10, True), fg=TEXT, bg=BG1, width=22, anchor="w").pack(side="left")
            tk.Label(line, text=detail, font=self.F(9), fg=MUTED, bg=BG1, anchor="w").pack(side="left")
        self.label(wrap, "Two Lexus LFA entries (Mililani Haven of Peace) and the Bugatti Divo / EB110SS pair (Kaukonahua Home) could not be told apart "
                         "from their look-alike houses, so those four vehicles show as an unrecognised house rather than a guessed one.",
                   9, False, MUTED, BG0, wraplength=1000, justify="left").pack(anchor="w", pady=(4, 0))

    def open_garage_list(self):
        """Opens the bundled garage_list.csv reference list with the system's default program."""
        if not os.path.exists(GARAGE_LIST):
            self.info("garage_list.csv not found", "The reference list should sit next to the program:\n" + GARAGE_LIST)
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(GARAGE_LIST)                     # Windows
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", GARAGE_LIST])
        except Exception as ex:
            self.info("Could not open the list", f"{ex}\n\nYou can open it yourself:\n{GARAGE_LIST}")

    # ================================================================== FILE actions
    def open_file(self):
        if self.busy:
            return
        if self.model and self.model.dirty() and not self.confirm("Unsaved changes", "Opening another save discards your unsaved edits. Continue?", ok="Discard and open", danger=True):
            return
        path = self.fd.askopenfilename(title="Choose PLAYERSAVE\\DATA", filetypes=[("TDU2 save DATA", "DATA"), ("All files", "*")])
        if not path:
            return
        prof = detect_profile(path)
        if not prof:
            prof = self._ask_text("Profile name", "Profile name (the folder name, e.g. Rynzler):")
            if not prof:
                return

        def done(model, err):
            if err:
                self.fail(err, "Save file could not be read")
                return
            self.model = model
            self.sel_slot, self.cur_hc = None, None
            self.combo.configure(values=[f"{k} – {v}" for k, v in sorted(model.cars.items(), key=lambda kv: kv[1].lower())])
            self.file_var.set(f"{model.profile}  •  {os.path.basename(path)}")
            self.refresh_garage()
            self.refresh_values()
            warn = ("  " + "; ".join(model.warnings)) if model.warnings else ""
            self.notify("ok" if not warn else "warn",
                        f"Save file loaded: profile {model.profile}, {model.nslots} garage entries, all checksums valid.{warn}")
            self.show("garage")
        self.run_task("Loading and verifying save file", lambda: SaveModel(path, prof), done)

    def _ask_text(self, title, prompt):
        tk = self.tk
        top = tk.Toplevel(self.root)
        top.title(title)
        top.configure(bg=BG1)
        top.transient(self.root)
        self.label(top, prompt, 10, False, TEXT, BG1).pack(padx=20, pady=(16, 6))
        v = tk.StringVar()
        e = self.entry(top, v, 30)
        e.pack(padx=20)
        out = [None]

        def ok():
            out[0] = v.get().strip() or None
            top.destroy()
        self.btn(top, "OK", ok, "accent").pack(pady=14)
        e.focus_set()
        top.bind("<Return>", lambda ev: ok())
        top.grab_set()
        self.root.wait_window(top)
        return out[0]

    def save_in_place(self):
        if not self.need_model():
            return
        n = len(self.model.changes())
        if n == 0:
            self.notify("info", "There are no changes to save.")
            return
        if not self.confirm("Save changes", f"{n} field(s) changed.\nA verified backup is made next to the file first, then the written file is re-read and verified.\nThe game must be closed.",
                            ok="Save", danger=False):
            return
        m = self.model

        def done(bak, err):
            if err:
                self.fail(err, "Save not written")
                return
            self.notify("ok", f"Saved and verified. Backup created: {os.path.basename(bak)}")
            self.refresh_garage()
        self.run_task("Validating, backing up and writing save", m.save_in_place, done)

    def save_new(self):
        if not self.need_model():
            return
        out = self.fd.asksaveasfilename(title="Save as new file", initialfile="DATA.new")
        if not out:
            return
        m = self.model

        def done(res, err):
            if err:
                self.fail(err, "Save not written")
                return
            self.notify("ok", f"Saved a new file: {res} (your original is untouched).")
        self.run_task("Validating and writing new file", lambda: m.save_new(out), done)

    def verify(self):
        if not self.need_model():
            return
        m = self.model

        def done(rep, err):
            if err:
                self.fail(err, "Save verification failed")
                return
            ok = all(o for o, _ in rep)
            self.notify("ok" if ok else "warn", "Save verification passed." if ok else "Verification finished with a warning.")
            self.info("Save verification", "Result for the file on disk:", "\n".join(("✔ " if o else "▲ ") + t for o, t in rep))
        self.run_task("Verifying save file", m.verify_report, done)

    def restore(self):
        if not self.need_model():
            return
        bs = self.model.backups()
        if not bs:
            self.info("No backups", "No backups were found next to this save file.")
            return
        tk = self.tk
        top = tk.Toplevel(self.root)
        top.title("Restore a backup")
        top.configure(bg=BG1)
        top.transient(self.root)
        self.label(top, "Choose a backup (newest at the bottom)", 11, True, "#fff", BG1).pack(padx=20, pady=(14, 6), anchor="w")
        lb = tk.Listbox(top, width=70, height=min(12, len(bs)), bg="#181a1d", fg=TEXT, selectbackground="#a22a38", relief="flat", font=self.F(9), exportselection=False)
        for b in bs:
            lb.insert("end", os.path.basename(b))
        lb.selection_set("end")
        lb.pack(padx=20)
        chosen = [None]

        def go():
            s = lb.curselection()
            if s:
                chosen[0] = bs[s[0]]
            top.destroy()
        row = tk.Frame(top, bg=BG1)
        row.pack(pady=14)
        self.btn(row, "Cancel", top.destroy).pack(side="left", padx=4)
        self.btn(row, "Restore selected", go, "danger").pack(side="left", padx=4)
        top.grab_set()
        self.root.wait_window(top)
        src = chosen[0]
        if not src:
            return
        if not self.confirm("Restore backup", f"Put back:\n{os.path.basename(src)}\n\nYour current file is kept as “before-restore”.", ok="Restore", danger=True):
            return
        m = self.model

        def work():
            r = SaveModel.restore_backup(m.path, m.profile, src)
            return r, SaveModel(m.path, m.profile)

        def done(res, err):
            if err:
                self.fail(err, "Restore failed")
                return
            (s, safety), self.model = res
            self.refresh_garage()
            self.refresh_values()
            self.notify("ok", f"Backup restored. Previous file kept as {os.path.basename(safety)}.")
        self.run_task("Restoring backup", work, done)

    def quit(self):
        if self.model and self.model.dirty():
            if not self.confirm("Unsaved changes", "You have unsaved changes. Quit anyway?", ok="Quit", danger=True):
                return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--check" in sys.argv:
        a = [x for x in sys.argv[1:] if x != "--check"]
        run_check(a[0] if a else None)
    else:
        run_gui()
