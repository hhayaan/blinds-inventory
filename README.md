# Windowstock

A local inventory application for blinds, curtains, and window accessories. This is the first one-PC skeleton: products, stock receipts and sales, corrections and returns, movement history, and printable Code 128 labels. Stock is counted in whole items, and identical units share a barcode.

The interface runs in a browser on the same PC as the Python backend and SQLite database. It starts with an empty inventory. Product filtering/sorting, multi-PC hosting, and desktop packaging are deferred. Excel is excluded.

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

## Set up on another Windows PC

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

## Demonstrate the workflow

1. Add a product, including its name and any useful details. Stock starts at zero and the application generates a stable barcode.
2. Copy its readable barcode into the **Receive stock** input. Submit it three separate times to receive three units.
3. Use **Record sale** to submit the same barcode once. Quantity becomes two.
4. Edit product details through the inventory interface. Stock changes use receive/sale/return operations or a correction with a reason.
5. Open **Stock history** to inspect the recorded movements.
6. Open the product's labels, select copies and label dimensions, and use the print dialog. Choose **Save as PDF** to review the result without a printer.

Every intentional repeated scan is a separate unit. Failed sales at zero stock do not change inventory. Product details and barcodes remain when stock reaches zero. Archiving is available only for products at zero stock; their history remains.

Until hardware is available, typing or pasting a barcode and pressing Enter simulates scanning. Later, a scanner configured as a keyboard can use this input. Printer alignment and actual barcode readability still need testing with the company's equipment. Label printing does not increase stock.

The interface shows whether requests were accepted or failed. If a stock request loses its response, retry the pending operation rather than submitting it again as a new scan; the backend recognizes the same operation and avoids counting it twice.

## Data and backups

Default database: `data\inventory.sqlite3`, under the project folder. Do not delete this folder when replacing application source files. Back up real inventory before moving or updating the application.

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

Tests use isolated temporary databases. The working requirements and architectural notes are in [docs/plan.md](docs/plan.md) and [docs/architecture.md](docs/architecture.md).
