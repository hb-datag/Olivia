import { useEffect, useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";

import "./App.css";
import { fetchBranches, fetchCalendar, fetchSession, enroll } from "./lib/api";
import type { Branch, CalendarEvent, SessionDetail } from "./lib/api";

function iso(d: Date) {
  return d.toISOString().slice(0, 10);
}
function startOfWeek(d: Date) {
  const x = new Date(d);
  const day = x.getDay(); // 0=sun
  const diff = (day === 0 ? -6 : 1) - day; // monday start
  x.setDate(x.getDate() + diff);
  x.setHours(0, 0, 0, 0);
  return x;
}

const BUCKETS = [
  { id: "swim", label: "Swim" },
  { id: "gym", label: "Gym" },
  { id: "sports", label: "Sports" },
  { id: "kids", label: "Kids" },
  { id: "run", label: "Run" }
] as const;

export default function App() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranchIds, setSelectedBranchIds] = useState<string[]>([]);
  const [selectedBuckets, setSelectedBuckets] = useState<string[]>(["swim","gym"]);
  const [onlyHasSpots, setOnlyHasSpots] = useState(false);

  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [activeStart, setActiveStart] = useState<string>(() => iso(startOfWeek(new Date())));
  const [activeEnd, setActiveEnd] = useState<string>(() => {
    const s = startOfWeek(new Date());
    const e = new Date(s);
    e.setDate(e.getDate() + 6);
    return iso(e);
  });

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<SessionDetail | null>(null);
  const [enrollMsg, setEnrollMsg] = useState<string>("");

  useEffect(() => {
    fetchBranches().then(setBranches).catch(console.error);
  }, []);

  async function loadCalendar(start: string, end: string) {
    const ev = await fetchCalendar({
      start,
      end,
      branchIds: selectedBranchIds.length ? selectedBranchIds : undefined,
      buckets: selectedBuckets.length ? selectedBuckets : undefined,
      hasSpots: onlyHasSpots
    });
    setEvents(ev);
  }

  useEffect(() => {
    loadCalendar(activeStart, activeEnd).catch(console.error);
  }, [activeStart, activeEnd, selectedBranchIds, selectedBuckets, onlyHasSpots]);

  useEffect(() => {
    if (!selectedSessionId) {
      setSelectedSession(null);
      return;
    }
    setEnrollMsg("");
    fetchSession(selectedSessionId).then(setSelectedSession).catch((e) => {
      console.error(e);
      setSelectedSession(null);
    });
  }, [selectedSessionId]);

  const branchMap = useMemo(() => new Map(branches.map(b => [b.id, b])), [branches]);

  function toggleBranch(id: string) {
    setSelectedBranchIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }
  function toggleBucket(id: string) {
    setSelectedBuckets(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  async function doEnroll() {
    if (!selectedSession) return;
    try {
      const res = await enroll(selectedSession.session_id, "demo_member");
      if (res.already_enrolled) setEnrollMsg("✅ You’re already enrolled.");
      else setEnrollMsg("✅ Enrolled! (synthetic)");
      // refresh details + calendar so color/open-spots update
      const fresh = await fetchSession(selectedSession.session_id);
      setSelectedSession(fresh);
      await loadCalendar(activeStart, activeEnd);
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.message ?? "Enroll failed";
      setEnrollMsg(`❌ ${msg}`);
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", height: "100vh" }}>
      {/* LEFT: master calendar */}
      <div style={{ padding: 18, borderRight: "1px solid rgba(255,255,255,0.12)" }}>
        <h2 style={{ margin: 0 }}>Master Calendar</h2>
        <div style={{ opacity: 0.7, marginTop: 6, marginBottom: 12 }}>
          All branches aggregated. Filters narrow what’s shown.
        </div>

        <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
            <strong>Bucket:</strong>
            {BUCKETS.map(b => (
              <label key={b.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input type="checkbox" checked={selectedBuckets.includes(b.id)} onChange={() => toggleBucket(b.id)} />
                {b.label}
              </label>
            ))}
            <label style={{ marginLeft: 18, display: "flex", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={onlyHasSpots} onChange={() => setOnlyHasSpots(v => !v)} />
              Only show sessions with spots
            </label>
          </div>

          <details>
            <summary><strong>Branches</strong> (multi-select)</summary>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 6, marginTop: 8 }}>
              {branches.map(b => (
                <label key={b.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={selectedBranchIds.includes(b.id)}
                    onChange={() => toggleBranch(b.id)}
                  />
                  {b.name}
                </label>
              ))}
            </div>
            <div style={{ marginTop: 8, opacity: 0.7 }}>
              Tip: leave all unchecked to show every branch.
            </div>
          </details>

          <div style={{ display: "flex", gap: 10, alignItems: "center", opacity: 0.9 }}>
            <span>Legend:</span>
            <span>🟩 &lt;80% full</span>
            <span>🟧 ≥80% full</span>
            <span>🟥 full</span>
          </div>
        </div>

        <FullCalendar
          plugins={[timeGridPlugin, dayGridPlugin, interactionPlugin]}
          initialView="timeGridWeek"
          height="calc(100vh - 190px)"
          nowIndicator
          allDaySlot={false}
          events={events as any}
          datesSet={(arg) => {
            const s = iso(arg.start);
            const e = new Date(arg.end);
            e.setDate(e.getDate() - 1);
            setActiveStart(s);
            setActiveEnd(iso(e));
          }}
          eventClick={(info) => {
            const sid = (info.event.extendedProps as any)?.session_id ?? info.event.id;
            setSelectedSessionId(sid);
          }}
          eventContent={(arg) => {
            const p: any = arg.event.extendedProps || {};
            const color = p.availability_color || "green";
            const bg =
              color === "red" ? "rgba(255,0,0,0.25)" :
              color === "amber" ? "rgba(255,165,0,0.22)" :
              "rgba(0,200,120,0.20)";

            const remaining = Number(p.remaining ?? 0);
            const cap = Number(p.capacity ?? 0);
            const openText = remaining <= 0 ? "FULL" : `${remaining} of ${cap} open`;

            const branchName = (branchMap.get(p.branch_id)?.name ?? p.branch_name ?? "").replace(" YMCA","");

            return (
              <div style={{
                background: bg,
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 10,
                padding: "6px 8px",
                fontSize: 12,
                lineHeight: 1.2,
                cursor: "pointer"
              }}>
                <div style={{ fontWeight: 700 }}>{arg.event.title}</div>
                <div style={{ opacity: 0.85 }}>{branchName}</div>
                <div style={{ opacity: 0.85 }}>{openText}</div>
              </div>
            );
          }}
        />
      </div>

      {/* RIGHT: details + enroll */}
      <div style={{ padding: 18 }}>
        <h2 style={{ margin: 0 }}>Details</h2>
        <div style={{ opacity: 0.7, marginTop: 6, marginBottom: 12 }}>
          Click a class on the calendar to view details and enroll.
        </div>

        {!selectedSession && (
          <div style={{ opacity: 0.75 }}>No class selected.</div>
        )}

        {selectedSession && (
          <div style={{
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 14,
            padding: 14
          }}>
            <div style={{ fontSize: 18, fontWeight: 800 }}>{selectedSession.class_name}</div>
            <div style={{ opacity: 0.85, marginTop: 6 }}>{selectedSession.branch_name}</div>
            <div style={{ opacity: 0.85 }}>{selectedSession.location} · {selectedSession.instructor}</div>
            <div style={{ opacity: 0.85, marginTop: 6 }}>
              {new Date(selectedSession.start_time).toLocaleString()} → {new Date(selectedSession.end_time).toLocaleTimeString()}
            </div>

            <div style={{ marginTop: 10, opacity: 0.9 }}>
              Capacity: {selectedSession.capacity} · Enrolled: {selectedSession.enrolled} · Remaining: {selectedSession.remaining}
            </div>

            <button
              onClick={doEnroll}
              disabled={selectedSession.remaining <= 0}
              style={{ marginTop: 12, padding: "10px 12px", borderRadius: 10, cursor: "pointer" }}
            >
              {selectedSession.remaining <= 0 ? "Class Full" : "Enroll (synthetic)"}
            </button>

            {enrollMsg && <div style={{ marginTop: 10 }}>{enrollMsg}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
