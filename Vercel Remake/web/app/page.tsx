"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type Health, type Job, type Video } from "../lib/api";
import { videoInsights, videoResearch, videoSummary } from "../lib/insights";

type Page = "library" | "add" | "queue" | "settings";

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

export default function Home() {
  const [page, setPage] = useState<Page>("library");
  const [videos, setVideos] = useState<Video[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<Video | null>(null);
  const [selectedJobs, setSelectedJobs] = useState<Job[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [query, setQuery] = useState("");
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
    const result = await api.jobs();
    setError("");
    setJobs(result.items);
  }

  useEffect(() => {
    async function boot() {
      try {
        const [healthResult, videosResult, jobsResult] = await Promise.all([
          api.health(),
          api.videos(),
          api.jobs()
        ]);
        setError("");
        setHealth(healthResult);
        setVideos(videosResult.items);
        setJobs(jobsResult.items);
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return videos;
    return videos.filter((video) =>
      [video.title, video.channel_name, video.status].some((value) =>
        (value || "").toLowerCase().includes(q)
      )
    );
  }, [videos, query]);

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
      const result = await api.ingest(url, kind);
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
      await api.process(selected.video_id);
      setNotice("Queued for processing.");
      await loadVideo(selected.video_id);
      await loadJobs();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not queue this video.");
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
            <div className="context-title">
              <span className="caps">Library ({videos.length})</span>
              <strong>InsightEngine</strong>
            </div>
            <button className="ghost" onClick={() => void loadVideos()}>
              Refresh
            </button>
          </div>

          <div className="context-tools">
            <div className="field">
              <label htmlFor="filter">Search library</label>
              <input
                id="filter"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Title, channel, status..."
              />
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
                  <span className={statusClass(video.status)}>{video.status}</span>
                </span>
                <span className="row-body">
                  <strong>{video.title || video.video_id}</strong>
                  <span>{video.channel_name || "Unknown channel"}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="main">
          <header className="main-head">
            <nav className="top-tabs" aria-label="Section tabs">
              {nav.map((item) => (
                <button
                  key={item.page}
                  className={page === item.page ? "active" : ""}
                  onClick={() => setPage(item.page)}
                >
                  {item.label}
                </button>
              ))}
            </nav>
            <div className="main-actions">
              <span className="pill done">{doneCount} done</span>
              <span className="pill queued">{activeJobs} active jobs</span>
              <button className="button" onClick={() => setPage("add")}>
                + Add video
              </button>
            </div>
          </header>

          <div className="content">
            {notice ? <p className="notice">{notice}</p> : null}
            {error ? <p className="notice error">{error}</p> : null}

            {page === "library" ? (
              <VideoDetail
                video={displayedVideo}
                jobs={selectedJobs}
                loading={loading}
                onProcess={processSelected}
                onTranscript={submitTranscript}
              />
            ) : null}

            {page === "add" ? (
              <AddPanel loading={loading} onSubmit={submitAdd} />
            ) : null}

            {page === "queue" ? (
              <QueuePanel jobs={jobs} onRefresh={loadJobs} />
            ) : null}

            {page === "settings" ? (
              <SettingsPanel health={health} />
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
  loading,
  onProcess,
  onTranscript
}: {
  video: Video | null;
  jobs: Job[];
  loading: boolean;
  onProcess: () => Promise<void>;
  onTranscript: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  if (!video) {
    return (
      <section>
        <h1 className="detail-title">No video selected</h1>
        <p className="summary">Add or choose a video to read its notes.</p>
      </section>
    );
  }

  const summary = videoSummary(video);
  const insights = videoInsights(video);
  const research = videoResearch(video);
  const failed = video.status === "failed";

  return (
    <section>
      <p className="caps">Video detail</p>
      <h1 className="detail-title">{video.title || video.video_id}</h1>
      <div className="meta">
        <span className={statusClass(video.status)}>{video.status}</span>
        <span className="pill">{video.channel_name || "Unknown channel"}</span>
        <span className="pill">{video.transcript_source || "No transcript source"}</span>
      </div>
      <div className="meta">
        <a className="ghost" href={video.url} target="_blank" rel="noreferrer">
          Watch
        </a>
        <button className="ghost" onClick={() => void onProcess()} disabled={loading}>
          Queue processing
        </button>
      </div>

      {failed ? (
        <div className="notice error">
          <strong>Processing failed.</strong>
          <br />
          {video.error_message || "The worker recorded a failure."}
        </div>
      ) : null}

      <section className="reader-block">
        <p className="reader-label">Summary</p>
        {summary ? <p className="summary">{summary}</p> : <p className="summary">No extracted notes yet.</p>}
      </section>

      {insights.length ? (
        <section className="insights-stack" aria-label="Insights">
          <div className="section-heading">
            <p className="reader-label">Insights</p>
            <span>{insights.length} section{insights.length === 1 ? "" : "s"}</span>
          </div>
          {insights.map((insight, index) => (
            <details className="insight-section" key={`${insight.title}-${index}`} open={index === 0}>
              <summary>
                <span className="section-number">{String(index + 1).padStart(2, "0")}</span>
                <span className="section-summary-copy">
                  <span>{insight.title}</span>
                  <small>{insight.points.length} point{insight.points.length === 1 ? "" : "s"}</small>
                </span>
              </summary>
              <div className="section-copy">
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
        </section>
      ) : null}

      {research.resources.length || research.links.length ? (
        <section className="research-panel">
          <div className="section-heading">
            <p className="reader-label">Research</p>
            <span>{research.resources.length} resources · {research.links.length} links</span>
          </div>

          {research.resources.length ? (
            <details className="card" open>
              <summary>Research insights and resources</summary>
              <div className="resource-list">
                {research.resources.map((resource, index) => (
                  <article className="resource-item" key={`${resource.name}-${index}`}>
                    <div>
                      <strong>{resource.name}</strong>
                      <span>{resource.type} · {resource.source || "insight"}</span>
                    </div>
                    {resource.detail ? <p>{resource.detail}</p> : null}
                    {resource.url ? (
                      <a href={resource.url} target="_blank" rel="noreferrer">
                        Open source
                      </a>
                    ) : null}
                  </article>
                ))}
              </div>
            </details>
          ) : null}

          {research.links.length ? (
            <details className="card">
              <summary>Links from video, description, and research</summary>
              <div className="link-list">
                {research.links.map((link) => (
                  <a href={link.url} target="_blank" rel="noreferrer" key={link.url}>
                    <span>{link.label}</span>
                    <small>{link.source}</small>
                  </a>
                ))}
              </div>
            </details>
          ) : null}
        </section>
      ) : null}

      <div className="support-grid">
        <details className="card">
          <summary>Use a transcript instead</summary>
          <p>
            Paste the YouTube transcript when audio download is blocked. Saving it queues the
            worker without relying on YouTube audio retrieval.
          </p>
          <form className="form" onSubmit={onTranscript}>
            <textarea name="transcript" required minLength={100} placeholder="Paste transcript text..." />
            <button className="button" disabled={loading}>
              Save transcript and process
            </button>
          </form>
        </details>

        <details className="card">
          <summary>Recent jobs</summary>
          {jobs.length ? (
            jobs.map((job) => (
              <p key={job.id}>
                {job.status} · {job.kind} · {job.attempts} attempt{job.attempts === 1 ? "" : "s"}
              </p>
            ))
          ) : (
            <p>No jobs for this video yet.</p>
          )}
        </details>
      </div>
    </section>
  );
}

function AddPanel({
  loading,
  onSubmit
}: {
  loading: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  return (
    <section>
      <p className="caps">New source</p>
      <h1 className="detail-title">Add a video</h1>
      <p className="summary">
        This creates a queued job. The worker processes the video separately, so the dashboard stays fast.
      </p>
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
        <button className="button" disabled={loading}>
          {loading ? "Adding..." : "Add and queue"}
        </button>
      </form>
    </section>
  );
}

function QueuePanel({ jobs, onRefresh }: { jobs: Job[]; onRefresh: () => Promise<void> }) {
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
      <div className="queue-list">
        {jobs.length ? (
          jobs.map((job) => (
            <div className="job" key={job.id}>
              <span className={statusClass(job.status)}>{job.status}</span>
              <span>{job.video_id}</span>
              <span>{job.attempts} attempt{job.attempts === 1 ? "" : "s"}</span>
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

function SettingsPanel({ health }: { health: Health | null }) {
  const [services, setServices] = useState<Record<string, boolean>>(health?.services || {});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setServices(health?.services || {});
  }, [health]);

  async function saveKeys(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    const form = new FormData(event.currentTarget);
    const keys: Record<string, string> = {};
    for (const name of ["youtube", "gemini", "anthropic", "groq", "tavily"]) {
      const value = String(form.get(name) || "").trim();
      if (value) keys[name] = value;
    }
    if (!Object.keys(keys).length) {
      setMessage("Paste at least one new key to save.");
      return;
    }
    setSaving(true);
    try {
      const result = await api.saveProviderKeys(keys);
      setServices(result.services);
      setMessage("Saved. New jobs will use the updated provider keys.");
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

      <details className="card" open>
        <summary>Provider API keys</summary>
        <p>
          Paste only the keys you want to add or replace. Blank fields keep the current key. Stored keys are used by the API and worker, but are never shown back in the dashboard.
        </p>
        <form className="settings-form" onSubmit={saveKeys}>
          <div className="field">
            <label htmlFor="youtube-key">YouTube API key</label>
            <input id="youtube-key" name="youtube" type="password" autoComplete="off" placeholder="Paste new YouTube key" />
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
