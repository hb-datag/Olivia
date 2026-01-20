import axios from "axios";

export type Branch = {
  id: string;
  name: string;
  aliases: string[];
};

export type HoursResponse = {
  branch_id: string;
  date: string;
  is_closed: boolean;
  open_time: string | null;
  close_time: string | null;
};

export type OpenNowResponse = {
  branch_id: string;
  open_now: boolean;
  now: string;
};

const API_BASE =
  (import.meta as any).env?.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function fetchBranches(): Promise<Branch[]> {
  const res = await axios.get(`${API_BASE}/api/v1/branches`);
  return res.data.branches as Branch[];
}

export async function fetchHours(branchId: string, date: string): Promise<HoursResponse> {
  const res = await axios.get(`${API_BASE}/api/v1/hours`, {
    params: { branch_id: branchId, date },
  });
  return res.data as HoursResponse;
}

export async function fetchOpenNow(branchId: string): Promise<OpenNowResponse> {
  const res = await axios.get(`${API_BASE}/api/v1/hours/open-now`, {
    params: { branch_id: branchId },
  });
  return res.data as OpenNowResponse;
}
