import type { Video } from "./api";

export type Insight = {
  title: string;
  content: string;
  points: string[];
};

function parseJson(raw: string | undefined): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function videoSummary(video: Video | null): string {
  if (!video) return "";
  const structured = parseJson(video.structured_insights) as Record<string, unknown> | null;
  if (video.summary) return video.summary;
  if (structured && typeof structured.summary === "string") return structured.summary;
  return "";
}

export function videoInsights(video: Video | null): Insight[] {
  if (!video) return [];
  const structured = parseJson(video.structured_insights) as Record<string, unknown> | null;
  const raw = structured?.insights;
  if (Array.isArray(raw)) {
    return raw
      .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      .map((item) => ({
        title: String(item.topic || item.title || "Insight"),
        content: String(item.content || item.insight || ""),
        points: Array.isArray(item.points)
          ? item.points.map(String)
          : Array.isArray(item.key_points)
            ? item.key_points.map(String)
            : []
      }));
  }
  const points = parseJson(video.key_points) as unknown;
  if (Array.isArray(points)) {
    return [{ title: "Key points", content: "", points: points.map(String) }];
  }
  return [];
}
