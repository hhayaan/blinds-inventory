# API reference

Current skeleton contract, verified against source on October 7, 2026. See [development.md](development.md) for implementation and test guidance. Default base URL is `http://127.0.0.1:8765` in development or `http://127.0.0.1:8767` in the portable release. Both use the same API.

FastAPI exposes local interactive request documentation at `/docs` and `/redoc`, and the generated schema at `/openapi.json`. Requests have Pydantic models; output dictionaries do not currently have declared response models, so their shapes are recorded below.

## Requests and routes

Writes require `Content-Type: application/json`. Unknown body fields are rejected. Browser writes must come from the same scheme, hostname, and port when an `Origin` header is supplied; local CLI calls may omit Origin. Accepted Host names are `127.0.0.1`, `localhost`, and `::1`, but the launcher listens on IPv4 `127.0.0.1`. No authentication or cross-origin deployment is implemented.

| Method and path | Request / result |
| --- | --- |
| `GET /api/health` | `{app: "Windowstock", status: "ok", version: "0.1.0", storage: "sqlite", launcher_id: "<opaque identifier>"}` after a database read. |
| `GET /api/products` | Product array, active only by default; `?include_archived=true` includes archived products. ID ascending. |
| `POST /api/products` | Product metadata; returns the created Product with HTTP 201, generated barcode, quantity 0, revision 1. |
| `GET /api/products/{id}` | One Product, including archived products. |
| `PATCH /api/products/{id}` | Flat metadata fields plus required `revision`; returns updated Product. At least one metadata field is required. |
| `POST /api/products/{id}/archive` | `{revision, archived}`; returns Product. `archived: false` restores. |
| `POST /api/stock` | Stock request described below; returns `{product, movement, replayed}`. |
| `GET /api/movements` | Movement array, newest ID first; optional `?product_id=1` limits to an existing product. Includes archived products' history. |
| `GET /api/products/{id}/barcode.svg` | Code 128 SVG for the stored barcode; no stock changes. |
| `GET /api/backup` | Downloadable, consistent SQLite backup including committed WAL data and retry records. |

There is no pagination, catalogue filtering/sorting API, or delete endpoint. `/` serves the main interface and `/static/` serves its assets. `/print?product_id=1&copies=3&width=70&height=40` serves the label page; its JavaScript validates product ID, copies 1–100, width 40–200 mm, and height 25–150 mm, then fetches the canonical Product and SVG. Print controls wait for images to load. Label generation never receives stock.

`launcher_id` is an additive health field used by the source and portable launchers to identify the existing installation and selected inventory database. It is a deterministic SHA-256 identifier derived from their resolved, OS-normalized paths; it does not expose those paths or grant authentication. Treat it as opaque. A launcher reopens an occupied port only when `app`, `status`, and `launcher_id` all match its expected instance. Another installation, another database, or an older health response without this field is not reused. Stop and restart older running instances before using the updated launcher.

## Product fields

Create requires only `name`. PATCH may supply any subset of metadata plus `revision`; omitted fields stay unchanged. Text is trimmed. Optional text `null` becomes an empty string. `width`, `height`, and `price` may be cleared with `null`; `name` and `dimension_unit` cannot be null.

| Metadata field | Contract |
| --- | --- |
| `name` | Nonempty string, maximum 160 characters. |
| `description` | String, maximum 2,000; default empty. |
| `category`, `brand`, `model`, `color`, `material` | Strings, maximum 100 each; default empty. |
| `location` | String, maximum 160; default empty. |
| `width`, `height` | Optional finite positive numbers, maximum 1,000,000; default null. |
| `dimension_unit` | `in`, `cm`, or `mm`; default `in`. |
| `price` | Optional decimal **string**, 0–99999999.99 with at most two decimal places; empty string becomes null. Returned with two places. CAD display is currently a UI convention. |

Product responses include all metadata plus `id` (integer), `barcode` (string), `quantity` (integer), `revision` (integer), `archived` (boolean), and `created_at`/`updated_at` (UTC strings). These extra fields cannot be set through product create/PATCH; PATCH uses `revision` only as its concurrency check. Archive uses its separate endpoint. Metadata edits are allowed for archived products. An accepted metadata PATCH increments revision even if values are unchanged; archive requests for the already-current state do not increment it after revision validation.

Example creation body:

```json
{"name":"White roller blind","color":"White","width":36,"height":72,"dimension_unit":"in","price":"89.95"}
```

Example edit body, using the revision from the Product fetched before editing:

```json
{"revision":4,"location":"Aisle B, Shelf 2"}
```

## Stock operations and retries

Each deliberate scan must generate a fresh UUID; preserve it and the entire payload for transport retries. These example identifiers are illustrative, not identifiers to reuse for new scans.

```json
{"barcode":"BL-000001","kind":"receipt","quantity":5,"request_id":"e85a14fa-c151-47dd-a32e-a62b6bcaa988"}
```

`receipt` and `return` add the requested `quantity`; `sale` removes it. For these operations, quantity must be a positive whole integer from 1 to 1,000,000,000. Omitted or null quantity defaults to 1 for earlier clients. They do not require a revision check. `reason` is optional, up to 500 characters. Archived products reject stock operations. A sale larger than current stock returns HTTP 409 with `{"detail":"Not enough in stock."}` and records no partial change.

A correction requires a **target count**, current `revision`, and nonblank `reason`:

```json
{"barcode":"BL-000001","kind":"correction","quantity":2,"revision":4,"reason":"Physical count","request_id":"e220f077-a1c1-4200-aad4-af832232ec1e"}
```

Quantities and revisions are strict JSON integers: strings, fractions, and booleans are rejected. Revisions must be at least one; `archived` is a strict boolean. Barcode input is a nonempty trimmed string of at most 80 characters and must match a stored barcode.

An accepted stock operation updates the quantity and revision, creates one Movement for the whole selected delta, and persists its retry result in one transaction. Correction target quantities allow zero, unlike receipt/sale/return counts. The API permits a correction whose target equals current stock, recording delta zero; the UI asks for a changed count.

Response members:

- `product`: the Product snapshot at that operation.
- `movement`: `id`, `product_id`, `kind`, signed `delta`, `quantity_after`, nullable `reason`, `request_id`, UTC `created_at`, `product_name`, and `barcode`.
- `replayed`: false initially; true when the same accepted UUID and normalized payload are retried.

An exact retry returns the original snapshots even if later stock or metadata changed, or the product was subsequently archived. Read current inventory separately. Reusing an accepted UUID with different normalized payload, including a changed quantity, returns 409. Retain the original payload on retry; previously accepted requests with omitted/null quantity still replay, and must not have `quantity: 1` added to them. Rejected operations leave no successful retry record and change neither balance nor history. Movement listing joins the product's current name; it is not a historical name snapshot.

## Errors

Errors use `{"detail": ...}`. `detail` may be a string, a validation-error array, or a stale-edit object containing `message` and `current_product`. Do not assume one shape.

| Status | Meaning / caller action |
| --- | --- |
| 403 | Nonlocal/malformed Host or foreign write Origin. Check deployment/URL, not inventory data. |
| 404 | Product or barcode does not exist. Select/create the correct product. |
| 409 | Stale revision, no stock, archived product, quantity limit, or reused operation UUID conflict. Stale forms must reopen against current data. |
| 415 | Write was not submitted as JSON. |
| 422 | Invalid/missing/extra request fields. Correct the input. |
| 503 | Database busy/unavailable, backup failure, or missing frontend file. Stock requests retain their UUID for safe retry. |

Treat transport failures and server errors during stock writes as uncertain: the change may already have committed. Retry the original UUID/payload rather than turning it into a new scan. Successful API responses are marked `Cache-Control: no-store`; the middleware also sets `X-Content-Type-Options: nosniff` on responses it passes through.
