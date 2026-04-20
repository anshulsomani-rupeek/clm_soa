# FED CLM SOA Generator

A Flask-based Statement of Account (SOA) generator for Federal Bank loans that queries Redshift data and serves PDF-downloadable SOA documents.

## Project Structure

```
fed_clm_soa/
├── app.py                  # Flask application with routes and calculation logic
├── requirements.txt        # Python dependencies
├── Dockerfile              # Docker container configuration
├── templates/
│   ├── index.html          # Input form for entering LMS ID
│   └── soa.html            # SOA template (adapted from fed_template.html)
├── static/                 # Static assets (logo images)
│   ├── Rupeek Capital Logo (1).png
│   └── Federal Logo_removed_page-0001-Photoroom.png
└── main.html / fed_template.html  # Original reference files (untouched)
```

## Setup & Deployment

### 1. Local Development (Non-Docker)

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Set environment variables:**
```bash
export REDSHIFT_HOST=<redshift-endpoint>
export REDSHIFT_PORT=5439
export REDSHIFT_DB=<database-name>
export REDSHIFT_USER=<username>
export REDSHIFT_PASSWORD=<password>
```

**Place logo images:**
Copy the two PNG logo files into the `static/` directory:
- `Rupeek Capital Logo (1).png`
- `Federal Logo_removed_page-0001-Photoroom.png`

**Run the Flask app:**
```bash
python app.py
```

The app will be available at `http://localhost:5000`.

### 2. Docker Deployment

**Build the Docker image:**
```bash
docker build -t fed-clm-soa .
```

**Run the container with Redshift credentials:**
```bash
docker run -p 5000:5000 \
  -e REDSHIFT_HOST=<redshift-endpoint> \
  -e REDSHIFT_PORT=5439 \
  -e REDSHIFT_DB=<database-name> \
  -e REDSHIFT_USER=<username> \
  -e REDSHIFT_PASSWORD=<password> \
  -v /path/to/static/logos:/app/static \
  fed-clm-soa
```

The app will be available at `http://localhost:5000`.

## Usage

1. **Open the form:** Navigate to `http://localhost:5000`
2. **Enter LMS ID:** Input the loan account number in the form
3. **Generate SOA:** Click "Generate SOA" button
4. **Download PDF:** Once the SOA page loads, click "Download as PDF" button in the bottom-right corner

## How It Works

### Routes

- **`GET /`** → Returns the input form (`index.html`)
- **`POST /generate`** → Accepts LMS ID, queries Redshift, generates SOA, returns `soa.html`

### Database Queries

The app queries three Redshift tables for a given LMS ID:

1. **`dw.account_svc_customer_rupeek_view`** — MIS records, day-change records (interest tracking)
2. **`dw.account_svc_charges`** — Charges grouped by type with sum of value+tax
3. **`tech.mis_fed_outstanding_till_date`** — Customer name, branch name, account number

### SOA Calculation Logic

The logic in `app.py` (ported from `main.html`'s `buildDashboard()`) performs:

1. **Sort data** by date, then event type (MIS → DAY_CHANGE → REPAYMENT)
2. **Extract MIS record** for loan details: principal, interest rate, slab rate, disbursement date
3. **Calculate interest entries per month**:
   - Non-closing months: Post interest on the 1st of the next month
   - Closing month: Post interest on the last repayment date
4. **Build transaction rows** with running balance:
   - Loan Disbursement (DR)
   - Interest Accrual per month (DR)
   - Rebate (CR)
   - Repayment (CR)
   - Charges appended at end (DR)
5. **Calculate summary** totals: interest, repayment, rebate, closing balance

### Template Context

The `soa.html` template receives:

```python
{
  "customer_name": str,
  "account_no": str,
  "branch_name": str,
  "opening_date": "DD-MM-YYYY",
  "closing_date": "DD-MM-YYYY",
  "sol_id": str,
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "narration": str,
      "withdrawal": float,
      "deposit": float,
      "balance": float,
      "cr_dr": "DR" | "CR"
    },
    ...
  ],
  "total_withdrawals": float,
  "total_deposits": float,
  "lms_id": str
}
```

## PDF Download

The SOA page uses **html2pdf.js** (CDN) for client-side PDF generation. No server-side PDF library is required. Users click the "Download as PDF" button to download a PDF file with the filename `{lms_id}_Federal_SOA.pdf`.

## Notes

- **Logo Images:** User must manually copy the PNG logo files into `static/`. The paths in `soa.html` reference `/static/Rupeek Capital Logo (1).png` and `/static/Federal Logo_removed_page-0001-Photoroom.png`.
- **Sol ID:** Not returned by any Redshift query. The field in the template is left blank.
- **Date Format:**
  - Database queries use `YYYY-MM-DD`
  - HTML template displays dates in `DD-MM-YYYY`
  - PDF filename uses `YYYY-MM-DD`
- **Original Files:** `main.html` and `fed_template.html` remain untouched and serve as reference/test data sources.

## Troubleshooting

**"Connection refused" when querying Redshift:**
- Verify the Redshift endpoint is accessible from your network
- Check that `REDSHIFT_HOST`, `REDSHIFT_PORT`, `REDSHIFT_DB`, `REDSHIFT_USER`, and `REDSHIFT_PASSWORD` are set correctly

**Missing logo images:**
- Ensure `static/Rupeek Capital Logo (1).png` and `static/Federal Logo_removed_page-0001-Photoroom.png` exist and are accessible

**SOA table is empty:**
- Verify the LMS ID exists in the Redshift database
- Check the queries in `app.py` match your table schemas

**PDF download not working:**
- Ensure the browser allows popups/downloads
- Check browser console for errors from html2pdf.js
- Verify the page loaded successfully before attempting to download

## Dependencies

- **Flask 3.0.3** — Web framework
- **redshift-connector 2.1.4** — Redshift database driver
- **html2pdf.js** — Client-side PDF generation (CDN)

See `requirements.txt` for exact versions.
