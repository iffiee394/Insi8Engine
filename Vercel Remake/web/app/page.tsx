"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type Health, type Job, type Playlist, type Profile, type Readiness, type Video, type WorkerStatus } from "../lib/api";
import { videoInsights, videoResearch, videoSummary } from "../lib/insights";

type Page = "library" | "add" | "queue" | "settings";

const DEFAULT_AGENDA = `The worker will generate the real agenda from your saved profile, selected playlist profile, and the video's transcript. Keep your profile current so the system knows which insights are important for you.`;

const EMPTY_PROFILE: Profile = {
  display_name: "",
  email: "",
  about_me: "",
  interests: "",
  insight_style: "",
  known_topics: "",
  personalize_extractions: true
};

const CUSTOM_AGENDA_EXAMPLE = `Focus on:
- specific tactics I can apply
- tools, links, companies, and people mentioned
- decisions or frameworks worth saving
- questions I should research next`;

const nav: Array<{ page: Page; label: string; icon: React.ReactNode }> = [
  { page: "library", label: "Library", icon: iconLibrary() },
  { page: "add", label: "Add", icon: iconPlus() },
  { page: "queue", label: "Queue", icon: iconQueue() },
  { page: "settings", label: "Settings", icon: iconSettings() }
];

function statusClass(status: string | undefined) {
  return `pill ${status || "pending"}`;
}

function thumbnailUrl(video: Video): string {
  return video.thumbnail_url || `https://i.ytimg.com/vi/${video.video_id}/mqdefault.jpg`;
}

const providerNames = ["youtube", "gemini", "anthropic", "groq", "tavily"] as const;

const providerEnvToName: Record<string, string> = {
  YOUTUBE_API_KEY: "youtube",
  GEMINI_API_KEY: "gemini",
  GOOGLE_API_KEY: "gemini",
  ANTHROPIC_API_KEY: "anthropic",
  GROQ_API_KEY: "groq",
  TAVILY_API_KEY: "tavily"
};

function stripWrappingQuotes(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2 && trimmed[0] === trimmed[trimmed.length - 1] && ["'", '"'].includes(trimmed[0])) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function parseProviderKeyBlock(input: string): Record<string, string> {
  const parsed: Record<string, string> = {};
  const trimmed = input.trim();
  if (!trimmed) return parsed;

  if (trimmed.startsWith("{")) {
    try {
      const data = JSON.parse(trimmed) as Record<string, unknown>;
      for (const [key, rawValue] of Object.entries(data)) {
        const provider = providerEnvToName[key.trim().toUpperCase()] || key.trim().toLowerCase();
        if (providerNames.includes(provider as (typeof providerNames)[number]) && typeof rawValue === "string" && rawValue.trim()) {
          parsed[provider] = stripWrappingQuotes(rawValue);
        }
      }
      return parsed;
    } catch {
      // Fall back to .env parsing below.
    }
  }

  for (const originalLine of input.replace(/\r\n/g, "\n").split("\n")) {
    let line = originalLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.toLowerCase().startsWith("export ")) line = line.slice(7).trim();
    if (!line.includes("=")) continue;
    const [rawName, ...rawParts] = line.split("=");
    const provider = providerEnvToName[rawName.trim().toUpperCase()] || rawName.trim().toLowerCase();
    const value = stripWrappingQuotes(rawParts.join("="));
    if (providerNames.includes(provider as (typeof providerNames)[number]) && value) {
      parsed[provider] = value;
    }
  }
  return parsed;
}

function normalizeSingleProviderInput(value: string, provider: string): string {
  const parsed = parseProviderKeyBlock(value);
  if (parsed[provider]) return parsed[provider];
  const keys = Object.values(parsed);
  if (keys.length === 1) return keys[0];
  return stripWrappingQuotes(value);
}

function profileHasText(profile: Profile): boolean {
  return ["about_me", "interests", "insight_style", "known_topics"].some((key) =>
    String(profile[key as keyof Profile] || "").trim()
  );
}

export default function Home() {
  const [page, setPage] = useState<Page>("library");
  const [videos, setVideos] = useState<Video[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<Video | null>(null);
  const [selectedJobs, setSelectedJobs] = useState<Job[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus | null>(null);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [profile, setProfile] = useState<Profile>(EMPTY_PROFILE);
  const [profilePrompt, setProfilePrompt] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [query, setQuery] = useState("");
  const [playlistFilter, setPlaylistFilter] = useState("all");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadVideo(id: string) {
    const result = await api.video(id);
    setError("");
    setSelected(result.item);
    setSelectedJobs(result.jobs);
  }

  async function loadVideos(preferredId?: string) {
    const result = await api.videos();
    setError("");
    setVideos(result.items);
    const nextId = preferredId || selectedId || result.items[0]?.video_id || "";
    setSelectedId(nextId);
    if (nextId) await loadVideo(nextId);
  }

  async function loadJobs() {
    const [result, worker] = await Promise.all([api.jobs(), api.workerStatus()]);
    setError("");
    setJobs(result.items);
    setWorkerStatus(worker);
  }

  async function syncPlaylists(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setLoading(true);
    const form = new FormData(event.currentTarget);
    const raw = Number(form.get("maxProcess") || 3);
    const maxProcess = Number.isFinite(raw) ? Math.max(0, Math.min(raw, 50)) : 3;
    try {
      await api.syncPlaylists(maxProcess);
      setNotice(maxProcess === 0 ? "Playlist sync queued. It will register new videos without processing them." : `Playlist sync queued. It will process up to ${maxProcess} pending video${maxProcess === 1 ? "" : "s"}.`);
      setPage("queue");
      await loadJobs();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not queue playlist sync.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    async function boot() {
      try {
        const [healthResult, videosResult, jobsResult, playlistsResult, profileResult, workerResult, readinessResult] = await Promise.all([
          api.health(),
          api.videos(),
          api.jobs(),
          api.playlists(),
          api.profile(),
          api.workerStatus(),
          api.readiness()
        ]);
        setError("");
        setHealth(healthResult);
        setVideos(videosResult.items);
        setJobs(jobsResult.items);
        setWorkerStatus(workerResult);
        setReadiness(readinessResult);
        setPlaylists(playlistsResult.items);
        setProfile(profileResult.profile);
        setProfilePrompt(profileResult.prompt_preview);
        const firstVideo = videosResult.items[0] || null;
        setSelected(firstVideo);
        setSelectedId(firstVideo?.video_id || "");
        if (firstVideo) await loadVideo(firstVideo.video_id);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Could not load the app.");
      }
    }
    void boot();
  }, []);

  useEffect(() => {
    if (page !== "queue") return;
    const timer = window.setInterval(() => void loadJobs(), 5000);
    return () => window.clearInterval(timer);
  }, [page]);

  const playlistNames = useMemo(
    () => new Map(playlists.map((playlist) => [playlist.playlist_id, playlist.name || playlist.kind])),
    [playlists]
  );

  const playlistTabs = useMemo(() => {
    const counts = new Map<string, number>();
    for (const video of videos) {
      const key = video.playlist_id && playlistNames.has(video.playlist_id) ? video.playlist_id : "none";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const tabs = [{ id: "all", label: "All", count: videos.length }];
    for (const playlist of playlists) {
      tabs.push({ id: playlist.playlist_id, label: playlist.name || playlist.kind, count: counts.get(playlist.playlist_id) || 0 });
    }
    if (counts.get("none")) tabs.push({ id: "none", label: "Manual", count: counts.get("none") || 0 });
    return tabs;
  }, [videos, playlists, playlistNames]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return videos.filter((video) => {
      if (playlistFilter !== "all") {
        const key = video.playlist_id && playlistNames.has(video.playlist_id) ? video.playlist_id : "none";
        if (key !== playlistFilter) return false;
      }
      if (!q) return true;
      return [video.title, video.channel_name, video.status].some((value) =>
        (value || "").toLowerCase().includes(q)
      );
    });
  }, [videos, query, playlistFilter, playlistNames]);

  const doneCount = videos.filter((video) => video.status === "done").length;
  const activeJobs = jobs.filter((job) => ["queued", "running"].includes(job.status)).length;
  const displayedVideo = selected ?? videos.find((video) => video.video_id === selectedId) ?? null;

  async function chooseVideo(id: string) {
    setSelectedId(id);
    setSelected(videos.find((video) => video.video_id === id) ?? null);
    setSelectedJobs([]);
    setError("");
    setPage("library");
    await loadVideo(id);
  }

  async function submitAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setLoading(true);
    const form = new FormData(event.currentTarget);
    try {
      const url = String(form.get("url") || "");
      const kind = String(form.get("kind") || "video");
      const agendaMode = String(form.get("agendaMode") || "default") === "custom" ? "custom" : "default";
      const agenda = String(form.get("agenda") || "").trim();
      const playlistId = String(form.get("playlistId") || "").trim();
      const result = await api.ingest({ url, kind, agendaMode, agenda, playlistId });
      setNotice(`Queued: ${result.video.title || result.video.video_id}`);
      setPage("library");
      await loadVideos(result.video.video_id);
      await loadJobs();
      event.currentTarget.reset();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not add this video.");
    } finally {
      setLoading(false);
    }
  }

  async function processSelected() {
    if (!selected) return;
    setError("");
    setNotice("");
    setLoading(true);
    try {
      await api.process(selected.video_id, { agendaMode: "default", reason: "default" });
      setNotice("Queued with the default agenda.");
      await loadVideo(selected.video_id);
      await loadJobs();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not queue this video.");
    } finally {
      setLoading(false);
    }
  }

  async function processSelectedWithAgenda(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    const agenda = String(form.get("agenda") || "").trim();
    setError("");
    setNotice("");
    setLoading(true);
    try {
      const result = await api.process(selected.video_id, { agendaMode: "custom", agenda, reason: "custom_agenda" });
      setNotice("Queued with your custom agenda.");
      if (result.video) setSelected(result.video);
      await loadVideo(selected.video_id);
      await loadJobs();
      event.currentTarget.reset();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not queue this video with a custom agenda.");
    } finally {
      setLoading(false);
    }
  }

  async function submitTranscript(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setLoading(true);
    setError("");
    setNotice("");
    const form = new FormData(event.currentTarget);
    try {
      await api.transcript(selected.video_id, String(form.get("transcript") || ""));
      setNotice("Transcript saved and processing queued.");
      await loadVideo(selected.video_id);
      await loadJobs();
      event.currentTarget.reset();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not save transcript.");
    } finally {
      setLoading(false);
    }
  }

  async function savePlaylistFocus(playlistId: string, updates: Partial<Pick<Playlist, "name" | "description" | "kind" | "extraction_focus" | "enabled">>) {
    const result = await api.savePlaylist(playlistId, updates);
    setPlaylists((items) => items.map((playlist) => playlist.playlist_id === playlistId ? result.item : playlist));
    if (selected?.playlist_id === playlistId) {
      await loadVideo(selected.video_id);
    }
    return result.item;
  }

  async function applyStarterSetup(overwrite = false) {
    const result = await api.applyStarterSetup(overwrite);
    setProfile(result.profile);
    setProfilePrompt(result.prompt_preview);
    setPlaylists(result.playlists);
    setReadiness(result.readiness);
    if (selected) await loadVideo(selected.video_id);
    return result;
  }

  return (
    <main className="shell">
      <aside className="rail" aria-label="Primary navigation">
        <div className="mark">IE</div>
        {nav.map((item) => (
          <button
            key={item.page}
            className={page === item.page ? "active" : ""}
            aria-label={item.label}
            title={item.label}
            onClick={() => setPage(item.page)}
          >
            {item.icon}
          </button>
        ))}
      </aside>

      <section className="app">
        <aside className="context">
          <div className="context-head">
            <strong className="wordmark">InsightEngine</strong>
            <button className="icon-button" onClick={() => void loadVideos()} aria-label="Refresh library" title="Refresh library">
              {iconRefresh()}
            </button>
          </div>

          <div className="context-tools">
            <label className="search">
              {iconSearch()}
              <input
                id="filter"
                aria-label="Search library"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search titles and channels"
              />
            </label>
            <div className="playlist-tabs" role="tablist" aria-label="Filter by playlist">
              {playlistTabs.map((tab) => (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={playlistFilter === tab.id}
                  className={playlistFilter === tab.id ? "active" : ""}
                  onClick={() => setPlaylistFilter(tab.id)}
                >
                  {tab.label} <span>{tab.count}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="list" aria-label="Videos">
            {filtered.map((video) => (
              <button
                key={video.video_id}
                className={`row ${selectedId === video.video_id ? "active" : ""}`}
                onClick={() => void chooseVideo(video.video_id)}
              >
                <span className="thumb" aria-hidden="true">
                  <img src={thumbnailUrl(video)} alt="" loading="lazy" />
                </span>
                <span className="row-body">
                  <strong>{video.title || video.video_id}</strong>
                  <span className="row-meta">
                    {video.status !== "done" ? <i className={`dot ${video.status}`} title={video.status} /> : null}
                    {video.channel_name || "Unknown channel"}
                    {playlistFilter === "all" && video.playlist_id && playlistNames.has(video.playlist_id)
                      ? ` · ${playlistNames.get(video.playlist_id)}`
                      : ""}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="main">
          <header className="main-head">
            <p className="page-name">{nav.find((item) => item.page === page)?.label}</p>
            <div className="main-actions">
              <span className="stat">{doneCount} processed</span>
              <span className={`stat ${activeJobs ? "live" : ""}`}>{activeJobs} running</span>
              <button className="button" onClick={() => setPage("add")}>
                {iconPlus()} Add video
              </button>
            </div>
          </header>

          <div className="content">
            {notice ? <p className="notice">{notice}</p> : null}
            {error ? <p className="notice error">{error}</p> : null}

            {page === "library" ? (
              <VideoDetail
                key={displayedVideo?.video_id || "none"}
                video={displayedVideo}
                jobs={selectedJobs}
                playlistName={displayedVideo?.playlist_id ? playlistNames.get(displayedVideo.playlist_id) || "" : ""}
                loading={loading}
                onProcess={processSelected}
                onCustomProcess={processSelectedWithAgenda}
                onTranscript={submitTranscript}
              />
            ) : null}

            {page === "add" ? (
              <AddPanel
                loading={loading}
                playlists={playlists}
                profile={profile}
                profilePrompt={profilePrompt}
                onSubmit={submitAdd}
              />
            ) : null}

            {page === "queue" ? (
              <QueuePanel jobs={jobs} workerStatus={workerStatus} loading={loading} onRefresh={loadJobs} onSync={syncPlaylists} />
            ) : null}

            {page === "settings" ? (
              <SettingsPanel
                health={health}
                readiness={readiness}
                profile={profile}
                profilePrompt={profilePrompt}
                playlists={playlists}
                onPlaylistSaved={savePlaylistFocus}
                onReadinessRefresh={async () => {
                  const result = await api.readiness();
                  setReadiness(result);
                  return result;
                }}
                onStarterSetup={applyStarterSetup}
                onProfileSaved={(nextProfile, nextPrompt) => {
                  setProfile(nextProfile);
                  setProfilePrompt(nextPrompt);
                }}
              />
            ) : null}
          </div>
        </section>
      </section>
    </main>
  );
}

function VideoDetail({
  video,
  jobs,
  playlistName,
  loading,
  onProcess,
  onCustomProcess,
  onTranscript
}: {
  video: Video | null;
  jobs: Job[];
  playlistName: string;
  loading: boolean;
  onProcess: () => Promise<void>;
  onCustomProcess: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  onTranscript: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const [toolsOpen, setToolsOpen] = useState(() => Boolean(video && video.status !== "done"));
  const [toolTab, setToolTab] = useState<"agenda" | "transcript">(() =>
    video?.status === "failed" && /download|forbidden|403/i.test(video.error_message || "") ? "transcript" : "agenda"
  );

  if (!video) {
    return (
      <section className="empty-state">
        <h1 className="detail-title">Pick a video</h1>
        <p className="lede">Choose one from the library, or add a new video to extract what matters in it.</p>
      </section>
    );
  }

  const summary = videoSummary(video);
  const insights = videoInsights(video);
  const research = videoResearch(video);
  const failed = video.status === "failed";
  const activeJob = jobs.find((job) => job.status === "queued" || job.status === "running");
  const lastJob = jobs[0];

  return (
    <article className="video">
      <div className="ambient" aria-hidden="true">
        <img src={thumbnailUrl(video)} alt="" />
      </div>

      <header className="video-head">
        <p className="eyebrow">
          <span className="eyebrow-status">
            <i className={`dot ${activeJob ? "processing" : video.status}`} />
            {activeJob ? "processing" : video.status}
          </span>
          <span>{video.channel_name || "Unknown channel"}</span>
          {playlistName ? <span>{playlistName}</span> : null}
        </p>
        <h1 className="detail-title">{video.title || video.video_id}</h1>
        <div className="actions">
          <a className="button" href={video.url} target="_blank" rel="noreferrer">
            {iconPlay()} Watch
          </a>
          <button
            className={`ghost ${toolsOpen ? "on" : ""}`}
            aria-expanded={toolsOpen}
            onClick={() => setToolsOpen((open) => !open)}
          >
            {iconRefresh()} Reprocess
          </button>
        </div>
      </header>

      {failed ? (
        <p className="notice error">
          <strong>Extraction failed.</strong> {video.error_message || "The worker recorded a failure."}
        </p>
      ) : null}

      {toolsOpen ? (
        <section className="tools" aria-label="Reprocess this video">
          <div className="tools-head">
            <div className="segmented" role="tablist" aria-label="Reprocess method">
              <button role="tab" aria-selected={toolTab === "agenda"} className={toolTab === "agenda" ? "active" : ""} onClick={() => setToolTab("agenda")}>
                Custom agenda
              </button>
              <button role="tab" aria-selected={toolTab === "transcript"} className={toolTab === "transcript" ? "active" : ""} onClick={() => setToolTab("transcript")}>
                Paste transcript
              </button>
            </div>
            <button className="text-button" onClick={() => void onProcess()} disabled={loading}>
              Rerun with my profile
            </button>
          </div>

          {toolTab === "agenda" ? (
            <form className="form" onSubmit={onCustomProcess}>
              <textarea name="agenda" required minLength={10} placeholder={CUSTOM_AGENDA_EXAMPLE} defaultValue={video.user_agenda || ""} />
              <button className="button" disabled={loading}>Rerun with this agenda</button>
            </form>
          ) : (
            <form className="form" onSubmit={onTranscript}>
              <textarea name="transcript" required minLength={100} placeholder="Paste the full transcript. Use this when YouTube blocks the audio download." />
              <button className="button" disabled={loading}>Save transcript and rerun</button>
            </form>
          )}

          {lastJob ? (
            <p className="job-line">
              Last run · {lastJob.status} · {lastJob.attempts} attempt{lastJob.attempts === 1 ? "" : "s"}
              {lastJob.error ? ` · ${lastJob.error}` : ""}
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="block">
        <h2 className="eyebrow">Summary</h2>
        <p className="lede">
          {summary || (activeJob ? "The worker is extracting insights from this video now." : "No insights yet. Use Reprocess to run extraction.")}
        </p>
      </section>

      {insights.length ? (
        <section className="block">
          <h2 className="eyebrow">Insights <span className="count">{insights.length}</span></h2>
          <div className="index">
            {insights.map((insight, index) => (
              <details className="entry" key={`${insight.title}-${index}`}>
                <summary>
                  <span className="entry-title">{insight.title}</span>
                  <span className="leader" aria-hidden="true" />
                  <span className="entry-count">{insight.points.length ? `${insight.points.length} pts` : ""}</span>
                  {iconChevron()}
                </summary>
                <div className="entry-body">
                  {insight.content ? <p>{insight.content}</p> : null}
                  {insight.points.length ? (
                    <ul>
                      {insight.points.map((point) => (
                        <li key={point}>{point}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </details>
            ))}
          </div>
        </section>
      ) : null}

      {research.resources.length ? (
        <section className="block">
          <h2 className="eyebrow">Resources <span className="count">{research.resources.length}</span></h2>
          <div className="index">
            {research.resources.map((resource, index) => (
              <details className="entry" key={`${resource.name}-${index}`}>
                <summary>
                  <span className="entry-title">{resource.name}</span>
                  <span className="leader" aria-hidden="true" />
                  <span className="entry-count">{resource.type}</span>
                  {iconChevron()}
                </summary>
                <div className="entry-body">
                  {resource.detail ? <p>{resource.detail}</p> : null}
                  {resource.url ? (
                    <a className="out-link" href={resource.url} target="_blank" rel="noreferrer">
                      Open source ↗
                    </a>
                  ) : null}
                </div>
              </details>
            ))}
          </div>
        </section>
      ) : null}

      {research.links.length ? (
        <section className="block">
          <h2 className="eyebrow">Links <span className="count">{research.links.length}</span></h2>
          <div className="index">
            <details className="entry">
              <summary>
                <span className="entry-title">Links from the video, description and research</span>
                <span className="leader" aria-hidden="true" />
                <span className="entry-count">{research.links.length}</span>
                {iconChevron()}
              </summary>
              <div className="entry-body link-list">
                {research.links.map((link) => (
                  <a href={link.url} target="_blank" rel="noreferrer" key={link.url}>
                    <span>{link.label}</span>
                    <small>{link.source}</small>
                  </a>
                ))}
              </div>
            </details>
          </div>
        </section>
      ) : null}
    </article>
  );
}

function AddPanel({
  loading,
  playlists,
  profile,
  profilePrompt,
  onSubmit
}: {
  loading: boolean;
  playlists: Playlist[];
  profile: Profile;
  profilePrompt: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const [agendaMode, setAgendaMode] = useState<"default" | "custom">("default");
  const hasProfile = profileHasText(profile);
  return (
    <section>
      <p className="caps">New source</p>
      <h1 className="detail-title">Add a video</h1>
      <p className="summary">
        This creates a queued job. The worker processes the video separately, so the dashboard stays fast.
      </p>

      <section className="agenda-cockpit" aria-label="Agenda cockpit">
        <div>
          <p className="reader-label">Goal</p>
          <h2>Extract what matters to you, not a generic summary.</h2>
          <p>
            Default processing builds the agenda from your saved profile, the selected playlist focus, and the transcript. Custom agenda adds a video-specific instruction on top of that profile.
          </p>
        </div>
        <div className="cockpit-grid">
          <div>
            <strong>{hasProfile ? "Profile active" : "Profile needed"}</strong>
            <span>{hasProfile ? "Default agendas will use your saved interests and style." : "Add your profile in Settings before serious processing."}</span>
          </div>
          <div>
            <strong>Default agenda</strong>
            <span>Best for normal videos and playlist automation.</span>
          </div>
          <div>
            <strong>Custom agenda</strong>
            <span>Best when this one video needs a special angle.</span>
          </div>
        </div>
        {profilePrompt ? (
          <details className="mini-preview">
            <summary>Current profile lens</summary>
            <pre>{profilePrompt}</pre>
          </details>
        ) : null}
      </section>

      <form className="form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="url">YouTube URL</label>
          <input id="url" name="url" required placeholder="https://www.youtube.com/watch?v=..." />
        </div>
        <div className="field">
          <label htmlFor="kind">Type</label>
          <select id="kind" name="kind" defaultValue="video">
            <option value="video">Video</option>
            <option value="podcast">Podcast</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="playlistId">Playlist profile</label>
          <select id="playlistId" name="playlistId" defaultValue="">
            <option value="">No specific playlist</option>
            {playlists.map((playlist) => (
              <option value={playlist.playlist_id} key={playlist.playlist_id}>
                {playlist.name || playlist.playlist_id} · {playlist.kind}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="agendaMode">Agenda</label>
          <select
            id="agendaMode"
            name="agendaMode"
            value={agendaMode}
            onChange={(event) => setAgendaMode(event.target.value === "custom" ? "custom" : "default")}
          >
            <option value="default">Default agenda</option>
            <option value="custom">Custom agenda</option>
          </select>
        </div>
        {agendaMode === "default" ? (
          <p className="notice">{DEFAULT_AGENDA}</p>
        ) : (
          <div className="field">
            <label htmlFor="agenda">Custom agenda</label>
            <textarea id="agenda" name="agenda" required minLength={10} placeholder={CUSTOM_AGENDA_EXAMPLE} />
          </div>
        )}
        <button className="button" disabled={loading}>
          {loading ? "Adding..." : "Add and queue"}
        </button>
      </form>
    </section>
  );
}

function QueuePanel({
  jobs,
  workerStatus,
  loading,
  onRefresh,
  onSync
}: {
  jobs: Job[];
  workerStatus: WorkerStatus | null;
  loading: boolean;
  onRefresh: () => Promise<void>;
  onSync: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const newestWorker = workerStatus?.workers[0] || null;
  return (
    <section>
      <div className="main-actions" style={{ justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <p className="caps">Worker queue</p>
          <h1 className="detail-title">Queue</h1>
        </div>
        <button className="ghost" onClick={() => void onRefresh()}>
          Refresh
        </button>
      </div>

      <section className="status-strip" aria-label="Worker status">
        <div>
          <strong>{workerStatus?.ok ? "Worker online" : "Worker not seen"}</strong>
          <span>
            {newestWorker
              ? `${newestWorker.status} · seen ${newestWorker.seconds_since_seen}s ago`
              : "Start the worker so queued videos can process."}
          </span>
        </div>
        <div>
          <strong>{workerStatus?.queue.queued ?? 0}</strong>
          <span>queued</span>
        </div>
        <div>
          <strong>{workerStatus?.queue.running ?? 0}</strong>
          <span>running</span>
        </div>
        <div>
          <strong>{workerStatus?.queue.failed ?? 0}</strong>
          <span>failed</span>
        </div>
      </section>

      <details className="card" open>
        <summary>Sync enabled playlists</summary>
        <p>
          Pulls new videos from the enabled playlist profiles, stores them in the library, and processes the oldest pending videos with the default profile-driven agenda. Use 0 to register videos only.
        </p>
        <form className="settings-form" onSubmit={onSync}>
          <div className="field">
            <label htmlFor="maxProcess">Max videos to process now</label>
            <input id="maxProcess" name="maxProcess" type="number" min="0" max="50" defaultValue="3" />
          </div>
          <button className="button" disabled={loading}>{loading ? "Queueing..." : "Sync playlists"}</button>
        </form>
      </details>

      <div className="queue-list">
        {jobs.length ? (
          jobs.map((job) => (
            <div className="job" key={job.id}>
              <span className={statusClass(job.status)}>{job.status}</span>
              <span>{job.kind === "sync_playlists" ? "Enabled playlists" : job.video_id}</span>
              <span>{job.kind} · {job.attempts} attempt{job.attempts === 1 ? "" : "s"}</span>
              {job.error ? <span className="notice error">{job.error}</span> : null}
            </div>
          ))
        ) : (
          <p className="summary">No jobs yet.</p>
        )}
      </div>
    </section>
  );
}

function SettingsPanel({
  health,
  readiness,
  profile,
  profilePrompt,
  playlists,
  onPlaylistSaved,
  onReadinessRefresh,
  onStarterSetup,
  onProfileSaved
}: {
  health: Health | null;
  readiness: Readiness | null;
  profile: Profile;
  profilePrompt: string;
  playlists: Playlist[];
  onPlaylistSaved: (playlistId: string, updates: Partial<Pick<Playlist, "name" | "description" | "kind" | "extraction_focus" | "enabled">>) => Promise<Playlist>;
  onReadinessRefresh: () => Promise<Readiness>;
  onStarterSetup: (overwrite?: boolean) => Promise<{ profile: Profile; prompt_preview: string; playlists: Playlist[]; readiness: Readiness }>;
  onProfileSaved: (profile: Profile, prompt: string) => void;
}) {
  const [services, setServices] = useState<Record<string, boolean>>(health?.services || {});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [bulkKeys, setBulkKeys] = useState("");
  const [profileDraft, setProfileDraft] = useState<Profile>(profile);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMessage, setProfileMessage] = useState("");

  useEffect(() => {
    setServices(health?.services || {});
  }, [health]);

  useEffect(() => {
    setProfileDraft(profile);
  }, [profile]);

  function updateProfileField<K extends keyof Profile>(key: K, value: Profile[K]) {
    setProfileDraft((current) => ({ ...current, [key]: value }));
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfileSaving(true);
    setProfileMessage("");
    try {
      const result = await api.saveProfile(profileDraft);
      onProfileSaved(result.profile, result.prompt_preview);
      setProfileMessage("Profile saved. New agenda generation will use this profile.");
    } catch (exc) {
      setProfileMessage(exc instanceof Error ? exc.message : "Could not save profile.");
    } finally {
      setProfileSaving(false);
    }
  }

  async function saveKeys(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    const form = new FormData(event.currentTarget);
    const keys: Record<string, string> = parseProviderKeyBlock(bulkKeys);
    for (const name of providerNames) {
      const value = String(form.get(name) || "").trim();
      if (value) keys[name] = normalizeSingleProviderInput(value, name);
    }
    if (!Object.keys(keys).length) {
      setMessage("Paste at least one key, either as a raw key or as NAME=value.");
      return;
    }
    setSaving(true);
    try {
      const result = await api.saveProviderKeys(keys);
      setServices(result.services);
      setMessage(`Saved ${Object.keys(keys).length} key${Object.keys(keys).length === 1 ? "" : "s"}. New jobs will use the updated provider keys.`);
      setBulkKeys("");
      event.currentTarget.reset();
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "Could not save keys.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <p className="caps">Configuration</p>
      <h1 className="detail-title">Settings</h1>
      <p className={health?.ok ? "notice" : "notice error"}>
        API status: {health?.ok ? "connected" : health?.error || "not connected yet"}.
      </p>
      <div className="settings-grid">
        {["youtube", "gemini", "anthropic", "groq", "tavily"].map((name) => (
          <div className="service" key={name}>
            <strong>{name[0].toUpperCase() + name.slice(1)}</strong>
            <span>{services[name] ? "Configured" : "Missing"}</span>
          </div>
        ))}
      </div>

      <ReadinessPanel readiness={readiness} onRefresh={onReadinessRefresh} onStarterSetup={onStarterSetup} />

      <details className="card" open>
        <summary>Working goal</summary>
        <p>
          Build a fast Vercel-style knowledge system: save your profile once, add a video with a default or custom agenda, process it in the worker, then read expandable insights, research resources, and links in the dashboard.
        </p>
        <ol>
          <li>Save your profile lens below. This is the stable part of every extraction.</li>
          <li>Add a video. Use default agenda for normal processing, or custom agenda for one special angle.</li>
          <li>Watch Queue until the processing job is done.</li>
          <li>Open the video and read its Summary, Insights, Resources, and Links.</li>
        </ol>
        <p className="summary">Project plan file: <code>Vercel Remake/GOAL_PLAN.md</code></p>
      </details>

      <details className="card" open>
        <summary>Profile-driven agenda</summary>
        <p>
          This profile is injected into default agenda generation and extraction. Custom agenda requests are combined with this profile, so write the profile as your stable lens and the custom agenda as the video-specific focus.
        </p>
        <form className="settings-form" onSubmit={saveProfile}>
          <div className="field">
            <label htmlFor="profile-name">Name</label>
            <input id="profile-name" value={profileDraft.display_name || ""} onChange={(event) => updateProfileField("display_name", event.target.value)} placeholder="Your name" />
          </div>
          <div className="field">
            <label htmlFor="profile-email">Email</label>
            <input id="profile-email" value={profileDraft.email || ""} onChange={(event) => updateProfileField("email", event.target.value)} placeholder="you@example.com" />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-about">About me / background</label>
            <textarea id="profile-about" value={profileDraft.about_me || ""} onChange={(event) => updateProfileField("about_me", event.target.value)} placeholder="Who you are, what you are building, your current goals..." />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-interests">What insights matter to me</label>
            <textarea id="profile-interests" value={profileDraft.interests || ""} onChange={(event) => updateProfileField("interests", event.target.value)} placeholder="Markets, automation, SaaS, coding, client delivery, content systems, research angles..." />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-style">Insight style</label>
            <textarea id="profile-style" value={profileDraft.insight_style || ""} onChange={(event) => updateProfileField("insight_style", event.target.value)} placeholder="Prefer specific examples, workflows, steps, links, practical playbooks, avoid generic summaries..." />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-known">Things I already know</label>
            <textarea id="profile-known" value={profileDraft.known_topics || ""} onChange={(event) => updateProfileField("known_topics", event.target.value)} placeholder="Topics to skip unless the video gives a new angle..." />
          </div>
          <label className="check-row span-2">
            <input
              type="checkbox"
              checked={profileDraft.personalize_extractions !== false}
              onChange={(event) => updateProfileField("personalize_extractions", event.target.checked)}
            />
            Personalize agendas and insights using this profile
          </label>
          <button className="button" disabled={profileSaving}>{profileSaving ? "Saving..." : "Save profile"}</button>
        </form>
        {profileMessage ? <p className="notice">{profileMessage}</p> : null}
        {profilePrompt ? (
          <details className="card nested-card">
            <summary>Profile prompt preview</summary>
            <pre>{profilePrompt}</pre>
          </details>
        ) : (
          <p className="summary">No profile lens is active yet. Add interests and an insight style to make default agendas more personal.</p>
        )}
      </details>

      <details className="card" open>
        <summary>Playlist agenda profiles</summary>
        <p>
          Playlist focus is added to the default agenda when a video belongs to that playlist. Use this for recurring streams such as AI tools, podcasts, or client research.
        </p>
        <div className="playlist-editor-list">
          {playlists.length ? (
            playlists.map((playlist) => (
              <PlaylistEditor playlist={playlist} onSave={onPlaylistSaved} key={playlist.playlist_id} />
            ))
          ) : (
            <p className="summary">No playlists found yet. Sync or add a playlist in the existing database first.</p>
          )}
        </div>
      </details>

      <details className="card" open>
        <summary>Provider API keys</summary>
        <p>
          Paste only the keys you want to add or replace. Blank fields keep the current key. Stored keys are used by the API and worker, but are never shown back in the dashboard.
        </p>
        <p className="summary">Runtime key file: <code>Vercel Remake/runtime/provider_keys.json</code></p>
        <pre>{`YOUTUBE_API_KEY=your_new_youtube_key
GEMINI_API_KEY=your_gemini_key
ANTHROPIC_API_KEY=your_anthropic_key
GROQ_API_KEY=your_groq_key
TAVILY_API_KEY=your_tavily_key`}</pre>
        <form className="settings-form" onSubmit={saveKeys}>
          <div className="field span-2">
            <label htmlFor="bulk-provider-keys">Paste .env key block</label>
            <textarea
              id="bulk-provider-keys"
              value={bulkKeys}
              onChange={(event) => setBulkKeys(event.target.value)}
              rows={6}
              spellCheck={false}
              placeholder="YOUTUBE_API_KEY=..."
            />
            <small>You can paste one line or the full block. JSON also works, for example {`{"youtube":"..."}`}.</small>
          </div>
          <div className="field">
            <label htmlFor="youtube-key">YouTube API key</label>
            <input id="youtube-key" name="youtube" type="password" autoComplete="off" placeholder="Raw key or YOUTUBE_API_KEY=..." />
          </div>
          <div className="field">
            <label htmlFor="gemini-key">Gemini API key</label>
            <input id="gemini-key" name="gemini" type="password" autoComplete="off" placeholder="Paste new Gemini key" />
          </div>
          <div className="field">
            <label htmlFor="anthropic-key">Anthropic API key</label>
            <input id="anthropic-key" name="anthropic" type="password" autoComplete="off" placeholder="Paste new Anthropic key" />
          </div>
          <div className="field">
            <label htmlFor="groq-key">Groq API key</label>
            <input id="groq-key" name="groq" type="password" autoComplete="off" placeholder="Paste new Groq key" />
          </div>
          <div className="field">
            <label htmlFor="tavily-key">Tavily API key</label>
            <input id="tavily-key" name="tavily" type="password" autoComplete="off" placeholder="Paste new Tavily key" />
          </div>
          <button className="button" disabled={saving}>{saving ? "Saving..." : "Save keys"}</button>
        </form>
        {message ? <p className="notice">{message}</p> : null}
      </details>

      <details className="card">
        <summary>Deployment variables</summary>
        <p>For hosted production, set stable keys as environment variables on the API/worker host. The dashboard key form is best for this remake runtime and local testing.</p>
        <pre>
{`DATABASE_URL=postgresql://...
NEXT_PUBLIC_API_BASE_URL=https://your-api-host
APP_ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
YOUTUBE_API_KEY=...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
GROQ_API_KEY=...
TAVILY_API_KEY=...`}
        </pre>
      </details>
    </section>
  );
}

function ReadinessPanel({
  readiness,
  onRefresh,
  onStarterSetup
}: {
  readiness: Readiness | null;
  onRefresh: () => Promise<Readiness>;
  onStarterSetup: (overwrite?: boolean) => Promise<{ profile: Profile; prompt_preview: string; playlists: Playlist[]; readiness: Readiness }>;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [message, setMessage] = useState("");

  async function refresh() {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  }

  async function applyStarter() {
    setApplying(true);
    setMessage("");
    try {
      const result = await onStarterSetup(false);
      setMessage(result.readiness.ok ? "Starter setup applied. The system is ready for a real processing test." : "Starter setup applied. Check the remaining readiness items below.");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "Could not apply starter setup.");
    } finally {
      setApplying(false);
    }
  }

  return (
    <section className="readiness-card">
      <div className="section-heading">
        <div>
          <p className="reader-label">System readiness</p>
          <h2>{readiness?.ok ? "Ready for normal processing" : "Needs setup before serious processing"}</h2>
        </div>
        <div className="main-actions">
          <button className="ghost" onClick={() => void refresh()} disabled={refreshing || applying}>
            {refreshing ? "Checking..." : "Refresh"}
          </button>
          <button className="button" onClick={() => void applyStarter()} disabled={applying}>
            {applying ? "Applying..." : "Apply starter setup"}
          </button>
        </div>
      </div>

      <div className="readiness-grid">
        {(readiness?.checks || []).map((check) => (
          <div className={check.ok ? "ready" : "needs-work"} key={check.id}>
            <strong>{check.ok ? "✓" : "!"} {check.label}</strong>
            <span>{check.detail}</span>
          </div>
        ))}
      </div>

      {readiness?.next_actions.length ? (
        <div className="reader-block compact">
          <p className="reader-label">Next setup steps</p>
          <ul>
            {readiness.next_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {message ? <p className="notice">{message}</p> : null}
    </section>
  );
}

function PlaylistEditor({
  playlist,
  onSave
}: {
  playlist: Playlist;
  onSave: (playlistId: string, updates: Partial<Pick<Playlist, "name" | "description" | "kind" | "extraction_focus" | "enabled">>) => Promise<Playlist>;
}) {
  const [draft, setDraft] = useState(playlist);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setDraft(playlist);
  }, [playlist]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const saved = await onSave(playlist.playlist_id, {
        name: draft.name || "",
        description: draft.description || "",
        kind: draft.kind,
        extraction_focus: draft.extraction_focus || "",
        enabled: draft.enabled !== false
      });
      setDraft(saved);
      setMessage("Playlist focus saved. New default agenda jobs will use it.");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "Could not save playlist focus.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="playlist-editor" open>
      <summary>
        <span>{draft.name || draft.playlist_id}</span>
        <small>{draft.kind} · {draft.enabled === false ? "disabled" : "enabled"}</small>
      </summary>
      <form className="settings-form" onSubmit={submit}>
        <div className="field">
          <label htmlFor={`${playlist.playlist_id}-name`}>Name</label>
          <input id={`${playlist.playlist_id}-name`} value={draft.name || ""} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
        </div>
        <div className="field">
          <label htmlFor={`${playlist.playlist_id}-kind`}>Kind</label>
          <select id={`${playlist.playlist_id}-kind`} value={draft.kind} onChange={(event) => setDraft((current) => ({ ...current, kind: event.target.value }))}>
            <option value="general">General</option>
            <option value="podcast">Podcast</option>
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor={`${playlist.playlist_id}-desc`}>Description</label>
          <textarea id={`${playlist.playlist_id}-desc`} value={draft.description || ""} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} placeholder="What this playlist is for..." />
        </div>
        <div className="field span-2">
          <label htmlFor={`${playlist.playlist_id}-focus`}>Extraction focus</label>
          <textarea id={`${playlist.playlist_id}-focus`} value={draft.extraction_focus || ""} onChange={(event) => setDraft((current) => ({ ...current, extraction_focus: event.target.value }))} placeholder="For this playlist, prioritize tools, workflows, pricing, deployment steps, examples, links, and ideas I can reuse..." />
        </div>
        <label className="check-row span-2">
          <input
            type="checkbox"
            checked={draft.enabled !== false}
            onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
          />
          Include this playlist in sync
        </label>
        <button className="button" disabled={saving}>{saving ? "Saving..." : "Save playlist focus"}</button>
      </form>
      {message ? <p className="notice">{message}</p> : null}
    </details>
  );
}

function iconLibrary() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 5.5h14M5 12h14M5 18.5h9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function iconPlus() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function iconQueue() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 7h12M6 12h8M6 17h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M17 14l2 2-2 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function iconSettings() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" stroke="currentColor" strokeWidth="1.7" />
      <path d="M19 12a7 7 0 0 0-.1-1.1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.9-1.1L14.3 3h-4.6l-.4 2.9A7 7 0 0 0 7.5 7l-2.4-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.1l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.9 1.1l.4 2.9h4.6l.4-2.9a7 7 0 0 0 1.9-1.1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1.1Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

function iconRefresh() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function iconSearch() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.7" />
      <path d="m16 16 4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function iconPlay() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5.8v12.4c0 .8.9 1.3 1.6.8l9.4-6.2a1 1 0 0 0 0-1.6L9.6 5c-.7-.5-1.6 0-1.6.8Z" />
    </svg>
  );
}

function iconChevron() {
  return (
    <svg className="chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="m9 6 6 6-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
