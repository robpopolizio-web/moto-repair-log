# Moto Repair Log

A simple page where motorcycle owners log what broke on their bike, at what mileage, and what it cost to fix. Entries go to a private Google Sheet through a Google Apps Script web app. The page shows each rider their own log plus totals for their model.

- `index.html`: the page (hosted with GitHub Pages)
- `apps-script/Code.gs`: a copy of the backend that runs in Google Apps Script, bound to the data sheet

To change the backend, edit it in Apps Script and redeploy: Deploy > Manage deployments > edit > Version: New version > Deploy. The web app URL stays the same.
