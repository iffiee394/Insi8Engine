"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type Health, type Job, type Playlist, type Profile, type Readiness, type UsageReport, type Video, type WorkerStatus } from "../lib/api";
import { videoInsights, videoResearch, videoSummary } from "../lib/insights";

type Page = "library" | "add" | "queue" | "usage" | "settings";

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
  { page: "usage", label: "Usage", icon: iconUsage() },
  { page: "settings", label: "Settings", icon: iconSettings() }
];

function thumbnailUrl(video: Video): string {
  return video.thumbnail_url || `https://i.ytimg.com/vi/${video.video_id}/mqdefault.jpg`;
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
  const [usage, setUsage] = useState<UsageReport | null>(null);

  async function loadUsage() {
    try {
      setUsage(await api.usage());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not load usage.");
    }
  }

  useEffect(() => {
    if (page !== "usage") return;
    void loadUsage();
    const timer = window.setInterval(() => void loadUsage(), 15000);
    return () => window.clearInterval(timer);
  }, [page]);
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
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
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
      formElement.reset();
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
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
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
      formElement.reset();
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
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      await api.transcript(selected.video_id, String(form.get("transcript") || ""));
      setNotice("Transcript saved and processing queued.");
      await loadVideo(selected.video_id);
      await loadJobs();
      formElement.reset();
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

  async function reloadPlaylists() {
    const [result, nextReadiness] = await Promise.all([api.playlists(), api.readiness()]);
    setPlaylists(result.items);
    setReadiness(nextReadiness);
    await loadJobs();
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
              <AddPanel loading={loading} playlists={playlists} profile={profile} onSubmit={submitAdd} />
            ) : null}

            {page === "queue" ? (
              <QueuePanel jobs={jobs} workerStatus={workerStatus} loading={loading} onRefresh={loadJobs} onSync={syncPlaylists} />
            ) : null}

            {page === "usage" ? <UsagePanel usage={usage} onRefresh={loadUsage} /> : null}

            {page === "settings" ? (
              <SettingsPanel
                health={health}
                workerStatus={workerStatus}
                readiness={readiness}
                profile={profile}
                profilePrompt={profilePrompt}
                playlists={playlists}
                onPlaylistSaved={savePlaylistFocus}
                onPlaylistsChanged={reloadPlaylists}
                onOpenUsage={() => setPage("usage")}
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
  const [toolsOpen, setToolsOpen] = useState(() => video?.status === "failed");
  const [toolTab, setToolTab] = useState<"default" | "agenda" | "transcript">(() =>
    video?.status === "failed" && /download|forbidden|403|no transcript/i.test(video.error_message || "") ? "transcript" : "default"
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
  const retryScheduled = Boolean(
    activeJob?.status === "queued" && activeJob.run_after && new Date(activeJob.run_after).getTime() > Date.now()
  );
  const liveLabel = !activeJob ? video.status : retryScheduled ? "retry scheduled" : activeJob.status === "running" ? "processing" : "queued";
  const lastJob = jobs[0];

  return (
    <article className="video">
      <div className="ambient" aria-hidden="true">
        <img src={thumbnailUrl(video)} alt="" />
      </div>

      <header className="video-head">
        <p className="eyebrow">
          <span className="eyebrow-status">
            <i className={`dot ${activeJob && !retryScheduled ? "processing" : retryScheduled ? "pending" : video.status}`} />
            {liveLabel}
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

      {activeJob?.status === "running" && activeJob.progress ? (
        <p className="notice live">
          <strong>Working on it.</strong> {activeJob.progress}
        </p>
      ) : failed ? (
        <p className={`notice ${retryScheduled ? "" : "error"}`}>
          <strong>{retryScheduled ? `Couldn't finish yet — retrying ${relativeTime(activeJob?.run_after)}.` : "Extraction failed."}</strong>{" "}
          {video.error_message || "The worker recorded a failure."}
        </p>
      ) : null}

      {toolsOpen ? (
        <section className="tools" aria-label="Reprocess this video">
          <div className="tools-head">
            <div className="segmented" role="tablist" aria-label="Reprocess method">
              <button role="tab" aria-selected={toolTab === "default"} className={toolTab === "default" ? "active" : ""} onClick={() => setToolTab("default")}>
                Default agenda
              </button>
              <button role="tab" aria-selected={toolTab === "agenda"} className={toolTab === "agenda" ? "active" : ""} onClick={() => setToolTab("agenda")}>
                Custom agenda
              </button>
              <button role="tab" aria-selected={toolTab === "transcript"} className={toolTab === "transcript" ? "active" : ""} onClick={() => setToolTab("transcript")}>
                Paste transcript
              </button>
            </div>
          </div>

          {toolTab === "default" ? (
            <div className="form">
              <p className="tool-copy">
                Extracts insights using your profile and this playlist&apos;s focus. This is what normally runs for new videos.
              </p>
              <button className="button" onClick={() => void onProcess()} disabled={loading}>
                Rerun with default agenda
              </button>
            </div>
          ) : toolTab === "agenda" ? (
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
  onSubmit
}: {
  loading: boolean;
  playlists: Playlist[];
  profile: Profile;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const [agendaMode, setAgendaMode] = useState<"default" | "custom">("default");
  const [playlistId, setPlaylistId] = useState("");
  const [kind, setKind] = useState("video");
  const hasProfile = profileHasText(profile);

  function choosePlaylist(id: string) {
    setPlaylistId(id);
    const playlist = playlists.find((item) => item.playlist_id === id);
    if (playlist) setKind(playlist.kind === "podcast" ? "podcast" : "video");
  }

  return (
    <section className="page">
      <h1 className="detail-title">Add a video</h1>
      <p className="lede small">
        Paste a YouTube link. The worker gets the transcript and writes insights through your profile, usually within a
        few minutes. Watch it in Queue.
      </p>
      {!hasProfile ? (
        <p className="notice">Your profile is empty, so insights won&apos;t be personal yet. Fill it in under Settings first.</p>
      ) : null}

      <form className="form add-form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="url">YouTube link</label>
          <input id="url" name="url" required placeholder="https://www.youtube.com/watch?v=…" />
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="playlistId">Playlist</label>
            <select id="playlistId" name="playlistId" value={playlistId} onChange={(event) => choosePlaylist(event.target.value)}>
              <option value="">None — just this video</option>
              {playlists.map((playlist) => (
                <option value={playlist.playlist_id} key={playlist.playlist_id}>
                  {playlist.name || playlist.playlist_id}
                </option>
              ))}
            </select>
            <small>Its focus is added to your profile when writing insights.</small>
          </div>
          <div className="field">
            <label htmlFor="kind">Type</label>
            <select id="kind" name="kind" value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="video">Video</option>
              <option value="podcast">Podcast</option>
            </select>
            <small>Podcasts get guest and topic research.</small>
          </div>
        </div>

        <div className="field">
          <span className="field-label">What to look for</span>
          <input type="hidden" name="agendaMode" value={agendaMode} />
          <div className="segmented" role="tablist" aria-label="Agenda">
            <button type="button" role="tab" aria-selected={agendaMode === "default"} className={agendaMode === "default" ? "active" : ""} onClick={() => setAgendaMode("default")}>
              Default agenda
            </button>
            <button type="button" role="tab" aria-selected={agendaMode === "custom"} className={agendaMode === "custom" ? "active" : ""} onClick={() => setAgendaMode("custom")}>
              Custom agenda
            </button>
          </div>
          {agendaMode === "default" ? (
            <small>Uses your profile and the playlist&apos;s focus. Right for most videos.</small>
          ) : (
            <textarea id="agenda" name="agenda" required minLength={10} placeholder={CUSTOM_AGENDA_EXAMPLE} aria-label="Custom agenda" />
          )}
        </div>

        <button className="button" disabled={loading}>{loading ? "Adding…" : "Add video"}</button>
      </form>
    </section>
  );
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  const abs = Math.abs(minutes);
  const span = abs < 1 ? "under a minute" : abs < 60 ? `${abs} min` : abs < 48 * 60 ? `${Math.round(abs / 60)} h` : `${Math.round(abs / 1440)} days`;
  return minutes >= 0 ? `in ${span}` : `${span} ago`;
}

function jobState(job: Job): { label: string; tone: string } {
  if (job.status === "queued" && job.run_after && new Date(job.run_after).getTime() > Date.now()) {
    return { label: "retry scheduled", tone: "queued" };
  }
  return { label: job.status, tone: job.status };
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
  const online = Boolean(workerStatus?.ok);
  return (
    <section className="page">
      <div className="page-head">
        <h1 className="detail-title">Queue</h1>
        <button className="ghost" onClick={() => void onRefresh()}>
          {iconRefresh()} Refresh
        </button>
      </div>

      <div className="worker-line">
        <i className={`dot ${online ? (newestWorker?.status === "running" ? "processing" : "done") : "failed"}`} />
        <span>
          {online
            ? newestWorker?.status === "running"
              ? `Worker busy — ${newestWorker.note || "processing"}`
              : "Worker online and waiting for jobs"
            : "Worker offline — queued videos will wait until it's back"}
        </span>
      </div>

      <p className="lede small">
        When a step fails, the next one takes over: captions, then Gemini reading the video, then the audio;
        Gemini key 1, 2, 3… and Claude last. If a whole job still fails it retries by itself after 2 min, 10 min,
        1 h, 6 h and 24 h, then every 12 h. Every error below is the real reason from that step.
      </p>

      <div className="index queue-index">
        {jobs.length ? (
          jobs.map((job, index) => {
            const resolved =
              job.status === "failed" &&
              jobs.slice(0, index).some((later) => later.video_id === job.video_id && later.status === "done");
            const state = resolved ? { label: "resolved", tone: "" } : jobState(job);
            const title = job.kind === "sync_playlists" ? "Playlist sync" : job.video_title || job.video_id;
            return (
              <div className="queue-row" key={job.id}>
                <span className={`pill ${state.tone}`}>{state.label}</span>
                <div className="queue-body">
                  <strong>{title}</strong>
                  {job.status === "running" && job.progress ? <span className="queue-step">{job.progress}</span> : null}
                  {state.label === "retry scheduled" ? (
                    <span className="queue-step">Next try {relativeTime(job.run_after)}</span>
                  ) : null}
                  {job.error && job.status !== "done" && !resolved ? <span className="queue-error">{job.error}</span> : null}
                  {resolved ? <span className="queue-step muted">A later run finished this video.</span> : null}
                </div>
                <span className="queue-meta">
                  {job.kind === "sync_playlists" ? "sync" : "video"} · try {job.attempts || 0}/{job.max_attempts || 6}
                  <br />
                  {relativeTime(job.updated_at)}
                </span>
              </div>
            );
          })
        ) : (
          <p className="summary">No jobs yet. Add a video or sync your playlists.</p>
        )}
      </div>

      <details className="card">
        <summary>Sync playlists now</summary>
        <p>
          Pulls new videos from your enabled playlists and processes the oldest waiting ones. This also runs by
          itself every morning. Use 0 to only add the videos without processing them.
        </p>
        <form className="settings-form" onSubmit={onSync}>
          <div className="field">
            <label htmlFor="maxProcess">Videos to process now</label>
            <input id="maxProcess" name="maxProcess" type="number" min="0" max="50" defaultValue="3" />
          </div>
          <button className="button" disabled={loading}>{loading ? "Queueing..." : "Sync playlists"}</button>
        </form>
      </details>
    </section>
  );
}

function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}k`;
  return String(tokens);
}

function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? time : `${date.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

function UsagePanel({ usage, onRefresh }: { usage: UsageReport | null; onRefresh: () => Promise<void> }) {
  const chain = usage?.chain || [];
  const gemini = chain.filter((item) => item.slot.startsWith("gemini_"));
  const claude = chain.find((item) => item.slot === "anthropic");
  const answering = chain.find((item) => item.status === "ready" || item.status === "unused");
  const nextBack = chain
    .filter((item) => item.status === "resting" && item.until)
    .sort((a, b) => String(a.until).localeCompare(String(b.until)))[0];

  let headline = "Waiting for the worker to report its keys.";
  if (answering && answering.slot !== "anthropic") {
    headline = `${answering.label} (${answering.role.toLowerCase()}) is answering.`;
  } else if (answering) {
    headline = "Every Gemini key is resting, so Claude is answering.";
  } else if (chain.length) {
    headline = `Every key is unavailable. The first one comes back at ${clockTime(nextBack?.until)}; jobs wait and retry then.`;
  }

  return (
    <section className="page">
      <div className="page-head">
        <h1 className="detail-title">Usage</h1>
        <button className="ghost" onClick={() => void onRefresh()}>
          {iconRefresh()} Refresh
        </button>
      </div>

      <div className="usage-now">
        <p className="eyebrow">Right now</p>
        <p className="usage-headline">{headline}</p>
        <p className="usage-claude">
          Claude (paid) today: <strong>{claude?.calls_today ?? 0} calls</strong>
          {claude && claude.calls_today === 0 ? " — your credits are untouched." : "."}
        </p>
      </div>

      <section className="block">
        <h2 className="eyebrow">Order of use</h2>
        {chain.length ? (
          <ol className="index usage-chain">
            {chain.map((item) => {
              const isClaude = item.slot === "anthropic";
              const inUse = answering?.slot === item.slot;
              const tone = item.status === "rejected" ? "failed" : item.status === "resting" ? "pending" : "done";
              let state = inUse ? "In use now" : isClaude ? "Standby — only if every Gemini key is resting" : "Ready as backup";
              if (item.status === "resting") state = `Resting until ${clockTime(item.until)} — ${item.detail}`;
              if (item.status === "rejected") state = `Not working — ${item.detail}. Replace this key.`;
              return (
                <li className={`usage-row ${inUse ? "current" : ""}`} key={item.slot}>
                  <span className="usage-pos">{item.position}</span>
                  <div className="usage-body">
                    <strong>
                      {item.label}
                      <span className={`usage-tag ${isClaude ? "paid" : ""}`}>{item.role}</span>
                      <span className="usage-mask">key {item.masked}</span>
                    </strong>
                    <span className="usage-state">
                      <i className={`dot ${tone}`} />
                      {state}
                    </span>
                  </div>
                  <span className="usage-count">
                    {item.calls_today} call{item.calls_today === 1 ? "" : "s"} today
                    <br />≈ {formatTokens(item.tokens_today)} tokens
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="summary">The worker hasn&apos;t reported its keys yet. It does this each time it starts.</p>
        )}
      </section>

      <dl className="usage-legend">
        <div><dt>In use now</dt><dd>The key new AI steps go to first.</dd></div>
        <div><dt>Ready as backup</dt><dd>Takes over when the keys above it are resting.</dd></div>
        <div><dt>Resting</dt><dd>Used up its free daily quota (or is briefly overloaded). It comes back by itself at the time shown — Google resets free quotas at midnight Pacific.</dd></div>
        <div><dt>Not working</dt><dd>Google rejected the key. Create a new one and replace it.</dd></div>
      </dl>

      {usage?.days.length ? (
        <section className="block">
          <h2 className="eyebrow">Calls per day</h2>
          <table className="usage-table">
            <thead>
              <tr>
                <th>Day</th>
                <th>Gemini ({gemini.length} keys)</th>
                <th>Claude</th>
                <th>Groq</th>
              </tr>
            </thead>
            <tbody>
              {usage.days.map((day) => (
                <tr key={day.date}>
                  <td>{day.date}</td>
                  <td>{day.gemini}</td>
                  <td className={day.claude ? "warn" : ""}>{day.claude}</td>
                  <td>{day.groq}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="usage-note">
            Groq writes the short agenda prompts ({usage.groq_today.calls} today). Days follow Pacific time, matching
            Google&apos;s quota reset.
          </p>
        </section>
      ) : null}
    </section>
  );
}

function iconUsage() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 19V11M12 19V5M19 19v-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

type PlaylistUpdate = Partial<Pick<Playlist, "name" | "description" | "kind" | "extraction_focus" | "enabled">>;

function SettingsPanel({
  health,
  workerStatus,
  readiness,
  profile,
  profilePrompt,
  playlists,
  onPlaylistSaved,
  onPlaylistsChanged,
  onProfileSaved,
  onOpenUsage
}: {
  health: Health | null;
  workerStatus: WorkerStatus | null;
  readiness: Readiness | null;
  profile: Profile;
  profilePrompt: string;
  playlists: Playlist[];
  onPlaylistSaved: (playlistId: string, updates: PlaylistUpdate) => Promise<Playlist>;
  onPlaylistsChanged: () => Promise<void>;
  onProfileSaved: (profile: Profile, prompt: string) => void;
  onOpenUsage: () => void;
}) {
  const [draft, setDraft] = useState<Profile>(profile);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setDraft(profile);
  }, [profile]);

  function update<K extends keyof Profile>(key: K, value: Profile[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const result = await api.saveProfile(draft);
      onProfileSaved(result.profile, result.prompt_preview);
      setMessage("Saved. New videos will be read through this profile.");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "Could not save the profile.");
    } finally {
      setSaving(false);
    }
  }

  const issues = (readiness?.checks || []).filter((check) => !check.ok);
  const workerOnline = Boolean(workerStatus?.ok);

  return (
    <section className="page">
      <h1 className="detail-title">Settings</h1>

      <section className="block settings-block">
        <h2 className="section-title">Your profile</h2>
        <p className="lede small">Every video is read through this. It decides which insights count as important to you.</p>
        <form className="settings-form" onSubmit={saveProfile}>
          <div className="field">
            <label htmlFor="profile-name">Name</label>
            <input id="profile-name" value={draft.display_name || ""} onChange={(event) => update("display_name", event.target.value)} placeholder="Your name" />
          </div>
          <div className="field">
            <label htmlFor="profile-email">Email</label>
            <input id="profile-email" type="email" value={draft.email || ""} onChange={(event) => update("email", event.target.value)} placeholder="you@example.com" />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-about">About you</label>
            <textarea id="profile-about" value={draft.about_me || ""} onChange={(event) => update("about_me", event.target.value)} placeholder="Who you are, what you're building, what you're working towards…" />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-interests">Insights that matter to you</label>
            <textarea id="profile-interests" value={draft.interests || ""} onChange={(event) => update("interests", event.target.value)} placeholder="Tools and workflows I can use, pricing, client delivery, automation ideas…" />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-style">How insights should be written</label>
            <textarea id="profile-style" value={draft.insight_style || ""} onChange={(event) => update("insight_style", event.target.value)} placeholder="Specific and practical: steps, numbers, links, examples. No generic summaries." />
          </div>
          <div className="field span-2">
            <label htmlFor="profile-known">What you already know</label>
            <textarea id="profile-known" value={draft.known_topics || ""} onChange={(event) => update("known_topics", event.target.value)} placeholder="Topics to skip unless the video adds something new…" />
          </div>
          <label className="check-row span-2">
            <input
              type="checkbox"
              checked={draft.personalize_extractions !== false}
              onChange={(event) => update("personalize_extractions", event.target.checked)}
            />
            Use this profile when writing insights
          </label>
          <div className="form-actions span-2">
            <button className="button" disabled={saving}>{saving ? "Saving…" : "Save profile"}</button>
            {message ? <span className="form-message">{message}</span> : null}
          </div>
        </form>
        {profilePrompt ? (
          <details className="card">
            <summary>See exactly what the AI is told about you</summary>
            <pre>{profilePrompt}</pre>
          </details>
        ) : null}
      </section>

      <section className="block settings-block">
        <h2 className="section-title">Playlists</h2>
        <p className="lede small">
          New videos in these YouTube playlists are pulled in every morning and processed automatically. Each playlist&apos;s
          focus is added to your profile for its videos.
        </p>
        <div className="index">
          {playlists.map((playlist) => (
            <PlaylistEditor playlist={playlist} onSave={onPlaylistSaved} key={playlist.playlist_id} />
          ))}
        </div>
        <AddPlaylistForm onAdded={onPlaylistsChanged} />
      </section>

      <section className="block settings-block">
        <h2 className="section-title">System</h2>
        <ul className="system-list">
          <li><i className={`dot ${health?.ok ? "done" : "failed"}`} />API {health?.ok ? "connected" : `not reachable${health?.error ? ` — ${health.error}` : ""}`}</li>
          <li><i className={`dot ${workerOnline ? "done" : "failed"}`} />Worker {workerOnline ? "online" : "offline — new videos wait until it's back"}</li>
          <li><i className={`dot ${health?.services?.youtube ? "done" : "failed"}`} />YouTube access {health?.services?.youtube ? "set up" : "missing — playlist sync can't run"}</li>
          <li>
            <i className="dot done" />AI keys live on the worker —{" "}
            <button className="text-button" onClick={onOpenUsage}>see Usage</button> for which one is in use
          </li>
          {issues.map((check) => (
            <li key={check.id}><i className="dot pending" />{check.label}: {check.detail}</li>
          ))}
        </ul>
      </section>
    </section>
  );
}

function AddPlaylistForm({ onAdded }: { onAdded: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: string; text: string } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    setMessage(null);
    try {
      const processNow = Number(form.get("processNow") || 3);
      const result = await api.createPlaylist({
        url: String(form.get("url") || ""),
        name: String(form.get("name") || ""),
        kind: String(form.get("kind") || "general") as "general" | "podcast",
        extraction_focus: String(form.get("focus") || ""),
        process_now: processNow
      });
      await onAdded();
      formElement.reset();
      const count = result.video_count != null ? ` (${result.video_count} videos)` : "";
      setMessage({
        tone: "",
        text: `Added “${result.item.name}”${count}. Syncing now — ${processNow ? `the first ${processNow} will be processed` : "videos are only being listed"}; the rest follow in the daily sync.`
      });
    } catch (exc) {
      setMessage({ tone: "error", text: exc instanceof Error ? exc.message : "Could not add the playlist." });
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="ghost add-playlist-toggle" onClick={() => setOpen(true)}>
        {iconPlus()} Add a playlist
      </button>
    );
  }

  return (
    <form className="settings-form add-playlist" onSubmit={submit}>
      <div className="field span-2">
        <label htmlFor="pl-url">YouTube playlist link</label>
        <input id="pl-url" name="url" required placeholder="https://www.youtube.com/playlist?list=PL…" />
        <small>The playlist must be Public or Unlisted.</small>
      </div>
      <div className="field">
        <label htmlFor="pl-name">Name</label>
        <input id="pl-name" name="name" placeholder="Leave blank to use YouTube's title" />
      </div>
      <div className="field">
        <label htmlFor="pl-kind">Type</label>
        <select id="pl-kind" name="kind" defaultValue="general">
          <option value="general">Videos</option>
          <option value="podcast">Podcasts</option>
        </select>
      </div>
      <div className="field span-2">
        <label htmlFor="pl-focus">Focus for this playlist (optional)</label>
        <textarea id="pl-focus" name="focus" placeholder="For this playlist, prioritize…" />
      </div>
      <div className="field">
        <label htmlFor="pl-now">Process right away</label>
        <input id="pl-now" name="processNow" type="number" min="0" max="20" defaultValue="3" />
        <small>Oldest videos first. 0 only lists them.</small>
      </div>
      <div className="form-actions span-2">
        <button className="button" disabled={busy}>{busy ? "Checking the playlist…" : "Add playlist"}</button>
        <button type="button" className="text-button" onClick={() => { setOpen(false); setMessage(null); }}>Cancel</button>
      </div>
      {message ? <p className={`notice span-2 ${message.tone}`}>{message.text}</p> : null}
    </form>
  );
}

function PlaylistEditor({
  playlist,
  onSave
}: {
  playlist: Playlist;
  onSave: (playlistId: string, updates: PlaylistUpdate) => Promise<Playlist>;
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
        kind: draft.kind,
        extraction_focus: draft.extraction_focus || "",
        enabled: draft.enabled !== false
      });
      setDraft(saved);
      setMessage("Saved.");
    } catch (exc) {
      setMessage(exc instanceof Error ? exc.message : "Could not save the playlist.");
    } finally {
      setSaving(false);
    }
  }

  const paused = playlist.enabled === false || Number(playlist.enabled) === 0;
  return (
    <details className="entry">
      <summary>
        <span className="entry-title">{playlist.name || playlist.playlist_id}</span>
        <span className="leader" aria-hidden="true" />
        <span className="entry-count">
          {playlist.kind === "podcast" ? "podcasts" : "videos"} · {playlist.done_count ?? 0}/{playlist.video_count ?? 0} done{paused ? " · paused" : ""}
        </span>
        {iconChevron()}
      </summary>
      <form className="settings-form entry-body" onSubmit={submit}>
        <div className="field">
          <label htmlFor={`${playlist.playlist_id}-name`}>Name</label>
          <input id={`${playlist.playlist_id}-name`} value={draft.name || ""} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
        </div>
        <div className="field">
          <label htmlFor={`${playlist.playlist_id}-kind`}>Type</label>
          <select id={`${playlist.playlist_id}-kind`} value={draft.kind} onChange={(event) => setDraft((current) => ({ ...current, kind: event.target.value }))}>
            <option value="general">Videos</option>
            <option value="podcast">Podcasts</option>
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor={`${playlist.playlist_id}-focus`}>Focus for this playlist</label>
          <textarea id={`${playlist.playlist_id}-focus`} value={draft.extraction_focus || ""} onChange={(event) => setDraft((current) => ({ ...current, extraction_focus: event.target.value }))} placeholder="For this playlist, prioritize…" />
        </div>
        <label className="check-row span-2">
          <input
            type="checkbox"
            checked={draft.enabled !== false && Number(draft.enabled) !== 0}
            onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
          />
          Include in the daily sync
        </label>
        <div className="form-actions span-2">
          <button className="button" disabled={saving}>{saving ? "Saving…" : "Save playlist"}</button>
          {message ? <span className="form-message">{message}</span> : null}
        </div>
      </form>
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
