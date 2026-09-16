export type Video = {
  video_id: string;
  title: string;
  url: string;
  status: string;
  thumbnail_url?: string;
  summary?: string;
  key_points?: string;
  structured_insights?: string;
  error_message?: string;
  channel_name?: string;
  playlist_type?: string;
  playlist_id?: string;
  transcript_source?: string;
  added_at?: string;
  processed_at?: string;
};

export type Job = {
  id: string;
  kind: string;
  video_id: string;
  status: string;
  attempts: number;
  error: string;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
};

export type Health = {
  ok: boolean;
  database: string;
  services?: Record<string, boolean>;
  error?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    },
    cache: "no-store"
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep the HTTP status message.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  videos: () => request<{ items: Video[] }>("/videos?limit=100"),
  video: (id: string) => request<{ item: Video; jobs: Job[] }>(`/videos/${id}`),
  jobs: () => request<{ items: Job[] }>("/jobs?limit=30"),
  search: (q: string) => request<{ items: Video[] }>(`/search?q=${encodeURIComponent(q)}&limit=12`),
  ingest: (url: string, kind: string) =>
    request<{ ok: boolean; video: Video; job: Job }>("/ingest", {
      method: "POST",
      body: JSON.stringify({ url, kind })
    }),
  process: (id: string) =>
    request<{ ok: boolean; job: Job }>(`/videos/${id}/process`, {
      method: "POST",
      body: JSON.stringify({ reason: "manual" })
    }),
  transcript: (id: string, transcript: string) =>
    request<{ ok: boolean; video: Video; job: Job | null }>(`/videos/${id}/transcript`, {
      method: "POST",
      body: JSON.stringify({ transcript, enqueue: true })
    }),
  saveProviderKeys: (keys: Record<string, string>) =>
    request<{ ok: boolean; services: Record<string, boolean> }>("/settings/providers", {
      method: "POST",
      body: JSON.stringify(keys)
    })
};
