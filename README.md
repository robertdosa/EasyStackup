# EasyStackup

Desktop app for **1D mechanical tolerance stack-up** analysis.

Draw a closed dimension loop on a canvas, assign tolerances (symmetric, bilateral, or ISO fits), then evaluate **worst-case (WC)** and **RSS** clearance or interference. Export a PDF report and loop diagrams (PNG/SVG).

**Version:** 0.1.0  
**License:** [MIT](LICENSE)  
**Repository:** [github.com/robertdosa/EasyStackup](https://github.com/robertdosa/EasyStackup)

## Screenshots

![Main workspace](docs/screenshot-main.png)

![Stack-up results](docs/screenshot-results.png)

---

## Features

- Interactive **loop diagram** (draw-to-scale dimension arrows)
- **Close loop / clearance** dimension with sign convention: `+` gap, `−` interference
- Tolerance types:
  - Symmetric ±
  - Bilateral upper/lower
  - ISO 286 hole/shaft fits (subset of common designations)
- Stack results: **mean clearance**, **WC min/max**, **RSS min/max**
- **Tolerance contribution** bars (share of total band width)
- Display units: **mm** or **inch** (values stored as mm)
- Save / load projects (`.eysp` JSON)
- Export:
  - Multi-page **PDF report**
  - Loop diagram **PNG** / **SVG**
- Unsaved-change prompts and dirty-state title (`*`)

---

## Requirements

- **Python 3.10+** (developed with 3.14)
- **tkinter** (usually included with Python on Windows; on some Linux installs you may need `python3-tk`)
- Windows recommended for v0.1 (CustomTkinter desktop UI)
- Dependencies listed in [`requirements.txt`](requirements.txt):
  - `customtkinter`
  - `Pillow`
  - `reportlab`

---

## Install & run

```bash
# Clone
git clone https://github.com/robertdosa/EasyStackup.git
cd EasyStackup

# Virtual environment (Windows)
python -m venv venv
venv\Scripts\activate

# Dependencies
python -m pip install -r requirements.txt

# Launch (from the project root so core/ and ui/ import correctly)
python main.py
```

On macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

UI is primarily tested on Windows.

---

## Quick start

1. **New project** from the main menu.
2. Click near the starting face and **drag** to place the first dimension; enter nominal and tolerance.
3. Continue the chain from the active face.
4. Click **Close Loop / Add Clearance** when the stack is complete.
5. Click **Calculate** to show WC / RSS results and contributions.
6. **File → Save** (`.eysp`) and/or **Export → Export PDF report**.

---

## Project layout

```text
EasyStackup/
├── main.py              # Entry point (menu shell + workspace)
├── requirements.txt
├── LICENSE
├── README.md
├── .gitignore
├── assets/              # App icon (PNG + ICO)
├── docs/                # README screenshots
├── core/                # Model, calculator, ISO tables, I/O, PDF
└── ui/                  # CustomTkinter dialogs and canvas app
```

---

## Project files (`.eysp`)

Projects are JSON. Dimensions are stored in **millimetres**; the display unit is a preference only. The file also stores layout metadata such as the diagram origin face.

---

## Building a Windows executable (optional)

A standalone `.exe` is **not** required to use the source. When you want a Release build, from the **project root** (with your venv active):

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onedir --name EasyStackup --icon assets/app_icon.ico --add-data "assets;assets" main.py
```

- Output is under `dist/EasyStackup/`. Zip that folder for GitHub Releases.
- `--add-data "assets;assets"` is the **Windows** form (`source;dest`). On Linux/macOS use `assets:assets`.
- Windows may SmartScreen-block unsigned binaries — expected for hobby/unsigned builds.

---

## Known limitations (v0.1)

- **1D** stack-ups only (single closed loop)
- Clearance (CL) is a special closing dimension (not fully edited like L-dimensions)
- ISO fit table is a **practical subset**, not the full standard
- Desktop GUI; packaging/signing and multi-OS builds are optional follow-ups

---

## Disclaimer

EasyStackup is a calculation and documentation aid. Results depend on how the loop and tolerances are defined. **The engineer remains responsible** for interpretation, design decisions, and any use in production or safety-related work.

---

## License

This project is released under the **MIT License**. See [LICENSE](LICENSE) for the full text.

---

## Development notes

Developed with AI assistance. Design decisions, engineering logic, and final review remain the responsibility of the author.
