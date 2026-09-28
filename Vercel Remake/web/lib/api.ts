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
  user_agenda?: string;
  auto_agenda?: string;
  manual_summary?: string;
  manual_key_points?: string;
  added_at?: string;
  processed_at?: string;
};

export type Playlist = {
  playlist_id: string;
  name: string;
  description?: string;
  kind: string;
  extraction_focus?: string;
  enabled?: boolean | number;
  video_count?: number;
  done_count?: number;
};

export type Profile = {
  display_name: string;
  email: string;
  about_me: string;
  interests: string;
  insight_style: string;
  known_topics: string;
  personalize_extractions: boolean;
};

export type ProfileResponse = {
  profile: Profile;
  prompt_preview: string;
};

export type AgendaLens = {
  mode: "default" | "custom";
  status: string;
  agenda_text: string;
  profile_active: boolean;
  profile_has_text: boolean;
  profile_prompt_preview: string;
  playlist_id: string;
  playlist_name: string;
  playlist_kind: string;
  playlist_focus: string;
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
  run_after?: string | null;
  progress?: string;
  max_attempts?: number;
  video_title?: string;
};

export type UsageSlot = {
  slot: string;
  label: string;
  role: string;
  masked: string;
  position: number;
  status: "ready" | "resting" | "rejected" | "unused";
  detail: string;
  until: string | null;
  last_used_at?: string | null;
  last_error?: string;
  calls_today: number;
  tokens_today: number;
};

export type UsageReport = {
  chain: UsageSlot[];
  groq_today: { calls: number; tokens: number };
  days: Array<{ date: string; gemini: number; claude: number; groq: number }>;
  day: string;
  published_at?: string | null;
};

export type WorkerStatus = {
  ok: boolean;
  active_workers: number;
  queue: {
    queued: number;
    running: number;
    failed: number;
    done: number;
  };
  workers: Array<{
    worker_id: string;
    status: string;
    current_job_id: string;
    current_video_id: string;
    note: string;
    updated_at: string;
    seconds_since_seen: number;
  }>;
};

export type Readiness = {
  ok: boolean;
  checks: Array<{
    id: string;
    label: string;
    ok: boolean;
    detail: string;
  }>;
  counts: {
    videos: number;
    done: number;
    pending: number;
    failed: number;
    playlists: number;
    focused_playlists: number;
  };
  next_actions: string[];
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
  videos: () => request<{ items: Video[] }>("/videos?limit=200"),
  video: (id: string) => request<{ item: Video; jobs: Job[]; agenda_lens: AgendaLens }>(`/videos/${id}`),
  playlists: () => request<{ items: Playlist[] }>("/playlists"),
  savePlaylist: (id: string, updates: Partial<Pick<Playlist, "name" | "description" | "kind" | "extraction_focus" | "enabled">>) =>
    request<{ ok: boolean; item: Playlist }>(`/playlists/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(updates)
    }),
  createPlaylist: (input: { url: string; name: string; kind: "general" | "podcast"; extraction_focus: string; process_now: number }) =>
    request<{ ok: boolean; item: Playlist; video_count: number | null; job: Job }>("/playlists", {
      method: "POST",
      body: JSON.stringify(input)
    }),
  syncPlaylists: (maxProcess: number) =>
    request<{ ok: boolean; job: Job }>("/playlists/sync", {
      method: "POST",
      body: JSON.stringify({ max_process: maxProcess })
    }),
  profile: () => request<ProfileResponse>("/settings/profile"),
  saveProfile: (profile: Profile) =>
    request<{ ok: boolean } & ProfileResponse>("/settings/profile", {
      method: "POST",
      body: JSON.stringify(profile)
    }),
  applyStarterSetup: (overwrite = false) =>
    request<{ ok: boolean; profile: Profile; prompt_preview: string; playlists: Playlist[]; readiness: Readiness }>("/settings/starter-setup", {
      method: "POST",
      body: JSON.stringify({ overwrite })
    }),
  jobs: () => request<{ items: Job[] }>("/jobs?limit=30"),
  workerStatus: () => request<WorkerStatus>("/worker/status"),
  usage: () => request<UsageReport>("/usage"),
  readiness: () => request<Readiness>("/readiness"),
  search: (q: string) => request<{ items: Video[] }>(`/search?q=${encodeURIComponent(q)}&limit=12`),
  ingest: (input: { url: string; kind: string; agendaMode: "default" | "custom"; agenda: string; playlistId: string }) =>
    request<{ ok: boolean; video: Video; job: Job }>("/ingest", {
      method: "POST",
      body: JSON.stringify({
        url: input.url,
        kind: input.kind,
        agenda_mode: input.agendaMode,
        agenda: input.agenda,
        playlist_id: input.playlistId
      })
    }),
  process: (id: string, input?: { agendaMode?: "default" | "custom"; agenda?: string; reason?: string }) =>
    request<{ ok: boolean; video?: Video; job: Job }>(`/videos/${id}/process`, {
      method: "POST",
      body: JSON.stringify({
        reason: input?.reason || "manual",
        agenda_mode: input?.agendaMode || "default",
        agenda: input?.agenda || ""
      })
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
