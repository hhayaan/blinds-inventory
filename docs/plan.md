# Inventory system: working plan

Status: work in progress; initial one-PC skeleton implemented. Updated: October 7, 2026.

This document records the company's intended workflow, decisions confirmed so far, recommendations, and questions still open. The initial one-PC skeleton is implemented; launch instructions are in [../README.md](../README.md). Recommendations about later delivery and product-specific features remain provisional.

## 1. Purpose and confirmed scope

Build a simple inventory management system for a company selling blinds, curtains, and window accessories. The first skeleton should let the company demonstrate stock receipt, sales, barcode labels, and inventory display before finalizing product categories, filtering, and sorting.

Confirmed decisions:

- The first version runs on one Windows PC.
- A browser frontend is acceptable for the skeleton. The final frontend may become a desktop application or an Edge/WebView2-based application; that choice remains open.
- Keep the local server in a visible console while the application is in use. Closing the browser leaves it running; staff stop it with Ctrl+C in the original server console. Launching the same copy again reopens its existing interface. Automatic shutdown when the browser closes is not planned for this version.
- Stock is measured in individual items using whole-number quantities.
- Multiple units of the same sellable item share the same barcode.
- Receive and sale submissions default to one unit. Staff can scan each unit separately or scan one barcode and choose a positive whole-number count using +/− or direct typing.
- The selected count resets to 1 after a confirmed successful submission. Invalid or rejected requests keep it for correction.
- There is currently no barcode scanner or barcode printer. Manual scan simulation and printable label previews are required.
- Filtering and sorting are deferred until the company supplies a clearer product catalogue.
- The frontend is the staff interface for viewing and editing products and stock. Excel is excluded from the project; no integration, dependencies, or future accommodation are planned.
- The initial one-PC application is authorized for implementation using the installed Python 3.14 runtime. Dependency setup and validation use the project's isolated environment.
- Demonstration delivery uses a portable Windows ZIP containing `Windowstock.exe`, Python, dependencies, and the frontend. Recipients extract the entire ZIP into a folder of their choice and launch the executable directly there without installing Python. The archive has no enclosing `Windowstock/` folder. It opens the browser interface; a separate desktop window remains undecided.
- The portable release starts with empty inventory and stores its own database beside the executable. It does not share or include the development database. Program changes require an explicit rebuild; inventory changes remain local to each extracted copy.

## 2. Inventory and barcode workflow

### Product creation

1. Enter the details of a new sellable item through the frontend.
2. Assign a unique, stable product identifier and barcode value.
3. Generate a barcode label for preview or printing.
4. Start the product at zero stock; product creation and label printing do not receive inventory automatically.

The barcode identifies a sellable product variant, such as a particular blind model, colour, and size. Identical units share that code. Different variants should have different codes. The company must still define what makes two products the same item; the skeleton does not infer duplicates from names or dimensions.

Implemented internal barcode format: Code 128 containing an identifier such as `BL-000001`. Product descriptions, dimensions, prices, and stock are looked up from the database using that identifier. Barcode identity stays stable when those attributes change. The [python-barcode documentation](https://python-barcode.readthedocs.io/en/stable/) lists Code 128 support.

### Receiving and selling

- Receive mode: a submitted barcode adds the selected positive whole-number count and records one receipt movement.
- Sale mode: a submitted barcode removes the selected positive whole-number count and records one sale movement.
- The selected mode must be clear on screen so staff know which operation they are performing.
- Unknown barcodes produce an error. Staff can create a product through Add product or copy a known barcode from Inventory; unknown scans do not create incomplete stock records.
- Selling more than available stock is rejected with **Not enough in stock.** No partial sale or history change is recorded, and quantities cannot become negative.
- A sale reduces quantity rather than deleting the product. A zero-stock product remains available for history and restocking.
- Every deliberate repeat submission of the same barcode counts its selected number of units. With quantity 1, staff can scan every unit separately. Retries retain the original quantity and operation ID and must not count twice.
- Receipt/sale quantity controls accept only positive whole-number counts. Negative receipt quantities cannot be used to remove stock; manual reductions use the controlled correction reachable from Edit product.
- Returns and corrections use explicit stock movements rather than erasing previous sales. Corrections require a reason; return reasons are optional in the API and are not collected by the initial receive screen.

### Hardware-free skeleton

The implemented barcode field accepts typing or pasting followed by Enter or a submit button. Receipt and sale simulations use the same backend stock operations that future hardware input will use.

USB scanners configured as keyboard input can later feed this field; the exact scanner configuration will be checked when hardware is available. See [Zebra's HID keyboard interface documentation](https://docs.zebra.com/us/en/scanners/general/sm72-ig/getting-started/host-interfaces.html).

Labels include the barcode, readable identifier, and product name. The skeleton supports preview, copy count, configurable label dimensions, and the browser's print/PDF dialog. Actual scan readability, printer alignment, printer drivers, and label stock cannot be validated without the equipment.

### Deferred scanner behavior

The following requirements are recorded for implementation and testing when a barcode scanner is available. They are not implemented in the current manual scan simulation.

1. **Capture scans without barcode-field focus.** When Receive stock or Record sale is the active page, a completed scanner barcode should populate the barcode field even when the cursor is elsewhere on that page. Ordinary typing in the quantity selector and other editable fields must continue to work normally. This applies while the application has keyboard input; it does not require capturing scans while another application is active.
2. **Accumulate repeated scans into the selected quantity.** The intended workflow is to scan an item once to select its barcode with quantity 1, then scan the same barcode again to increase the quantity to 2, 3, and so on. Staff then click Receive or Record sale to submit that count as one stock movement. Scanning alone should not commit this accumulated entry. Existing positive-whole-number validation, the **Not enough in stock.** warning, and reset to 1 after a successful submission still apply.

With the actual scanner, determine how to recognize a completed scan without redirecting every keyboard stroke. Check its available prefix/suffix settings or another reliable method of distinguishing scanner input from manual typing. A scanner's Enter suffix should complete a scan for accumulation instead of triggering the current form's immediate submission. Validate this with the quantity field focused, buttons focused, and other editable forms or dialogs open.

Before implementing accumulation, confirm how scanning a different barcode should handle an unsubmitted entry and how repeated scans should interact with a manually chosen quantity. Do not silently discard a pending entry. Test intentional repeated scans, scan boundaries, and submission/reset behavior using the equipment.

## 3. Frontend: browser, webview, or native desktop

| Option | What staff would use | Tradeoff and current position |
| --- | --- | --- |
| Browser frontend | A local page in Edge or Chrome | Implemented skeleton interface; simple local browser delivery. |
| Edge installed web app / PWA | A separate window with an app icon and taskbar presence | A relatively simple route to an app-style window. It still depends on the web service; installation does not bundle or start our Python backend. |
| WebView2 desktop wrapper | A Windows application window displaying our HTML interface | Proposed preferred desktop direction if the company wants its own executable and launcher. The launcher can manage the local backend, app lifecycle, and printing integration. |
| Native desktop UI | Windows or Qt controls, for example using PySide6 or .NET | A valid alternative if native controls or deeper device integration become important. It would require implementing a different UI while keeping the same backend API. |

Edge supports installed web applications with Windows integration; see [Microsoft's PWA documentation](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps-chromium/ux). WebView2 is an embedded web runtime for native applications; production distribution must ensure that the [WebView2 Runtime is installed](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

The web interface is implemented against the Python backend and is delivered in a portable browser-based release for demonstrations. A WebView2 wrapper can be evaluated later if the company wants its own desktop window. A Python wrapper such as pywebview is a candidate, not a finalized dependency. Its [Windows installation requirements](https://pywebview.flowrl.com/guide/installation.html) include WebView2 and Python/.NET integration dependencies. A wrapper's packaging, printing, and compatibility need a small validation exercise before adopting it.

The backend should stay independent of the chosen window technology. A wrapper should use the same API as the browser rather than introducing a second set of inventory rules.

## 4. Frontend viewing and editing

Staff manage inventory through the application's inventory table and product forms. The frontend submits changes to the Python backend, which validates and commits them to SQL before reporting success.

Requirements:

- Display the current product details and quantity from the database.
- Support creating products and editing allowed product fields through the application.
- Keep stable product IDs and generated barcode values protected from ordinary editing, with validation enforced by the backend.
- Use receive and sale operations for normal stock changes. Provide a controlled correction operation for physical counts or mistakes, recording its reason and quantity change.
- Show clear saving, saved, rejected, and unavailable-backend states.
- Refresh the inventory display after successful edits or scans using the committed database values.
- Reject invalid quantities and stale corrections instead of overwriting newer stock changes.
- Keep stock history when a product sells out or is archived.
- Show errors when the backend is unavailable and prevent new stock submissions while a scan's result needs confirmation. Queued offline editing is outside the first scope.

Product edits use an explicit Save action. A simulated scan submits one stock movement and updates the displayed quantity. Bulk editing can be considered if a demonstrated staff workflow warrants it; it is not required to begin.

## 5. Initial data and screens

Implemented initial product fields, subject to company review:

| Field | Notes |
| --- | --- |
| Product ID and barcode | Stable identifiers; barcode stored as text. |
| Name and description | Human-readable identification. |
| Category | Blinds, curtains, accessories, or categories provided later. |
| Brand/model, colour, material | Optional variant details. |
| Width and height | Optional, with explicit measurement units. |
| Quantity on hand | Whole items, never negative. |
| Storage location | Optional for the one-PC skeleton. |
| Price | Optional, currently displayed as CAD; currency choice needs company confirmation. Accounting and payment processing are outside this prototype. |

Initial screens: inventory table; create/edit product; receive stock; record sale; stock history and correction; barcode label preview/printing.

Basic validation and a documented backup/restore process are required before the company relies on this for real inventory. Final category-specific fields, filtering, sorting, and user roles remain future work.

## 6. Developer setup and installation requirements

Python 3.14.8 and pip were verified at `C:\Users\t2xpl\AppData\Local\Programs\Python\Python314`. Project dependencies are installed in `.venv`. This section also records requirements for a fresh developer setup.

| Component | Install now? |
| --- | --- |
| Python | Yes: stable 64-bit Python 3.14, currently 3.14.8. Use the normal Windows installer, or the Python install manager with a 3.14 runtime. With the normal installer, enable Add Python to PATH and retain pip. [Official Windows downloads](https://www.python.org/downloads/windows/). Verify dependency compatibility before pinning project versions. |
| SQLite | No separate installation. It is the initial local SQL database, and Python includes its SQLite interface. [Python SQLite documentation](https://docs.python.org/3/library/sqlite3.html). |
| Edge or Chrome | Use an existing browser for the initial frontend. |
| VS Code | Recommended editor, optional if another editor is preferred. [Windows User Setup](https://code.visualstudio.com/docs/setup/windows). |
| Git | Optional development tool for version control; not an application runtime requirement. |
| Python project libraries | Installed in `.venv`: FastAPI, Uvicorn, SQLAlchemy, and python-barcode. Pinned requirements are in `requirements.txt`; test dependencies are in `requirements-dev.txt`. |
| Release build tooling | PyInstaller is used by the repeatable Windows build script. It is a developer build dependency; recipients receive its output, not the tool. |
| Desktop wrapper | Defer: if selected later, pywebview, WebView2 Runtime, and its Windows dependencies. |

Python and an existing browser are enough for the development setup. Project dependencies stay in a local `.venv`; they do not need global installation. The initial plain HTML/CSS/JavaScript interface does not require a Node.js build toolchain, Docker, or a separate SQL server. See `README.md` for setup and launching.

The demonstration release uses [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html) to bundle Python, the application, and web assets into one portable folder. `Build Release.ps1` recreates that folder and its ZIP under `release/`; source edits do not affect an existing release until it is rebuilt. See [release.md](release.md) for developer and recipient instructions. An installer and final desktop-window choice remain open.

SQLite runs on the same PC as the backend. No separate SQL server is required for this version.

## 7. Implementation status and open decisions

The one-PC core, browser interface, scan simulation with selectable counts, stock history, backup download, and configurable label sheets are implemented. The project environment is installed, and the main workflows have been checked in a browser. A portable Windows browser release is now part of the deliverable. Physical hardware checks and the final desktop-window choice remain pending; current build verification is recorded in [release.md](release.md).

Next steps:

1. Demonstrate the implemented workflow to the company and confirm what defines a sellable variant, its required fields, and price currency.
2. Refine product fields and implement filtering/sorting once the catalogue and staff needs are understood.
3. When a scanner is available, implement and test the two deferred scanner behaviors above. Validate barcode readability and label printing with the actual equipment.
4. Demonstrate the portable browser release on the recipient's PC. Decide later whether the final interface should use the browser, an Edge app, or WebView2.

Still open: final desktop technology; required product attributes and editable fields; price currency; printer model and label dimensions; backup location and retention; scanner configuration and handling of a different barcode or manually chosen quantity during accumulation.

Baseline demonstration: create a product, generate its label, receive it three times, sell it once, and see two units remaining. Edit an allowed product field through the frontend, save it, and confirm the change remains after reloading. Correct a physical count through the stock-correction workflow and verify its recorded movement and reason.

See [architecture.md](architecture.md) for the implemented component boundaries, consistency rules, and remaining validation milestones.

For continuing implementation, read [development.md](development.md) and [api.md](api.md). They describe the actual source, contracts, and technical limits independently of the original conversation.
