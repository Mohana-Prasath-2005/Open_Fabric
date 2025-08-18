import { useEffect, useState, useMemo, useRef } from "react";
import { PieChart, Pie, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { Link } from "react-router-dom";

const COLORS = ["#10b981","#4b5563" , "#ef4444", "#8b5cf6", "#6b7280", "#f1af3eff" ];

export default function SummaryPage() {
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState("");
  const fileInput = useRef();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/dashboard/summary").then(r => r.json()).then(setSummary);
    fetchRows();
  }, [filter]);

  const fetchRows = () => {
    const qs = filter ? `?status=${encodeURIComponent(filter)}` : "";
    fetch("/api/transactions" + qs).then(r => r.json()).then(setRows);
  };

  const pieData = useMemo(() => {
    if (!summary) return [];
    return Object.entries(summary.breakdown_by_status || {}).map(([name, value]) => ({ name, value }));
  }, [summary]);

  const upload = async () => {
    const f = fileInput.current.files[0];
    if (!f) return alert("Pick a CSV file first!");
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/reconcile", { method: "POST", body: fd });
    setBusy(false);
    if (res.ok) {
      alert("Reconciled successfully!");
      fetchRows();
    } else {
      alert("Error: " + (await res.text()));
    }
  };

  return (
    <div style={{ fontFamily: "Inter, sans-serif", padding: 24, background: "#f9fafb", minHeight: "100vh" }}>
      <h1 style={{ fontSize: 32, fontWeight: 800, marginBottom: 8 }}>📊 Reconciliation Dashboard</h1>
      <p style={{ color: "#6b7280" }}>Overview of transactions, settlements, and reconciliation status</p>

      {/* Summary Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginTop: 20 }}>
        <Card title="Total Transactions" value={summary?.total_transactions} color="#6366f1" icon="💳" />
        <Card title="Settlements" value={summary?.total_settlements} color="#10b981" icon="💰" />
        <Card title="Critical Issues" value={summary?.critical_issues} color="#ef4444" icon="⚠️" />
        <Card title="Warnings" value={summary?.warning_issues} color="#f59e0b" icon="❗" />
      </div>

      {/* Chart + Reconcile */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 32 }}>
        <div style={{ background: "#fff", borderRadius: 16, padding: 20, boxShadow: "0 4px 12px rgba(0,0,0,0.05)" }}>
          <h3 style={{ marginTop: 0 }}>Status Breakdown</h3>
          <div style={{ width: "100%", height: 250 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={100} llabel={({ value }) => value}
>
                  {pieData.map((entry, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Upload & Reconcile */}
        <div
          style={{
            background: "#fff",
            borderRadius: 16,
            padding: 24,
            boxShadow: "0 4px 12px rgba(0,0,0,0.05)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          <h3 style={{ marginBottom: 16, fontSize: 18, fontWeight: 600 }}>📂 Upload & Reconcile</h3>

          {/* File Drop Zone */}
          <label
            htmlFor="file-upload"
            style={{
              border: "2px dashed #6366f1",
              borderRadius: 12,
              padding: "30px 20px",
              width: "75%",
              cursor: "pointer",
              background: "#f9fafb",
              color: "#4b5563",
              fontSize: 14,
              marginBottom: 16,
              transition: "all 0.2s ease",
            }}
            onMouseEnter={e => (e.currentTarget.style.background = "#eef2ff")}
            onMouseLeave={e => (e.currentTarget.style.background = "#f9fafb")}
          >
            <input
              id="file-upload"
              type="file"
              ref={fileInput}
              accept=".csv"
              style={{ display: "none" }}
            />
            <p style={{ margin: 0 }}>Drag & drop a CSV here, or <span style={{ color: "#6366f1", fontWeight: 600 }}>browse</span></p>
          </label>

          {/* Selected File Name */}
          <div id="file-name" style={{ fontSize: 13, color: "#374151", marginBottom: 16 }}>
            {fileInput.current?.files?.[0]?.name || "No file selected"}
          </div>

          {/* Upload Button */}
          <button
            onClick={upload}
            disabled={busy}
            style={{
              padding: "10px 20px",
              borderRadius: 8,
              border: "none",
              background: busy ? "#9ca3af" : "#6366f1",
              color: "#fff",
              fontWeight: 600,
              cursor: busy ? "not-allowed" : "pointer",
              transition: "background 0.2s ease, transform 0.1s ease",
            }}
          >
            {busy ? "⏳ Uploading..." : "🚀 Reconcile CSV"}
          </button>
        </div>
      </div>

      {/* Transactions */}
      <div style={{ marginTop: 32, background: "#fff", borderRadius: 16, padding: 20, boxShadow: "0 4px 12px rgba(0,0,0,0.05)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>💳 Transactions</h3>
          <select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="">All</option>
            <option>PENDING</option>
            <option>PARTIAL</option>
            <option>FULLY_SETTLED</option>
            <option>OVER_SETTLED</option>
            <option>REFUNDED</option>
            <option>NOT_APPLICABLE</option>
          </select>
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #eee" }}>
              <th style={{ padding: 12 }}>Txn ID</th>
              <th>Date</th>
              <th>Merchant</th>
              <th>Amount</th>
              <th>Net Settled</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.transaction_id} style={{ borderBottom: "1px solid #f1f1f4" }}>
                <td style={{ padding: 12 }}>
                  <Link to={`/transactions/${r.transaction_id}`} style={{ color: "blue", textDecoration: "underline" }}>
                    {r.transaction_id}
                  </Link>
                </td>
                <td>{r.transaction_date}</td>
                <td>{r.merchant_name}</td>
                <td>${Number(r.transaction_amount).toFixed(2)}</td>
                <td>${Number(r.net_settled || 0).toFixed(2)}</td>
                <td>
                  <StatusBadge status={r.settlement_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* --- Components --- */
function Card({ title, value, color, icon }) {
  return (
    <div style={{ background: "#fff", borderRadius: 16, padding: 20, boxShadow: "0 4px 12px rgba(0,0,0,0.05)" }}>
      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color }}>{icon} {value ?? "—"}</div>
    </div>
  );
}

function StatusBadge({ status }) {
  const COLORS = {
    FULLY_SETTLED: "#10b981",
    REFUNDED: "#f59e0b",
    PARTIAL: "#8b5cf6",
    OVER_SETTLED: "#ef4444",
    PENDING: "#6b7280",
    NOT_APPLICABLE: "#4b5563"
  };

  return (
    <span
      style={{
        background: COLORS[status] || "#9ca3af",
        color: "white",
        padding: "4px 10px",
        borderRadius: 12,
        fontSize: 12,
        fontWeight: 600
      }}
    >
      {status}
    </span>
  );
}
