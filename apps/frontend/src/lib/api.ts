import axios from "axios";

export type Branch = { id: string; name: string; aliases: string[] };

export type CalendarEvent = {
  id: string;
  title: string;
  start: string;
  end: string;
  extendedProps: {
    session_id: string;
    branch_id: string;
    branch_name: string;
    class_id: string;
    bucket: string;
    tags: string[];
    location: string;
    instructor: string;
    capacity: number;
    enrolled: number;
    remaining: number;
    percent_full: number;
    availability_color: "green" | "amber" | "red";
  };
};

export type SessionDetail = {
  session_id: string;
  class_id: string;
  class_name: string;
  bucket: string;
  tags: string[];
  branch_id: string;
  branch_name: string;
  start_time: string;
  end_time: string;
  location: string;
  instructor: string;
  capacity: number;
  enrolled: number;
  remaining: number;
  percent_full: number;
  availability_color: "green" | "amber" | "red";
};

export type ChatUIContext = {
  selected_branch_ids: string[];
  selected_buckets: string[];
  only_has_spots: boolean;
  member_id: string;
  user_group?: "member" | "front_desk";
};

export type ChatResponse = {
  assistant_message: string;
  follow_up_question?: string | null;
  intent_name: string;
  suggested_sessions?: any[];
  enroll_result?: any;
};

const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function fetchBranches(): Promise<Branch[]> {
  const res = await axios.get(`${API_BASE}/api/v1/branches`);
  return res.data.branches as Branch[];
}

export async function fetchCalendar(params: {
  start: string; end: string;
  branchIds?: string[];
  buckets?: string[];
  hasSpots?: boolean;
}): Promise<CalendarEvent[]> {
  const res = await axios.get(`${API_BASE}/api/v1/calendar`, {
    params: {
      start: params.start,
      end: params.end,
      branch_ids: params.branchIds?.length ? params.branchIds.join(",") : undefined,
      buckets: params.buckets?.length ? params.buckets.join(",") : undefined,
      has_spots: params.hasSpots ? "true" : "false",
    }
  });
  return res.data.events as CalendarEvent[];
}

export async function fetchSession(sessionId: string): Promise<SessionDetail> {
  const res = await axios.get(`${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}`);
  return res.data as SessionDetail;
}

export async function enroll(sessionId: string, memberId = "demo_member"): Promise<any> {
  const res = await axios.post(`${API_BASE}/api/v1/enroll`, { session_id: sessionId, member_id: memberId });
  return res.data;
}

export async function chat(sessionId: string, message: string, ui: ChatUIContext): Promise<ChatResponse> {
  const res = await axios.post(`${API_BASE}/api/v1/chat`, { session_id: sessionId, message, ui_context: ui });
  return res.data as ChatResponse;
}
