import { useEffect, useMemo, useState } from "react";
import "./App.css";
import { fetchBranches, fetchHours, fetchOpenNow } from "./lib/api";
import type { Branch } from "./lib/api";

function isoTodayLocal(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function App() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string>("central_parkway");
  const [date, setDate] = useState<string>(isoTodayLocal());
  const [result, setResult] = useState<string>("");

  const selected = useMemo(
    () => branches.find((b) => b.id === branchId),
    [branches, branchId]
  );

  useEffect(() => {
    fetchBranches().then(setBranches).catch((e) => setResult(String(e)));
  }, []);

  async function onCheckHours() {
    setResult("Loading...");
    try {
      const h = await fetchHours(branchId, date);
      if (h.is_closed || !h.open_time || !h.close_time) {
        setResult(`Closed on ${h.date}.`);
      } else {
        setResult(`Hours on ${h.date}: ${h.open_time}–${h.close_time}.`);
      }
    } catch (e) {
      setResult(String(e));
    }
  }

  async function onOpenNow() {
    setResult("Loading...");
    try {
      const r = await fetchOpenNow(branchId);
      setResult(r.open_now ? "Yes — you’re open right now." : "No — you’re closed right now.");
    } catch (e) {
      setResult(String(e));
    }
  }

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: 24 }}>
      <h1>Olivia (Prototype)</h1>
      <p style={{ opacity: 0.8 }}>
        Backend: <code>{import.meta.env.VITE_API_BASE_URL}</code>
      </p>

      <div style={{ display: "grid", gap: 12 }}>
        <label>
          Branch
          <select
            value={branchId}
            onChange={(e) => setBranchId(e.target.value)}
            style={{ width: "100%", padding: 8, marginTop: 6 }}
          >
            {branches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} ({b.id})
              </option>
            ))}
          </select>
        </label>

        <label>
          Date
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            style={{ width: "100%", padding: 8, marginTop: 6 }}
          />
        </label>

        <div style={{ display: "flex", gap: 12 }}>
          <button onClick={onCheckHours}>Check hours</button>
          <button onClick={onOpenNow}>Open now?</button>
        </div>

        <div style={{ padding: 12, border: "1px solid #ddd", borderRadius: 8 }}>
          <div style={{ fontSize: 12, opacity: 0.7 }}>Selected</div>
          <div style={{ marginTop: 6 }}>
            <strong>{selected?.name ?? branchId}</strong>
          </div>
          <div style={{ marginTop: 12 }}>{result}</div>
        </div>
      </div>
    </div>
  );
}
