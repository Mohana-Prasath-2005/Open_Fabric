'''\
import os, io, json
from app import app, init_db, DB_PATH

def setup_function(func):
    # Fresh DB
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    app.testing = True

def test_reconcile_and_summary():
    client = app.test_client()
    # load sample csv
    csv_text = open(os.path.join(os.path.dirname(__file__), "..", "settlement_report.csv")).read()
    resp = client.post("/reconcile", json={"csv_text": csv_text})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["processed_rows"] > 0
    assert data["inserted_settlements"] > 0

    summary = client.get("/dashboard/summary").get_json()
    assert "total_transactions" in summary
    assert "breakdown_by_status" in summary

def test_transactions_endpoint():
    client = app.test_client()
    csv_text = open(os.path.join(os.path.dirname(__file__), "..", "settlement_report.csv")).read()
    client.post("/reconcile", json={"csv_text": csv_text})
    resp = client.get("/transactions")
    assert resp.status_code == 200
    arr = resp.get_json()
    assert isinstance(arr, list)
    assert any("issue_flag" in x for x in arr)

def test_transaction_detail():
    client = app.test_client()
    csv_text = open(os.path.join(os.path.dirname(__file__), "..", "settlement_report.csv")).read()
    client.post("/reconcile", json={"csv_text": csv_text})
    resp = client.get("/transactions/TXN004")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "transaction" in data and "settlements" in data
'''

import sqlite3

conn = sqlite3.connect("reconciliation.db")
cursor = conn.cursor()

cursor.execute("DELETE FROM settlement_history")

conn.commit()
conn.close()
