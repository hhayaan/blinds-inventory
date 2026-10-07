# Developer handoff

Verified against the inventory skeleton and portable Windows release on October 7, 2026. This guide is for an engineer or AI model continuing the project without access to the original conversation.

## Read first

1. [README](../README.md): setup, launch, demonstration, backup and restore.
2. [Working plan](plan.md): confirmed user decisions and deferred work.
3. [Architecture](architecture.md): component boundaries and consistency rules.
4. This guide: source map, development workflow, and implementation limits.
5. [API reference](api.md): requests, responses, validation, and errors.
6. [Portable release](release.md): repeatable Windows builds, recipient instructions, and safe updates.

Windowstock is the working application name. The current deliverable is a Windows, one-PC browser application for whole-item inventory, available as source or a portable ZIP with bundled Python. Excel is explicitly excluded. Product filtering/sorting, a native/WebView2 desktop window, and shared hosting need a later product decision; Excel has no planned role.

## Source map

| File or directory | What to change here |
| --- | --- |
| [run.py](../run.py) | Loopback server startup, port selection, opening the default browser, and detecting an existing instance. |
| [Setup.ps1](../Setup.ps1), [Start Inventory.cmd](../Start%20Inventory.cmd) | Windows environment setup and staff launcher. |
| [Build Release.ps1](../Build%20Release.ps1), [packaging/windowstock.spec](../packaging/windowstock.spec) | Repeatable one-folder PyInstaller build and ZIP creation. Generated output stays under `release/`. |
| [packaging/smoke_release.py](../packaging/smoke_release.py) | Runs the actual staged executable with disposable inventory and validates assets, stock, backups, isolation, restart/retry, matching relaunch, and real Windows Ctrl+C before ZIP creation. |
| [packaging/START HERE.txt](../packaging/START%20HERE.txt), [packaging/release_manifest.py](../packaging/release_manifest.py) | Recipient instructions and generated build/runtime version information included in the release. |
| [inventory/main.py](../inventory/main.py) | FastAPI app factory, HTTP routes, local-access middleware, SVG barcodes, SQLite backup, and static page serving. |
| [inventory/schemas.py](../inventory/schemas.py) | Pydantic input models, allowed metadata, normalization, and field limits. Unknown fields are rejected. |
| [inventory/service.py](../inventory/service.py) | Inventory rules, transactions, revision checks, response serialization, and persisted scan retries. It currently raises FastAPI HTTP exceptions. |
| [inventory/database.py](../inventory/database.py) | SQLAlchemy tables, UTC timestamps, SQLite engine and connection settings. |
| [inventory/paths.py](../inventory/paths.py) | Source/bundle resource roots, database selection, and installation/database launcher identity. |
| [web/index.html](../web/index.html), [web/styles.css](../web/styles.css) | Main screens, dialogs, form constraints, and layout. |
| [web/app.js](../web/app.js) | API calls, rendering, forms, scan submission/recovery, polling, backup download, and opening labels. |
| [web/print.html](../web/print.html), [web/print.js](../web/print.js), [web/print.css](../web/print.css) | Separate printable label page, query validation, image readiness, physical dimensions, and print styling. |
| [tests/test_inventory_api.py](../tests/test_inventory_api.py) | Stock, edit, retry, concurrency, barcode and backup integration checks. |
| [tests/test_local_access.py](../tests/test_local_access.py), [tests/conftest.py](../tests/conftest.py) | Local HTTP restrictions and isolated app/database fixtures. |
| [tests/test_portable_runtime.py](../tests/test_portable_runtime.py) | Frozen resource paths, database isolation, same-instance relaunch, conflicting instances, and Ctrl+C handling. |
| `data/` | Working SQLite files. Preserve separately from source updates. Ignored by Git. |
| `.venv/`, `.validation/` | Machine-specific Python environment and disposable validation artifacts. Neither is application source or a required delivery file. |
| `release/` | Generated build work, packaged program folder, and distributable ZIP. Ignored by Git and replaceable by another build. Never keep the only copy of valued demonstration inventory here. |

The frontend uses plain HTML/CSS/JavaScript with relative, same-origin API URLs. There is no frontend framework, build step, npm requirement, or separate frontend development server. HTML IDs are used directly by `app.js`; rename them together. User-provided text is rendered with `textContent`; keep that boundary when adding fields.

## Setup, configuration, and iteration

From PowerShell in the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup.ps1 -IncludeTests
& .\.venv\Scripts\python.exe run.py
```

Setup expects Python 3.14 and detects the standard per-user `Python314` location; `-PythonPath` selects another installation. Runtime and test dependency versions are in [requirements.txt](../requirements.txt) and [requirements-dev.txt](../requirements-dev.txt). Activation of `.venv` is optional because commands call its interpreter directly. Recreate the environment on another PC.

| Setting | Current behavior |
| --- | --- |
| Host | Fixed `127.0.0.1`; no LAN mode. |
| Port | Development `8765`; packaged release `8767`; overridden with `--port`. |
| Browser | Opened after matching health is ready, or reopened for an existing matching instance; `--no-browser` suppresses both. |
| Database | Explicit `create_app(db_path)` takes precedence. Source mode next uses `INVENTORY_DB_PATH`, then project `data/inventory.sqlite3`. Frozen mode ignores the inherited environment variable and defaults to `data/inventory.sqlite3` beside the executable. |
| `--database` | Passes an explicit database path to the factory. Relative paths resolve from the process's current working directory; use an absolute path when that location is uncertain. |
| Existing process | Both source and frozen modes first reserve the selected loopback listener. On a bind conflict they query health and reuse only an instance matching the application installation and resolved selected database, including an explicit `--database`. Other applications, installations, databases, and legacy health responses without `launcher_id` remain port conflicts. |

`Start Inventory.cmd` starts the project's Python directly in a separate visible console and exits, rather than running Python inside an ongoing batch job. Staff stop the server with Ctrl+C in that original console; the expected interrupt is handled after Uvicorn's graceful shutdown without a traceback or **Terminate batch job** prompt. Closing the browser leaves the backend running. Relaunching the same copy reopens its interface and exits the new launcher without taking ownership of the original server. Source edits require stopping and restarting that server; relaunching alone does not reload it.

`inventory.paths.resolve_database_path()` applies the same database-selection rules before startup and before reuse, without opening the database. `launcher_identity()` hashes the OS-normalized resolved installation and database paths; `/api/health` returns this opaque `launcher_id`. The installation root is the source project root or the directory containing the packaged executable, independently of the bundle's resource location. This is an inventory-selection check, not authentication. Browser opening after startup also requires matching health. After a port conflict, the launcher allows a brief readiness interval for an instance that is still starting. Interactive startup errors remain visible until Enter; `--no-browser` checks never wait for that prompt.

`inventory.main:create_app` is an app factory, not a global `app` object. Creating an app opens/creates the selected database and missing tables immediately; shutdown disposes the engine. Importing the module alone does not open the working database. This is important for test isolation.

Backend changes require a server restart; automatic reload is not enabled. Frontend changes require a browser reload. API and page responses use `no-store`; static assets may require a hard reload during development. Do not run demonstrations against real inventory:

```powershell
& .\.venv\Scripts\python.exe run.py --no-browser --port 8766 --database .\.validation\demo.sqlite3
```

Open `http://127.0.0.1:8766` in Edge or Chrome. Stop that server with Ctrl+C before restoring or replacing its database.

## Portable release builds

Run `powershell -NoProfile -ExecutionPolicy Bypass -File ".\Build Release.ps1"` from the project root. It installs `requirements-build.txt`, runs tests, packages the saved spec, and checks a disposable copy of the staged executable before creating the ZIP. The generated folder and `Windowstock.zip` live under `release/`; intermediate output is removed after success. `-SkipInstall` and `-SkipTests` are optional shortcuts when those steps have already been completed for the current source; the executable smoke check still runs. The script does not launch the delivered copy or open a browser, and refuses to overwrite a generated application folder that contains `data/`. See [release.md](release.md) for build requirements, recorded verification, and the exact distribution and update workflow.

Frozen startup loads read-only web assets from PyInstaller's bundle resources and creates writable inventory beside the executable. Keep these locations separate: source edits must not affect an existing release, and its database must not use the development database or PyInstaller's bundled resource directory. The executable defaults to port 8767 so a source demo on 8765 can run separately.

The ZIP stores the **contents** of `release/Windowstock/` directly at its root: `Windowstock.exe`, `_internal/`, `START HERE.txt`, and `BUILD INFO.json`. There is no enclosing application folder in the archive. Keep this layout when changing packaging so recipients can launch directly from their chosen extraction folder. Track source, build scripts/configuration, dependency requirements, and docs in Git; generated `release/` artifacts remain ignored.

Do not include `data/`, live SQLite/WAL/SHM files, `.venv`, or QA databases in the distributable. Test an extracted copy outside the shipped folder, leaving the ZIP empty of inventory. Rebuilds replace generated files, while recipient updates must preserve their own database with a consistent backup. Database structure changes still need a tested explicit migration.

## Persistence and invariants

The tables are `products`, `stock_movements`, and `stock_operations`. SQLite uses WAL, foreign keys, and a five-second busy timeout. Every service mutation takes `BEGIN IMMEDIATE` before reading values used for its decision. Keep that transaction boundary: simultaneous last-unit sales must not both succeed.

Preserve these rules when extending the system:

- Product creation starts at quantity zero and revision one; its barcode is generated as `BL-{id:06d}` and remains stable. No hard-delete API exists.
- Receipt/return adds the requested positive whole-number count, sale subtracts it, and correction sets a nonnegative target count by recording the difference. Omitted/null scan quantity defaults to 1. Stock cannot become negative or exceed the quantity limit; an overlarge sale rejects the whole request with `Not enough in stock.`.
- Quantity, movement, revision, and successful operation retry record commit together. Do not directly edit the stored balance or delete history/retry records.
- Metadata edits and corrections require the revision originally displayed. Archive/restore also checks revision; only zero-stock products can be archived. Restore retains identity and history.
- Each deliberate stock submission gets a new UUID. A retry sends the same normalized payload and UUID. The backend returns the **original response snapshot**, with `replayed: true`; it is not the latest quantity. Refresh inventory afterward. Reusing an accepted UUID for different data is a conflict.

`price_cents` stores exact integer cents; the API uses nullable decimal strings and the UI displays CAD. Dimensions are optional floating-point display attributes, never stock units. Timestamps are UTC strings; the browser displays local time.

There is **no schema migration system**. `Base.metadata.create_all()` creates missing tables, but does not upgrade columns in existing tables. Before a schema change, back up existing data, define an explicit migration, and validate it on a copied database including history and operation replay. Deleting the working database is not an upgrade procedure.

## Frontend recovery behavior

The visible main interface refreshes products, history, and health every three seconds, as well as after operations and when becoming visible. The separate print page fetches its product once and does not poll. Editing dialogs retain their values and starting revision; refreshing the list does not update an open form's revision. A stale save requires reopening the form against current data.

Only one stock request is active per page. Its payload, including the selected quantity, and UUID are saved under `windowstock.pendingStock` in browser `sessionStorage` before sending. Network failures, unreadable successful responses, and server errors leave it pending. New stock submissions and count controls are locked until Retry confirms/rejects it or the user explicitly dismisses it after refreshing inventory. Retry and dismissal share the busy lock. Preserve both that lock and the saved UUID/payload when changing the UI.

Receive/sale count controls accept digit entry, including temporarily clearing the field while editing, but submission requires a positive whole number no larger than 1,000,000,000. +/− cannot pass the limits. A confirmed success resets the relevant selector to 1; rejection leaves its value. Manual stock adjustments remain a separate target-count correction with reason/revision, reachable from Edit product.

Grouped quantities use existing movement and operation columns, so this change needs no schema migration. Keep omitted/null quantity represented as null in normalized operation JSON: accepted requests from the earlier one-item version must still replay using their original payload after upgrading. Do not inject a default 1 into that stored contract. An explicitly supplied 1 remains distinct from null for retry-payload comparison.

This is recovery for an uncertain request, not an offline queue. Session storage is tied to a browser tab/origin and may disappear when the tab/session closes or if storage is unavailable. Product creation/metadata edits do not have persisted operation IDs; after an uncertain save, inspect inventory before resubmitting.

## Checks before handing off a change

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m pip check
```

Tests create fresh databases through `create_app(tmp_path)` and use a loopback TestClient URL. They do not require a running server or alter working inventory. The latest recorded result was **106 passing tests**, including grouped counts, backward-compatible retries, portable runtime isolation, same-instance relaunch, and normal Ctrl+C handling, on October 7, 2026; this is a dated baseline, not a guarantee for a later checkout. A dependency deprecation warning about TestClient/httpx was present without test failures.

Real source and packaged processes were also checked with disposable databases: relaunch reused the original server, Windows console Ctrl+C completed shutdown with exit code zero and no traceback, and the selected port was released. The source browser-open call was observed through a temporary test hook; the packaged reuse check ran headlessly. These process checks do not establish another-PC compatibility. See [release.md](release.md#verification-recorded-october-7-2026) for the packaged verification details.

For a UI change, use the isolated demo database and exercise the affected workflow. For changes to stock handling, include repeated intentional scans, grouped counts, invalid count entry, overlarge/zero-stock sale rejection, a stale form, and disconnect/reload/retry. For labels, check copy count, millimetre dimensions, loaded barcodes, and Print / Save as PDF in Edge or Chrome. The project has no automated browser test suite. API tests cannot establish physical scan readability or printer alignment.

When adding a product field, check the database model and migration, schema/metadata allowlist, service serialization, HTML form constraints, JavaScript form/rendering, relevant tests, and API documentation together. Add meaningful regression checks when changing stock, retries, revisions, or persistence.

## Limits and next decisions

The skeleton has no staff login, permissions, sale/order/payment records, metadata edit audit, offline queue, pagination, or schema migrations. History displays the product's **current name**, not its name when a movement occurred. Product lists use ID order and movement lists use newest ID first; user filtering/sorting remains deferred.

Loopback Host and browser Origin checks are local protections, not authentication. Changing the listener to `0.0.0.0` is insufficient for a shared deployment: middleware, client addressing, authentication, HTTPS, migrations, backups, and operating procedures need design together. Do not put SQLite on a network share for client PCs to edit.

Next product work is company review of sellable variants and fields, then filtering/sorting once the catalogue is understood. Physical scanner/printer validation and the final browser/desktop delivery choice remain open. Shared local/cloud hosting is a later phase. No changes to those decisions should be inferred from this handoff.
