# Moto Repair Log

A one-page form where motorcycle owners log which part failed on their bike and at what mileage (optionally with up to 3 photos). It tests whether riders will contribute data for a future motorcycle reliability / cost-of-ownership site.

The owner (Marc) is not a developer. Keep explanations short and plain, never use em dashes in anything you write for him, and confirm before anything that deletes data.

## Pieces and where they live

| Piece | Where | Notes |
|---|---|---|
| Page | `site/index.html` | Single file: HTML, CSS and JS. Hosted on Cloudflare Pages. |
| Live URL | https://motorcycle-reliability-index.pages.dev | Cloudflare account: popocdc@gmail.com. Pages project: `motorcycle-reliability-index` (Direct Upload). |
| Backend | `apps-script/Code.gs`, `apps-script/appsscript.json` | Google Apps Script bound to the data sheet, deployed as a web app. Google account: rob.popolizio@gmail.com. |
| Script ID | `1wd0PDMsHrvgDr2njGYtcmDvEe06_8VHN_JGianTvnonbe-levfU1J6Mt` | In `.clasp.json`. |
| Web app deployment ID | `AKfycbxY7IrSAkGdcPoNhGjTAbz3x5QSuM5GAw6Z9hfBC0dooyTDQohpkaa3mvKn8R-JxLy3cw` | Its `/exec` URL is `API_URL` in `site/index.html`. Always update THIS deployment; never create a new one (that changes the URL and breaks the page). |
| Data | Google Sheet "Moto Repair Log data", tab `entries` | https://docs.google.com/spreadsheets/d/1rzqlHlFLhuxnxP9Vzozvz20O-ackyPVtG4g1aUC_1kE |
| Photos | Drive folder "Moto Repair Log photos" | Private to the owner. Links in the sheet's `photos` column. |

## How it works

- The page talks to the Apps Script web app with `fetch`: GET `?action=log|stats|models`, POST JSON `{action: "add"|"delete", ...}` sent as text/plain (keeps it a simple CORS request).
- Riders get a random "garage code" in localStorage; they only ever see their own entries plus per-model totals. Emails and photo links are never returned by the API.
- Photos are resized in the browser to 1600px JPEG (this also strips EXIF/GPS) and sent as base64; the script saves them with the Advanced Drive service.
- Script permissions are limited in `appsscript.json` to `spreadsheets.currentonly` and `drive.file`. Adding a Google service that needs a new scope means the owner must re-approve in the Apps Script editor (Run > `setup`).
- `?src=...` on the page URL is stored with each entry so the sheet shows which post a rider came from.
- With `API_URL` set to `''` the page runs in demo mode (localStorage only), useful for local testing.

## Deploy

```bash
npm run deploy:page     # publish site/ to Cloudflare Pages (production)
npm run deploy:script   # push apps-script/ and update the existing web app deployment
```

After a deploy, test on the live URL with `?src=test`: add a bike named `TEST-DELETE-ME`, log one failure, check the row in the sheet, then delete the entry from the page (that also trashes its photos). Leave the sheet clean.

Front-end-only changes need only `deploy:page`. If a change touches what the page sends or receives, deploy the script first, then the page.

## NHTSA motorcycle data

`python3 tools/nhtsa_motorcycles.py` builds `data/nhtsa/motorcycles.sqlite` (tables `complaints`, `complaint_components`, `recalls`, `models`, `meta`, plus `complaints_search` full-text index) and CSV copies (`complaints.csv`, `recalls.csv`, `model_summary.csv`) from NHTSA's complaint and recall flat files. Motorcycles are picked by decoding each complaint's 11-character VIN with vPIC (body class `Motorcycle - ...` or dirt bike; ATVs/side-by-sides excluded), falling back to brand/model name when there is no VIN. `model_family` is the clean model name (VIN model, e.g. GL1800 -> Gold Wing; FZ-07/09 merged into MT-07/09); `model_filed` is what the owner typed. Downloads and VIN lookups are cached in `data/nhtsa/raw/` (rebuild takes ~30s; delete it to refresh). On python.org Python, run with `SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())')` if downloads fail with a certificate error. `data/` is not committed (large). Personal fields (VIN, city, dealer, operator name) are never copied. NHTSA complaints are US-only, owner-submitted and safety-related: label them as such on any page and keep them separate from the owner log counts.

## One-time setup on a new computer

1. Install Node.js 20+ if `node -v` fails (`brew install node`).
2. `npx wrangler login` (browser opens; owner approves with the Cloudflare account above).
3. Owner turns on "Google Apps Script API" at https://script.google.com/home/usersettings.
4. `npx @google/clasp login` (browser opens; owner signs in with rob.popolizio@gmail.com and approves).
5. Check: `npx @google/clasp list-deployments` should show the deployment ID above.
6. Do not run `clasp pull` over local changes without asking: the repo is the source of truth.
