import os
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from dateutil import parser as dateparser
from datetime import datetime, date, timedelta
import csv
import io

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "reconciliation.db"))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def to_dict(row):
    return dict(row) if row else None

def compute_status_and_issue(net_settled, txn_amount, had_credit, has_settlement, txn_date, last_settlement_date):
    # Determine settlement_status
    if not has_settlement or net_settled == 0:
        status = "PENDING"
    elif net_settled > txn_amount:
        status = "OVER_SETTLED"
    elif abs(net_settled - txn_amount) < 1e-9:
        status = "FULLY_SETTLED"
    elif had_credit and net_settled < txn_amount:
        status = "REFUNDED"
    elif net_settled < txn_amount:
        status = "PARTIAL"
    else:
        status = "PENDING"

    # Issue flags
    critical = False
    warning = False
    if net_settled > txn_amount:
        critical = True
    # No settlement after 7 days
    if (not has_settlement) and (date.today() - txn_date).days > 7:
        critical = True
    # Warning: under-settled with no credits
    if (net_settled < txn_amount) and (net_settled > 0) and (not had_credit):
        warning = True

    issue_flag = "NONE"
    if critical:
        issue_flag = "CRITICAL"
    elif warning:
        issue_flag = "WARNING"

    return status, issue_flag

def recalc_transaction(conn, transaction_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
    txn = cur.fetchone()
    if not txn:
        return

    cur.execute("SELECT * FROM settlement_history WHERE transaction_id = ?", (transaction_id,))
    rows = cur.fetchall()

    debit = sum(float(r["settlement_amount"]) for r in rows if r["settlement_type"] == "DEBIT")
    credit = sum(float(r["settlement_amount"]) for r in rows if r["settlement_type"] == "CREDIT")
    net = debit - credit
    last_date = None
    had_credit = any(r["settlement_type"] == "CREDIT" for r in rows)
    for r in rows:
        sd = datetime.fromisoformat(r["settlement_date"]).date()
        if last_date is None or sd > last_date:
            last_date = sd

    txn_amount = float(txn["transaction_amount"])
    txn_date = datetime.fromisoformat(txn["transaction_date"]).date()
    has_settlement = len(rows) > 0
    status, issue_flag = compute_status_and_issue(net, txn_amount, had_credit, has_settlement, txn_date, last_date)

    cur.execute("""
        UPDATE transactions
        SET settlement_status = ?, total_settled_amount = ?, last_settlement_date = ?
        WHERE transaction_id = ?
    """, (status, round(net,2), last_date.isoformat() if last_date else None, transaction_id))
    conn.commit()
    return status, issue_flag, round(net,2), last_date.isoformat() if last_date else None

def init_db():
    conn = get_conn()
    conn.executescript(open(os.path.join(os.path.dirname(__file__), "db_init.sql")).read())
    conn.commit()
    conn.close()

app = Flask(__name__)
CORS(app)

@app.route("/init-db", methods=["POST"])
def initdb_endpoint():
    init_db()
    return jsonify({"ok": True})

@app.route("/reconcile", methods=["POST"])
def reconcile():
    conn = get_conn()
    cur = conn.cursor()

    # Read CSV content
    if "file" in request.files:
        file = request.files["file"]
        content = file.read().decode("utf-8")
    else:
        data = request.get_json(silent=True) or {}
        content = data.get("csv_text", "")
    if not content:
        return jsonify({"error": "No CSV provided"}), 400

    reader = csv.DictReader(io.StringIO(content))
    required_cols = {"settlement_id","settlement_date","settlement_amount","settlement_type","currency","transaction_date","merchant_name","account_id"}
    if not required_cols.issubset(set(reader.fieldnames or [])):
        return jsonify({"error": f"CSV missing required columns: {sorted(list(required_cols - set(reader.fieldnames or [])))}"}), 400

    processed = 0
    inserted = 0
    matched = 0
    unmatched_rows = []
    already_exist = 0
    errors = []
    updated_transactions = set()  # Track which transactions we've updated

    try:
        cur.execute("DELETE FROM settlement_history")
        for row in reader:
            processed += 1
            try:
                sid = row["settlement_id"].strip()
                if not sid:
                    errors.append({"row": row, "error": "missing settlement_id"})
                    continue

                # Check for duplicates
                cur.execute("SELECT 1 FROM settlement_history WHERE settlement_id = ?", (sid,))
                if cur.fetchone():
                    already_exist += 1
                    continue

                lifecycle_id = (row.get("lifecycle_id") or "").strip() or None
                acc = row["account_id"].strip()
                merch = row["merchant_name"].strip()
                
                # Better date parsing with error handling
                try:
                    txn_date = dateparser.parse(row["transaction_date"]).date()
                    s_date = dateparser.parse(row["settlement_date"]).date()
                except (ValueError, AttributeError) as e:
                    errors.append({"row": row, "error": f"Invalid date format: {str(e)}"})
                    continue

                try:
                    amount = float(row["settlement_amount"])
                except (ValueError, TypeError):
                    errors.append({"row": row, "error": "Invalid settlement_amount"})
                    continue

                s_type = row["settlement_type"].strip().upper()
                currency = row["currency"].strip().upper()

                if amount <= 0:
                    errors.append({"row": row, "error": "non-positive settlement_amount"})
                    continue
                if s_type not in ("DEBIT","CREDIT"):
                    errors.append({"row": row, "error": "settlement_type must be DEBIT or CREDIT"})
                    continue

                # Primary match by lifecycle_id
                txn = None
                if lifecycle_id:
                    cur.execute("SELECT * FROM transactions WHERE lifecycle_id = ?", (lifecycle_id,))
                    txn = cur.fetchone()

                # Fallback match - more flexible matching
                if not txn:
                    # Try exact match first
                    cur.execute("""
                    SELECT * FROM transactions
                    WHERE account_id = ? AND merchant_name = ? AND transaction_date = ?
                    """, (acc, merch, txn_date.isoformat()))
                    txn = cur.fetchone()
                    
                    # If no exact match, try date range (±1 day for processing delays)
                    if not txn:
                        date_before = (txn_date - timedelta(days=1)).isoformat()
                        date_after = (txn_date + timedelta(days=1)).isoformat()
                        cur.execute("""
                        SELECT * FROM transactions
                        WHERE account_id = ? AND merchant_name = ? 
                        AND transaction_date BETWEEN ? AND ?
                        ORDER BY ABS(julianday(transaction_date) - julianday(?))
                        LIMIT 1
                        """, (acc, merch, date_before, date_after, txn_date.isoformat()))
                        txn = cur.fetchone()

                if not txn:
                    unmatched_rows.append(row)
                    continue

                # Skip failed/declined/not applicable
                if txn["status"] in ("FAILED","DECLINED") or txn["settlement_status"] == "NOT_APPLICABLE":
                    unmatched_rows.append({**row, "reason": "transaction not eligible"})
                    continue

                # Currency check (handle None values)
                txn_currency = (txn["currency"] or "").upper()
                if txn_currency and txn_currency != currency:
                    errors.append({"row": row, "error": f"currency mismatch: txn={txn['currency']} csv={currency}"})
                    continue

                # Insert settlement with proper error handling
                try:
                    cur.execute("""
                        INSERT INTO settlement_history 
                        (settlement_id, transaction_id, lifecycle_id, settlement_date, 
                         settlement_amount, settlement_type, currency)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (sid, txn["transaction_id"], txn["lifecycle_id"], 
                          s_date.isoformat(), round(amount,2), s_type, currency))
                    
                    inserted += 1
                    matched += 1
                    updated_transactions.add(txn["transaction_id"])
                    
                except Exception as db_error:
                    errors.append({"row": row, "error": f"Database insert failed: {str(db_error)}"})
                    continue

            except Exception as e:
                errors.append({"row": row, "error": f"Row processing failed: {str(e)}"})
                continue

        # Commit settlements first
        conn.commit()
        
        # Now recalculate all affected transactions
        recalc_errors = []
        for transaction_id in updated_transactions:
            try:
                recalc_transaction(conn, transaction_id)
            except Exception as e:
                recalc_errors.append(f"Failed to recalculate transaction {transaction_id}: {str(e)}")
        
        # Final commit after recalculations
        conn.commit()

        # Build summary and metrics (same as before but with better error handling)
        try:
            # Totals
            cur.execute("SELECT COUNT(*) as c FROM transactions")
            total_txns = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) as c FROM settlement_history")
            total_settlements = cur.fetchone()["c"]

            # Breakdown by status
            cur.execute("""
              SELECT settlement_status, COUNT(*) as c FROM transactions
              GROUP BY settlement_status
            """)
            breakdown = {r["settlement_status"]: r["c"] for r in cur.fetchall()}

            # Issue counts with better performance
            cur.execute("""
                SELECT 
                    SUM(CASE WHEN issue_flag = 'CRITICAL' THEN 1 ELSE 0 END) as critical,
                    SUM(CASE WHEN issue_flag = 'WARNING' THEN 1 ELSE 0 END) as warning,
                    SUM(CASE WHEN outstanding_amount > 0 THEN outstanding_amount ELSE 0 END) as outstanding_total,
                    AVG(CASE WHEN days_to_settle > 0 THEN days_to_settle ELSE NULL END) as avg_days,
                    SUM(CASE WHEN settlement_status = 'SETTLED' THEN 1 ELSE 0 END) as settled_count
                FROM transactions
            """)
            metrics = cur.fetchone()
            
            critical = metrics["critical"] or 0
            warning = metrics["warning"] or 0
            outstanding_total = metrics["outstanding_total"] or 0.0
            avg_days_to_settle = metrics["avg_days"] or 0.0
            settled_count = metrics["settled_count"] or 0
            settlement_rate = (settled_count / total_txns) if total_txns else 0.0

            dashboard = {
                "total_transactions": total_txns,
                "total_settlements": total_settlements,
                "breakdown_by_status": breakdown,
                "critical_issues": critical,
                "warning_issues": warning,
                "total_outstanding_amount": round(outstanding_total,2),
                "avg_days_to_settle": round(avg_days_to_settle,2),
                "settlement_rate": round(settlement_rate,2)
            }
            
        except Exception as e:
            dashboard = {"error": f"Dashboard calculation failed: {str(e)}"}

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Transaction failed: {str(e)}"}), 500
    
    finally:
        conn.close()

    result = {
        "processed_rows": processed,
        "inserted_settlements": inserted,
        "matched_rows": matched,
        "already_existing": already_exist,
        "unmatched_rows": unmatched_rows,
        "errors": errors,
        "updated_transactions": len(updated_transactions),
        "dashboard": dashboard
    }
    
    if recalc_errors:
        result["recalculation_errors"] = recalc_errors
    
    return jsonify(result)

@app.route("/transactions", methods=["GET"])
def list_transactions():
    status_filter = request.args.get("status")
    conn = get_conn()
    query = "SELECT * FROM transactions"
    args = []
    if status_filter:
        query += " WHERE settlement_status = ?"
        args.append(status_filter)

    rows = conn.execute(query, args).fetchall()
    result = []
    for t in rows:
        txn_id = t["transaction_id"]
        # compute issue flag
        srows = conn.execute("SELECT settlement_type, settlement_amount, settlement_date FROM settlement_history WHERE transaction_id = ?", (txn_id,)).fetchall()
        debit = sum(float(r["settlement_amount"]) for r in srows if r["settlement_type"] == "DEBIT")
        credit = sum(float(r["settlement_amount"]) for r in srows if r["settlement_type"] == "CREDIT")
        net = debit - credit
        had_credit = any(r["settlement_type"] == "CREDIT" for r in srows)
        txn_date = datetime.fromisoformat(t["transaction_date"]).date()
        last_date = t["last_settlement_date"]
        last_date = datetime.fromisoformat(last_date).date() if last_date else None
        status, issue_flag = compute_status_and_issue(net, float(t["transaction_amount"]), had_credit, len(srows)>0, txn_date, last_date)

        d = dict(t)
        d["issue_flag"] = issue_flag
        d["net_settled"] = round(net,2)
        result.append(d)

    conn.close()
    return jsonify(result)

@app.route("/transactions/<txn_id>", methods=["GET"])
def transaction_detail(txn_id):
    conn = get_conn()
    t = conn.execute("SELECT * FROM transactions WHERE transaction_id = ?", (txn_id,)).fetchone()
    if not t:
        return jsonify({"error": "not found"}), 404
    srows = conn.execute("SELECT * FROM settlement_history WHERE transaction_id = ? ORDER BY settlement_date ASC", (txn_id,)).fetchall()
    conn.close()
    return jsonify({
        "transaction": dict(t),
        "settlements": [dict(r) for r in srows]
    })

@app.route("/dashboard/summary", methods=["GET"])
def dashboard_summary():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM transactions")
    total_txns = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM settlement_history")
    total_settlements = cur.fetchone()["c"]

    cur.execute("""
      SELECT settlement_status, COUNT(*) as c FROM transactions
      GROUP BY settlement_status
    """)
    breakdown = {r["settlement_status"]: r["c"] for r in cur.fetchall()}

    cur.execute("SELECT * FROM transactions")
    txns = cur.fetchall()
    critical = 0
    warning = 0
    outstanding_total = 0.0
    days_to_settle = []
    settled_count = 0
    for t in txns:
        debit_credit = conn.execute("SELECT settlement_type, settlement_amount, settlement_date FROM settlement_history WHERE transaction_id = ?", (t["transaction_id"],)).fetchall()
        debit = sum(float(r["settlement_amount"]) for r in debit_credit if r["settlement_type"] == "DEBIT")
        credit = sum(float(r["settlement_amount"]) for r in debit_credit if r["settlement_type"] == "CREDIT")
        net = debit - credit
        had_credit = any(r["settlement_type"] == "CREDIT" for r in debit_credit)
        txn_amount = float(t["transaction_amount"])
        txn_date = datetime.fromisoformat(t["transaction_date"]).date()
        last_date = t["last_settlement_date"]
        last_date = datetime.fromisoformat(last_date).date() if last_date else None
        status, issue_flag = compute_status_and_issue(net, txn_amount, had_credit, len(debit_credit)>0, txn_date, last_date)

        if issue_flag == "CRITICAL":
            critical += 1
        elif issue_flag == "WARNING":
            warning += 1

        outstanding_total += max(0.0, txn_amount - net)
        if last_date:
            days_to_settle.append((last_date - txn_date).days)
            settled_count += 1

    avg_days_to_settle = (sum(days_to_settle) / len(days_to_settle)) if days_to_settle else 0.0
    settlement_rate = (settled_count / total_txns) if total_txns else 0.0

    conn.close()
    return jsonify({
        "total_transactions": total_txns,
        "total_settlements": total_settlements,
        "breakdown_by_status": breakdown,
        "critical_issues": critical,
        "warning_issues": warning,
        "total_outstanding_amount": round(outstanding_total,2),
        "avg_days_to_settle": round(avg_days_to_settle,2),
        "settlement_rate": round(settlement_rate,2)
    })

if __name__ == "__main__":
    # Auto-init DB if first run
    if not os.path.exists(DB_PATH):
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
