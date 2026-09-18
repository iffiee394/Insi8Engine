import type { Video } from "./api";

export type Insight = {
  title: string;
  content: string;
  points: string[];
};

export type ResearchLink = {
  label: string;
  url: string;
  source: string;
};

export type ResearchResource = {
  name: string;
  type: string;
  detail: string;
  url?: string | null;
  source?: string;
};

export type ResearchBundle = {
  resources: ResearchResource[];
  links: ResearchLink[];
};

function parseJson(raw: string | undefined): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function cleanTitle(value: unknown, fallback = "Insight"): string {
  const text = String(value || fallback).replace(/^=+\s*/, "").trim();
  return text || fallback;
}

function textFrom(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  const direct = record.point || record.text || record.detail || record.insight || record.content || record.title || record.name;
  if (typeof direct === "string") return direct.trim();
  return "";
}

function listFrom(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(textFrom).filter(Boolean);
}

function fromKeyPoints(raw: unknown): Insight[] {
  const rows = listFrom(raw);
  const sections: Insight[] = [];
  let current: Insight | null = null;

  for (const row of rows) {
    if (/^=+\s*/.test(row)) {
      if (current && (current.content || current.points.length)) sections.push(current);
      current = { title: cleanTitle(row, "Key points"), content: "", points: [] };
      continue;
    }

    if (!current) current = { title: "Key points", content: "", points: [] };
    current.points.push(row);
  }

  if (current && (current.content || current.points.length)) sections.push(current);
  return sections;
}

export function videoSummary(video: Video | null): string {
  if (!video) return "";
  const structured = parseJson(video.structured_insights) as Record<string, unknown> | null;
  if (video.summary) return video.summary;
  if (video.manual_summary) return video.manual_summary;
  if (structured && typeof structured.summary === "string") return structured.summary;
  return "";
}

export function videoInsights(video: Video | null): Insight[] {
  if (!video) return [];
  const structured = parseJson(video.structured_insights) as Record<string, unknown> | null;
  const raw = structured?.insights;

  if (Array.isArray(raw)) {
    const sections = raw
      .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      .map((item) => ({
        title: cleanTitle(item.topic || item.title, "Insight"),
        content: textFrom(item.content || item.insight || item.summary),
        points: listFrom(item.points || item.key_points)
      }))
      .filter((section) => section.content || section.points.length);
    if (sections.length) return sections;
  }

  const keyPointInsights = fromKeyPoints(parseJson(video.key_points));
  if (keyPointInsights.length) return keyPointInsights;
  return fromKeyPoints(parseJson(video.manual_key_points));
}


function urlFrom(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  return /^https?:\/\//i.test(text) ? text : "";
}

function pushLink(links: ResearchLink[], raw: unknown, source: string, fallbackLabel: string) {
  if (typeof raw === "string") {
    const url = urlFrom(raw);
    if (url) links.push({ label: fallbackLabel || url, url, source });
    return;
  }
  if (!raw || typeof raw !== "object") return;
  const item = raw as Record<string, unknown>;
  const url = urlFrom(item.url || item.href || item.link);
  if (!url) return;
  links.push({
    label: textFrom(item.title || item.name || item.label) || fallbackLabel || url,
    url,
    source: textFrom(item.source) || source
  });
}

export function videoResearch(video: Video | null): ResearchBundle {
  if (!video) return { resources: [], links: [] };
  const structured = parseJson(video.structured_insights) as Record<string, unknown> | null;
  const resourcesRaw = structured?.resources;
  const linksRaw = structured?.links;
  const resources: ResearchResource[] = [];
  const links: ResearchLink[] = [];

  if (Array.isArray(resourcesRaw)) {
    for (const raw of resourcesRaw) {
      if (!raw || typeof raw !== "object") continue;
      const item = raw as Record<string, unknown>;
      const name = textFrom(item.name || item.title);
      const detail = textFrom(item.detail || item.description || item.summary);
      const url = urlFrom(item.url);
      if (!name && !detail && !url) continue;
      resources.push({
        name: name || url || "Resource",
        type: textFrom(item.type) || "resource",
        detail,
        url: url || null,
        source: textFrom(item.source) || "insight"
      });
      if (url) links.push({ label: name || url, url, source: textFrom(item.source) || "resource" });
    }
  }

  if (linksRaw && typeof linksRaw === "object") {
    for (const [source, value] of Object.entries(linksRaw as Record<string, unknown>)) {
      if (Array.isArray(value)) {
        value.forEach((entry, index) => pushLink(links, entry, source, `${source} ${index + 1}`));
      } else {
        pushLink(links, value, source, source);
      }
    }
  }

  const uniqueLinks = Array.from(new Map(links.map((link) => [link.url, link])).values());
  return { resources: resources.slice(0, 30), links: uniqueLinks.slice(0, 30) };
}
