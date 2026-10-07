# Portable Windows release

Windowstock is distributed as a ZIP containing a Windows executable and its bundled runtime and frontend. The program runs locally and opens its browser interface. The recipient does not install Python or the developer dependencies. A separate desktop UI or installer is not part of this release.

## Recipient instructions

1. Extract the **entire** `Windowstock.zip` to a writable local folder, for example under Documents. Do not run the executable from inside the ZIP or move it away from the bundled `_internal` folder.
2. Double-click **Windowstock.exe** directly inside the folder you extracted into.
3. The app opens the default browser at `http://127.0.0.1:8767`. If the browser does not open, visit that address manually after the console reports startup.
4. Keep the console window open while using the app. Stop the server with **Ctrl+C** in that window when finished. Closing the browser alone leaves the server running.

Requirements are 64-bit Windows and an existing browser, such as Edge or Chrome. The bundled application includes its Python runtime and required libraries. Normal inventory use requires no internet connection, database server, or development tools.

First launch creates `data\inventory.sqlite3` next to `Windowstock.exe`. The delivered ZIP contains no development inventory. Each extracted copy has its own data folder; changes in it do not affect the development project's database. Do not extract into a protected application folder such as Program Files: the portable app needs permission to create and update its data alongside the executable.

The workflows are described in [the project README](../README.md#demonstrate-the-workflow): add a product, copy its barcode, receive stock, record a sale, inspect history, and preview labels. Scanner and printer hardware are not needed for the demonstration; type or paste barcode values and use the browser's print/PDF dialog.

## Keep inventory when updating

The executable, bundled libraries, and frontend are a snapshot created by the build. Editing development source files does not change an existing release. Inventory data changes independently as someone uses that release.

For an update that preserves demonstration inventory:

1. Use **Download database backup** in the old application and save that backup somewhere separate from its application folder.
2. Stop the old application. Ensure no Windowstock process is still using its database.
3. Extract the new ZIP into a new folder. Keep the old application folder until the update has been verified.
4. Before starting the new copy, copy the saved backup to the new copy's `data\inventory.sqlite3`, creating the `data` folder if needed.
5. Start the new copy and verify products, quantities, and movement history.

Do not overwrite or delete the old `data` folder to update program files. A backup is a consistent copy; copying a live database file by itself may omit pending SQLite WAL changes. Schema changes require an explicit, tested migration before this update procedure is supported for those versions. The current skeleton has no automatic schema migrations.

## Build from source

From PowerShell in the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\Build Release.ps1"
```

The build requires the project's isolated `.venv` with 64-bit Python 3.14 on Windows. Run [Setup.ps1](../Setup.ps1) first if that environment does not exist. By default, the script installs the pinned [requirements-build.txt](../requirements-build.txt), runs the test suite, and uses the saved PyInstaller configuration in [packaging/windowstock.spec](../packaging/windowstock.spec). It then runs [packaging/smoke_release.py](../packaging/smoke_release.py) against a disposable copy of the actual staged executable before creating the ZIP. Dependency installation needs internet access unless the packages are already cached. The source environment is not copied into the deliverable.

Once the build dependencies are installed, `-SkipInstall` skips dependency installation. `-SkipTests` skips the source test suite when it has already been run for the same source state. The executable smoke test still runs. The normal command keeps both optional steps enabled.

All generated packaging output is under `release/`:

```text
release/
├── Windowstock/       portable application folder to distribute
│   ├── Windowstock.exe
│   ├── START HERE.txt  recipient launch and demonstration instructions
│   ├── BUILD INFO.json build time, target, and dependency versions
│   └── _internal/     bundled Python, libraries, and web assets
└── Windowstock.zip    ready-to-send archive of the contents of Windowstock/
```

The ZIP contains `Windowstock.exe`, `_internal/`, `START HERE.txt`, and `BUILD INFO.json` directly at its root, without an enclosing `Windowstock/` folder. Extracting it into a folder of your choice puts the executable directly in that folder.

Keep application source, build scripts/configuration, dependency requirements, and documentation in version control. The generated `release/` folder is excluded through `.gitignore`; share `Windowstock.zip` separately for demonstrations.

Intermediate output is staged under `release/work/` and removed after a successful build. Tests, packaging, bundle checks, the executable smoke check, and ZIP creation must succeed before the new folder and ZIP replace the prior output. The smoke check uses a separate temporary copy and database under that work directory; neither is included in the shipped folder or ZIP. A failed build can retain `release/work/` for diagnostics.

`release/` is ignored by version control. The build's temporary smoke check runs without opening a browser; the delivered application is not automatically launched. Rebuilding regenerates program output; it does not change an older ZIP that has already been sent to someone. The script refuses to rebuild if `release/Windowstock/data` exists, preserving inventory created by launching that generated copy. Back up and move a used application folder outside `release/` before rebuilding. Prefer a separately extracted copy for demonstrations that should persist between builds.

The build includes the application modules, bundled frontend, required dependencies, and recipient launch instructions. It excludes source development data, `.venv`, tests, and disposable validation files. The bundled frontend is loaded from PyInstaller's resource directory; writable inventory stays outside that directory beside the executable.

## Validate before sending

Run the project tests, then test a copy extracted from the newly generated ZIP. The packaged copy needs its own temporary database; do not test against development inventory or send the QA copy with test products.

Check that it starts from a directory other than its own, serves the main and print pages, generates a barcode, receives a grouped quantity, rejects an overlarge sale without changing stock, records a valid sale, downloads a backup, and retains data after a restart. Confirm the shipped archive contains no database, WAL, SHM, or QA files. Physical scanning, printer alignment, and another-PC compatibility require the actual equipment or destination PC; local validation does not replace those checks.

Ordinary source or frontend changes use the same build command again. Changes to dependencies, dynamically imported modules, bundled assets, launcher paths, or the database schema may also require updates to the saved configuration and additional validation.

### Verification recorded October 7, 2026

The source suite passed **89 tests**. The actual packaged executable also passed the automated smoke check from a path containing spaces while its working directory was elsewhere. Its `PATH` contained only Windows directories, with no Python installation on the path. An inherited `INVENTORY_DB_PATH` pointed at a sentinel file that remained untouched; the app instead created its own empty database beside the executable.

The packaged app served the bundled main page, JavaScript, CSS, and print assets; created a product; received 3 units; sold 1; and rejected a sale of 3 with **Not enough in stock.** Quantity remained 2 and history contained only the two accepted movements. SVG barcode generation and a downloaded SQLite backup were verified. After a forced stop and restart, quantity remained 2; retrying the original receipt UUID also left quantity and history unchanged. Smoke-test copies and inventory were removed, leaving the distributable empty.

The latest flat ZIP passed CRC and file-content checks: all 187 shipped files matched the generated application folder. The executable and supporting files were directly at the archive root, with no enclosing application folder or bundled inventory database. The source tests were unchanged by the archive-layout update; the packaged executable smoke check was run again during that rebuild.

These checks ran on the development PC using the bundled runtime. A second Windows PC and physical scanner/printer have not yet been tested.

## Troubleshooting

- **The browser cannot connect:** keep the console open and inspect its startup error. If port 8767 is occupied, stop the earlier copy or run `.\Windowstock.exe --port 8768` from PowerShell in its folder and use the corresponding address.
- **The app cannot write its database:** extract to a writable local folder and retain its `data` folder. Running from a ZIP or protected directory is unsupported.
- **An incomplete copy will not start:** extract the entire ZIP again; the executable depends on its bundled files.
- **Windows blocks the executable:** this demonstration build is unsigned. Follow the recipient company's normal software approval process; packaging does not provide code signing or an installer.

For the source layout and database contracts, see [development.md](development.md), [architecture.md](architecture.md), and [api.md](api.md).
