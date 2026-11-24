# Rynzler's Garage & Casino Editor  (v1.1.1)

A Test Drive Unlimited 2 / Project Paradise 2 save utility: browse your garages by house and slot, apply Stage 4 upgrades, edit mileage, money, Casino chips and coupons, unlock Casino VIP, and (optionally) try the "Strange Flag" repair.

## Quick start (Windows)

1. **Install Python 3.8 or newer** from <https://www.python.org/downloads/> (tick **"Add python.exe to PATH"**). The installer's *tcl/tk* option provides the window toolkit and is on by default. **Nothing else needs installing** – there are no extra packages.
2. **Extract the whole ZIP** and keep the folder together.
3. **Close Test Drive Unlimited 2**, then copy your entire profile folder somewhere safe as your own backup.
4. **Double-click `Launch_Rynzlers_Garage_and_Casino_Editor.bat`.**
5. Press **Open save…** and choose your save file:  
   `…\savegame\<YourProfile>\PLAYERSAVE\DATA`  
   (normally inside *Documents\Test Drive Unlimited 2\savegame*). The profile name is taken from the folder name.
6. Make your edits, then press **Save changes**. A verified backup is made first. Start the game and check.

If the launcher can't find Python or tkinter it tells you so. You can also run `py Rynzlers_Garage_and_Casino_Editor.py` from a Command Prompt in this folder.

## What it does

- **Garage Editor** – vehicles grouped by house (Ibiza and Hawaii) with numbered slots and upgrade badges; Stage 4 for one vehicle, a whole garage or every owned vehicle; odometer editing; change a slot's vehicle by archetype ID (cars you already own only).
- **Casino & Player** – player money, Casino chips, Casino coupons, Casino VIP unlock (original behaviour), Casino cosmetics and reward-car flags presets.
- **Casino DLC / TDU Life Repair** – *optional*. Changes `Driver.MustClearOnlineDatas` from 4 to 0 and nothing else. It is only offered when the value is exactly 4, makes a backup first and verifies the result. It helped fix missing Casino access / Casino DLC / TDU Life problems for the author, but it is **not guaranteed** to fix every player's problem.
- **Safety** – every save to disk checks the data, makes a verified backup (`DATA.backup-<date>-<time>` next to your save), writes atomically, re-reads the file and rolls back automatically if anything is wrong. **More ▾ → Restore a backup…** puts a backup back (your current file is kept as `DATA.before-restore-…`). **More ▾ → Verify save file** re-checks the file on disk. **More ▾ → Save as new file…** writes a copy instead of overwriting.

It cannot add cars, remove garage slots or edit text.

## Updating the vehicle / house lists

`cars_database.json`, `houses_database.json` and `vehicle_classes.json` are read from this folder when you open a save. Replace or extend them (same file names, same structure) – no program change is needed. A vehicle only needs `"id"` and `"name"` to be recognised. The **Information** screen shows which data files were loaded.

`garage_list.csv` is a reference list of the author's 206 vehicles (house, position, slot, ID, upgrades, odometer). Open it from **More ▾ → Open garage_list.csv**.

## Known limits

- Four vehicles could not be matched to a specific house: two Lexus LFA (Mililani Haven of Peace) and the Bugatti Divo / EB110SS (Kaukonahua Home). They show as an "Unrecognised house" rather than a guess.
- Vehicle classes are no longer shown in the Garage Editor. `vehicle_classes.json` (100 of the author's 206 vehicles classed) stays in the folder for possible future use; the program still loads it but does not display it.
- Use at your own risk. Always keep your own backup of the profile folder.

## Files

| File | Purpose |
|---|---|
| `Rynzlers_Garage_and_Casino_Editor.py` | The editor |
| `tdu2_tool.py` | Save decrypt / encrypt / checksum engine (also a command-line tool) |
| `cars_database.json` | Vehicle names by archetype ID |
| `houses_database.json` | House names, islands and sizes |
| `vehicle_classes.json` | Vehicle class data (A1, B4, …) – kept for future use, not displayed |
| `garage_list.csv` | Reference list of the author's 206 vehicles |
| `Launch_Rynzlers_Garage_and_Casino_Editor.bat` | Windows launcher |
| `DEVELOPMENT_REPORT.md` | What changed, what was tested, what is still uncertain |

Command-line check without opening a window: `py Rynzlers_Garage_and_Casino_Editor.py --check "<path to a COPY of DATA>"`
