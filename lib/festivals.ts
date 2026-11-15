export type Festival = {
  id: string;
  name: string;
  type: string;
  genres: string[];
  country: string;
  city: string;
  edition_year: number;
  date_from: string | null;
  date_to: string | null;
  status: string;
  open_call: boolean;
  open_call_url: string | null;
  website: string | null;
  source_url: string;
};

export const genreLabels: Record<string, string> = {
  rock: "Rock",
  pop: "Pop",
  "indie-alternative": "Indie & alternative",
  metal: "Metal",
  "punk-hardcore": "Punk & hardcore",
  electronic: "Electronic",
  "techno-house": "Techno & house",
  "hip-hop": "Hip-hop",
  "jazz-blues": "Jazz & blues",
  "folk-acoustic": "Folk & acoustic",
  world: "World",
  classical: "Classical",
  "reggae-ska": "Reggae & ska",
  experimental: "Experimental",
  "multi-genre": "Multi-genre",
};

export function normalize(text: string) {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

export function safeUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function isPast(festival: Festival, today: string) {
  const end = festival.date_to || festival.date_from;
  return end ? end < today : festival.edition_year < Number(today.slice(0, 4));
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value + "T00:00:00Z"));
}

export function dateRange(festival: Festival) {
  if (!festival.date_from) return "Dates to be announced";
  if (!festival.date_to || festival.date_to === festival.date_from)
    return formatDate(festival.date_from);
  return `${formatDate(festival.date_from)} – ${formatDate(festival.date_to)}`;
}

export function currentPragueDate() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Prague",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = (type: string) =>
    parts.find((part) => part.type === type)?.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}
