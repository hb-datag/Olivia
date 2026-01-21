import { useEffect, useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import timeGridPlugin from "@fullcalendar/timegrid";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";

import "./App.css";
import { fetchBranches, fetchCalendar, fetchSession, enroll, chat } from "./lib/api";
import { speakText, startSpeechToText } from "./lib/voice";
import type { Branch, CalendarEvent, SessionDetail, ChatResponse } from "./lib/api";

const OLIVIA_GREETING = "This is Olivia with the YMCA! How may I help you?";

function iso(d: Date) { return d.toISOString().slice(0, 10); }
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

type ChatMsg = { role: "user" | "assistant"; text: string };

export default function App() {
  const [userType, setUserType] = useState<"member" | "front_desk">("member");
  const [branches, setBranches] = useState<Branch[]>([]);
  const [selectedBranchIds, setSelectedBranchIds] = useState<string[]>([]);
  const [selectedBuckets, setSelectedBuckets] = useState<string[]>(["swim", "gym"]);
  const [onlyHasSpots, setOnlyHasSpots] = useState(false);

  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [activeStart, setActiveStart] = useState<string>(() => iso(startOfWeek(new Date())));
  const [activeEnd, setActiveEnd] = useState<string>(() => {
    const s = startOfWeek(new Date());
    const e = new Date(s); e.setDate(e.getDate() + 6);
    return iso(e);
  });

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<SessionDetail | null>(null);
  const [enrollMsg, setEnrollMsg] = useState<string>("");
  const [toastMsg, setToastMsg] = useState<string>("");

  const [chatSessionId] = useState(() => (globalThis.crypto?.randomUUID?.() ?? `sess_${Date.now()}`));
  const [chatMsgs, setChatMsgs] = useState<ChatMsg[]>([
    { role: "assistant", text: "Try: “What’s HIIT availability this week at my Y?”" }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [lastChat, setLastChat] = useState<ChatResponse | null>(null);

  useEffect(() => { fetchBranches().then(setBranches).catch(console.error); }, []);

  async function loadCalendar(start: string, end: string) {
    const ev = await fetchCalendar({
      start, end,
      branchIds: selectedBranchIds.length ? selectedBranchIds : undefined,
      buckets: selectedBuckets.length ? selectedBuckets : undefined,
      hasSpots: onlyHasSpots
    });
    setEvents(ev);
  }

  useEffect(() => { loadCalendar(activeStart, activeEnd).catch(console.error); },
    [activeStart, activeEnd, selectedBranchIds, selectedBuckets, onlyHasSpots]
  );

  useEffect(() => {
    if (!selectedSessionId) { setSelectedSession(null); return; }
    setEnrollMsg("");
    fetchSession(selectedSessionId).then(setSelectedSession).catch((e) => { console.error(e); setSelectedSession(null); });
  }, [selectedSessionId]);

  const branchMap = useMemo(() => new Map(branches.map(b => [b.id, b])), [branches]);


  const [voiceOn, setVoiceOn] = useState(false);
  function toggleBranch(id: string) {
    setSelectedBranchIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }
  function toggleBucket(id: string) {
    setSelectedBuckets(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  function pushToast(msg: string) {
    setToastMsg(msg);
    window.setTimeout(() => setToastMsg(""), 2500);
  }

  async function doEnrollSessionId(sessionId: string) {
    try {
      const res = await enroll(sessionId, "demo_member");
      setEnrollMsg(res.already_enrolled ? "✅ You’re already enrolled." : "✅ Enrolled! (synthetic)");
      pushToast(res.already_enrolled ? "✅ You’re already enrolled." : "✅ Enrolled!");
      const fresh = await fetchSession(sessionId);
      setSelectedSession(fresh);
      await loadCalendar(activeStart, activeEnd);
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.message ?? "Enroll failed";
      setEnrollMsg(`❌ ${msg}`);
      pushToast(`❌ ${msg}`);
    }
  }

  async function sendChat(text: string) {
    const t = text.trim();
    if (!t) return;

    setChatMsgs(prev => [...prev, { role: "user", text: t }]);
    setChatInput("");

    const ui = {
      selected_branch_ids: selectedBranchIds,
      selected_buckets: selectedBuckets,
      only_has_spots: onlyHasSpots,
      member_id: "demo_member",
      user_group: userType,
    };

    try {
      const res = await chat(chatSessionId, t, ui);
      setLastChat(res);
      setChatMsgs(prev => {
        let msg = (res.assistant_message ?? "");
        if (prev.length && prev[0].role === "assistant" && prev[0].text === OLIVIA_GREETING && msg.startsWith(OLIVIA_GREETING)) {
          msg = msg.slice(OLIVIA_GREETING.length).replace(/^(\s*\n\s*)+/, "");
        }
        if (!msg.trim()) msg = OLIVIA_GREETING;
        return [...prev, { role: "assistant", text: msg }];
      });

      // if chat enrolled, refresh calendar + details if possible
      if (res.enroll_result?.session_id) {
        pushToast(res.assistant_message?.includes("Enrolled") ? res.assistant_message : "✅ Enrollment updated.");
        await loadCalendar(activeStart, activeEnd);
        setSelectedSessionId(res.enroll_result.session_id);
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e?.message ?? "Chat failed";
      setChatMsgs(prev => [...prev, { role: "assistant", text: `❌ ${msg}` }]);
    }
  }

  return (
    <div style={{ display: "grid", gridTemplateRows: "1fr 0.8fr", height: "100vh" }}>
      {/* TOP: User type selector */}
      <div style={{ position: "absolute", top: 10, left: 10, zIndex: 100, display: "flex", gap: 12, alignItems: "center", background: "rgba(0,0,0,0.3)", padding: "8px 16px", borderRadius: 8 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="radio" name="userType" value="member" checked={userType === "member"} onChange={() => setUserType("member")} />
          Member
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="radio" name="userType" value="front_desk" checked={userType === "front_desk"} onChange={() => setUserType("front_desk")} />
          Front Desk
        </label>
      </div>

      {/* TOP: master calendar */}
      <div style={{ padding: 18, borderBottom: "1px solid rgba(255,255,255,0.12)", overflow: "auto" }}>
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
                  <input type="checkbox" checked={selectedBranchIds.includes(b.id)} onChange={() => toggleBranch(b.id)} />
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
          height="350px"
          nowIndicator
          allDaySlot={false}
          events={events as any}
          datesSet={(arg) => {
            const s = iso(arg.start);
            const e = new Date(arg.end); e.setDate(e.getDate() - 1);
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

      {/* BOTTOM: details + chat */}
      <div style={{ padding: 18, display: "grid", gridTemplateRows: "auto 1fr", gap: 14, overflow: "auto" }}>
        <div>
          <h2 style={{ margin: 0 }}>Details</h2>
          <div style={{ opacity: 0.7, marginTop: 6, marginBottom: 12 }}>
            Click a class to view details and enroll.
          </div>

          {!selectedSession && <div style={{ opacity: 0.75 }}>No class selected.</div>}

          {selectedSession && (
            <div style={{ border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14, padding: 14 }}>
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
                onClick={() => doEnrollSessionId(selectedSession.session_id)}
                disabled={selectedSession.remaining <= 0}
                style={{ marginTop: 12, padding: "10px 12px", borderRadius: 10, cursor: "pointer" }}
              >
                {selectedSession.remaining <= 0 ? "Class Full" : "Enroll (synthetic)"}
              </button>

              {enrollMsg && <div style={{ marginTop: 10 }}>{enrollMsg}</div>}
            </div>
          )}
        </div>

        <div style={{ border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14, padding: 14, overflow: "auto" }}>
          <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 10 }}>Chat</div>

            {toastMsg && (
              <div style={{ marginBottom: 10, padding: "8px 10px", borderRadius: 10, background: "rgba(0,0,0,0.35)", border: "1px solid rgba(255,255,255,0.10)" }}>
                {toastMsg}
              </div>
            )}


          <div style={{ display: "grid", gap: 10 }}>
            {chatMsgs.map((m, i) => (
              <div key={i} style={{
                justifySelf: m.role === "user" ? "end" : "start",
                maxWidth: "90%",
                padding: "10px 12px",
                borderRadius: 12,
                background: m.role === "user" ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.20)",
                whiteSpace: "pre-wrap"
              }}>
                {m.text}
              </div>
            ))}
          </div>

          {lastChat?.suggested_sessions?.length ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Suggested sessions</div>
              <div style={{ display: "grid", gap: 8 }}>
                {lastChat.suggested_sessions.slice(0, 6).map((s: any, idx: number) => (
                  <div key={s.session_id} style={{ padding: 10, borderRadius: 12, border: "1px solid rgba(255,255,255,0.10)" }}>
                    <div style={{ fontWeight: 700 }}>{idx + 1}) {s.class_name}</div>
                    <div style={{ opacity: 0.85 }}>{new Date(s.start_time).toLocaleString()} · {s.branch_name}</div>
                    <div style={{ opacity: 0.85 }}>{s.remaining} of {s.capacity} open</div>
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <button onClick={() => setSelectedSessionId(s.session_id)} style={{ padding: "8px 10px", borderRadius: 10, cursor: "pointer" }}>
                        Select
                      </button>
                      <button onClick={() => doEnrollSessionId(s.session_id)} style={{ padding: "8px 10px", borderRadius: 10, cursor: "pointer" }}>
                        Enroll
                      </button>
                      <button onClick={() => sendChat(`Sign me up for option ${idx + 1}`)} style={{ padding: "8px 10px", borderRadius: 10, cursor: "pointer" }}>
                        Enroll option {idx + 1}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(chatInput); } }}
              placeholder='Ask: "What’s HIIT availability this week at my Y?"'
              style={{ flex: 1, padding: "10px 12px", borderRadius: 10 }}
            />
            <button onClick={() => sendChat(chatInput)} style={{ padding: "10px 12px", borderRadius: 10, cursor: "pointer" }}>
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
