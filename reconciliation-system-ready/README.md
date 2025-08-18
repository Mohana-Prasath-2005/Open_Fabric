# Transaction Reconciliation System (Flask + SQLite + React)

End‑to‑end, ready‑to‑run solution for the take‑home exercise.

## 1) Prerequisites
- Python 3.10+
- Node.js 18+ and npm
- (Windows) Git Bash or PowerShell recommended

## 2) Backend – Setup & Run
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# Initialize the SQLite DB with sample data
python -c "from app import init_db; init_db()"

# Run the API
python app.py
# API is now at http://localhost:5000
```

### API Endpoints
- `POST /init-db` – reset DB
- `POST /reconcile` – upload CSV (`file`) **or** JSON `{ csv_text: "..." }`
- `GET /transactions?status=PARTIAL` – list with issue_flag + net_settled
- `GET /transactions/<id>` – transaction + settlement history
- `GET /dashboard/summary` – KPIs for the dashboard

## 3) Frontend – Setup & Run
```bash
cd frontend
npm install
npm run dev
# UI at http://localhost:5173  (proxies /api/* to Flask)
```

## 4) How to Demo Quickly
1. Start the backend (step 2).
2. Start the frontend (step 3).
3. In the UI, click **Reconcile CSV** and upload `backend/settlement_report.csv`.
4. The dashboard updates: counts, pie chart, table with status badges & issue dots.
5. Click a **Txn ID** to see its details + settlements.

## 5) Reconciliation Logic (implemented)
- Primary match: `lifecycle_id`.
- Fallback: `(account_id, merchant_name, transaction_date)`.
- Inserts into `settlement_history` (skips duplicates).
- Recomputes per-transaction:
  - `total_settled_amount = sum(DEBIT) - sum(CREDIT)`
  - `last_settlement_date = latest settlement_date`
  - `settlement_status` rules:
    - `PENDING`: none
    - `FULLY_SETTLED`: net == amount
    - `PARTIAL`: net < amount and **no credits**
    - `REFUNDED`: net < amount and **has credits**
    - `OVER_SETTLED`: net > amount
- Issue detection:
  - **CRITICAL**: net > amount, or no settlement after 7 days
  - **WARNING**: net < amount and > 0 with no credits
- Dashboard metrics:
  - totals, breakdown, critical/warning counts
  - total outstanding = Σ max(0, amount - net)
  - avg days to settle, settlement rate

## 6) Testing
```bash
cd backend
pytest -q
```

## 7) Notes & Assumptions
- Currency must match exactly (e.g., `USD`). Mismatches are rejected.
- Failed/Declined transactions are not eligible for settlements.
- CSV validation enforces positive amounts and valid types.
- Duplicate `settlement_id` is ignored.
- You can reset the DB anytime via `POST /init-db`.

## 8) Folder Structure
```
RECONCILIATION-SYSTEM
│
├── backend
│   ├── __pycache__
│   ├── .pytest_cache
│   ├── .venv
│   ├── tests
│   │   └── __pycache__
│   │       └── test_api.cpython-313-pytest-8.4.1.pyc
│   ├── venv
│   ├── app.py
│   ├── db_init.sql
│   ├── reconciliation.db
│   ├── requirements.txt
│   ├── settlement_report_given.csv
│   ├── settlement_report_test.csv
│   └── test_api.py
│
├── frontend
│   ├── node_modules
│   ├── src
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── SummaryPage.jsx
│   │   ├── TransactionDetailPage.jsx
│   │   ├── TransactionsPage.jsx
│   │   └── WelcomePage.jsx
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   └── vite.config.js

```