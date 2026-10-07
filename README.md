# Windowstock

A local inventory application for blinds, curtains, and window accessories. This is the first one-PC skeleton: products, stock receipts and sales, corrections and returns, movement history, and printable Code 128 labels. Stock is counted in whole items, and identical units share a barcode.

The interface runs in a browser on the same PC as the Python backend and SQLite database. It starts with an empty inventory. A portable Windows release bundles Python and the frontend, so demonstration recipients do not need to install Python. Product filtering/sorting and a separate desktop window remain deferred. Excel is excluded.

## Documentation map

| Document | Purpose |
| --- | --- |
| This README | Running the application, basic workflow, and backup/restore. |
| [Working plan](docs/plan.md) | Confirmed requirements, company decisions, and deferred scope. |
| [Architecture](docs/architecture.md) | Component boundaries, storage, and stock consistency. |
| [Developer handoff](docs/development.md) | Start here when continuing development: source map, configuration, checks, and known limits. |
| [API reference](docs/api.md) | Exact endpoint, input, response, revision, and retry contracts. |
| [Portable release](docs/release.md) | Building, distributing, running, and updating the Windows ZIP. |

## Run the portable demonstration

1. Extract the entire `Windowstock.zip` to a writable local folder, such as a folder under Documents. Keep the executable and its bundled files together; do not run it from inside the ZIP.
2. Double-click **Windowstock.exe** directly inside the folder you extracted into. There is no extra `Windowstock` subfolder in the ZIP. It starts the local server and opens the default browser at <http://127.0.0.1:8767>.
3. Keep its console window open while using the application. Press **Ctrl+C** in that window, or close it, when finished. Closing the browser alone does not stop the server.

The release requires 64-bit Windows and an existing browser; Python, a separate SQL server, and an internet connection are not required for normal operation. Its first launch creates an empty `data\inventory.sqlite3` beside the executable. This database is separate from the development project's `data` folder and persists when the release restarts. See [portable release instructions](docs/release.md) for updates and troubleshooting.

## Start on this PC

The project environment has been created with Python 3.14.8. Double-click **Start Inventory.cmd** in this folder. The launcher starts the server and opens:

<http://127.0.0.1:8765>

Keep the server window open while using the application. Closing the browser does not stop the server. Press **Ctrl+C** in the server window to stop it. Inventory is saved automatically in SQLite and survives restarts.

From PowerShell, the equivalent command is:

```powershell
Set-Location C:\Dev\blinds-inventory
& .\.venv\Scripts\python.exe run.py
```

If that port is occupied by another application, choose a different one:

```powershell
& .\.venv\Scripts\python.exe run.py --port 8766
```

## Set up a development copy on another Windows PC

The portable release above is the distribution route for demonstrations. These instructions are for someone who needs to edit or run the source code.

1. Install normal 64-bit Python 3.14 and copy this project folder. The `.venv` folder is machine-specific; recreate it on the destination PC rather than copying it.
2. Open PowerShell in the project folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1
```

This process-only execution-policy option lets the setup script run without changing the PC's saved policy. Setup detects the usual per-user Python 3.14 installation and creates `.venv`. For another Python location, supply it explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -PythonPath "C:\path\to\python.exe"
```

3. Double-click **Start Inventory.cmd**.

Initial dependency installation requires internet access. Normal inventory operations use this PC's local files and database. No separate SQL server or frontend build tool is required.

## Build a portable release

From PowerShell in the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\Build Release.ps1"
```

The script installs build dependencies in `.venv`, runs the tests, packages the app, and checks the executable using disposable inventory. It creates `release\Windowstock\` and `release\Windowstock.zip`; the ZIP contains the executable and supporting files directly at its root. Send that ZIP for demonstrations. Generated release files are ignored by Git; source, build configuration, and documentation belong in version control.

Source changes take effect in the release only after rebuilding. The build refuses to replace `release\Windowstock\` if it contains a `data` folder, protecting inventory from a used copy. Back up and move that copy elsewhere before rebuilding. See [the release guide](docs/release.md) for build options, updates, and verification.

## Demonstrate the workflow

1. Add a product, including its name and any useful details. Stock starts at zero and the application generates a stable barcode.
2. Copy its readable barcode into the **Receive stock** input. Submit three separate times at quantity 1, or set quantity to 3 and submit once.
3. Use **Record sale** to submit the same barcode once. Quantity becomes two.
4. Edit product details through the inventory interface. Stock changes use receive/sale/return operations or a correction with a reason, accessible through Edit product's stock adjustment action.
5. Open **Stock history** to inspect the recorded movements.
6. Open the product's labels, select copies and label dimensions, and open the print sheet. In Edge or Chrome, click **Print / Save as PDF**. Choose **Save as PDF** in the browser dialog to review the result without a printer; use 100% scale for dimension checks.

Receive and sale buttons have a quantity selector: use +/− or replace the number by typing. Only positive whole-number counts are accepted, with a default of 1. A successful submission resets the selector to 1 for the next scan; a rejected request keeps the entered count. Sales above available stock show **Not enough in stock.** and change neither inventory nor history. Negative receipts are not allowed; use a controlled stock correction through Edit product to reduce a physical count.

Each intentional submission is one recorded movement for its selected number of units. At the default count, repeating a scan receives or sells one more unit each time. Product details and barcodes remain when stock reaches zero. Archiving is available only for products at zero stock; their history remains.

Until hardware is available, typing or pasting a barcode and pressing Enter simulates scanning. Later, a scanner configured as a keyboard can use this input. Printer alignment and actual barcode readability still need testing with the company's equipment. Label printing does not increase stock.

Automatic capture without barcode-field focus and repeated-scan quantity accumulation are deferred until a scanner is available. Their intended behavior is recorded in [the working plan](docs/plan.md#deferred-scanner-behavior); the current simulation submits each entry immediately.

The interface shows whether requests were accepted or failed. If a stock request loses its response, retry the pending operation rather than submitting it again as a new scan; the backend recognizes the same operation and avoids counting it twice.

## Data and backups

Development database: `data\inventory.sqlite3`, under the project folder. Portable release database: `data\inventory.sqlite3`, under the extracted folder containing `Windowstock.exe`. These are independent locations. Preserve the relevant `data` folder when replacing source or application files. Back up real inventory before moving or updating the application.

Use the application's **Download database backup** action to download a consistent SQLite backup. Store it outside the project folder as well, preferably on another drive or managed backup location.

To restore a backup:

1. Stop the server with Ctrl+C and ensure no other inventory process is running.
2. Preserve a copy of the existing `data` folder.
3. Replace `data\inventory.sqlite3` with the downloaded backup. Remove old `inventory.sqlite3-wal` and `inventory.sqlite3-shm` files if they remain, only while the server is stopped.
4. Start the application and check inventory and movement history.

Do not open the SQLite file from multiple PCs over a network drive. Shared-server operation is a separate deployment phase. The current app listens only on this PC's loopback address and has no staff login system.

To run a separate demonstration with its own empty database:

```powershell
& .\.venv\Scripts\python.exe run.py --port 8766 --database .\data\demo.sqlite3
```

## Development checks

Install test dependencies into the project environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -IncludeTests
& .\.venv\Scripts\python.exe -m pytest
```

Tests use isolated temporary databases. Follow [docs/development.md](docs/development.md) for the source map, configuration, safe schema changes, UI checks, and remaining limitations. Keep the relevant docs updated when changing behavior; implementation details must describe the current code, while deferred requirements stay clearly marked in the working plan.
