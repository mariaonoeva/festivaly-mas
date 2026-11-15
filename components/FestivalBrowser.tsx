"use client";

import FestivalCalendar, { CalendarEventList } from "./FestivalCalendar";
import FestivalMap from "./FestivalMap";
import { useMemo, useRef, useState } from "react";
import {
  Festival,
  dateRange,
  formatDate,
  genreLabels,
  isPast,
  normalize,
  safeUrl,
} from "../lib/festivals";

type Props = {
  festivals: Festival[];
  generated: string;
  today: string;
  catalogue?: boolean;
};
const PAGE_SIZE = 24;
const genreOptions = Object.entries(genreLabels).sort((a, b) =>
  a[1].localeCompare(b[1]),
);

const opportunityOptions = [
  ["festivals", "Festivals"],
  ["gigs", "Gigs"],
];

function Bubbles({
  label,
  options,
  values,
  onChange,
  clearable = false,
}: {
  label: string;
  options: string[][];
  values: string[];
  onChange: (values: string[]) => void;
  clearable?: boolean;
}) {
  return (
    <fieldset className="bubble-group">
      <legend>{label}</legend>
      <div className="bubble-options">
        {options.map(([value, text]) => (
          <button
            className="bubble"
            key={value}
            type="button"
            aria-pressed={values.includes(value)}
            onClick={() =>
              onChange(
                values.includes(value)
                  ? values.filter((selectedValue) => selectedValue !== value)
                  : [...values, value],
              )
            }
          >
            {text}
          </button>
        ))}
      </div>
      {clearable && (
        <button
          className="text-button clear-genres"
          type="button"
          disabled={!values.length}
          onClick={() => onChange([])}
        >
          Clear genres
        </button>
      )}
    </fieldset>
  );
}

function ExternalLink({
  url,
  children,
  className = "",
}: {
  url: string | null;
  children: React.ReactNode;
  className?: string;
}) {
  const href = safeUrl(url);
  return href ? (
    <a
      className={className}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <span aria-hidden="true"> ↗</span>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ) : null;
}

export default function FestivalBrowser({
  festivals,
  generated,
  today,
  catalogue = false,
}: Props) {
  const [bandName, setBandName] = useState("");
  const [bandGenres, setBandGenres] = useState<string[]>([]);
  const [opportunityTypes, setOpportunityTypes] = useState(["festivals"]);
  const showFestivals = !catalogue && opportunityTypes.includes("festivals");
  const showGigs = !catalogue && opportunityTypes.includes("gigs");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("name");
  const [selectedCity, setSelectedCity] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [selected, setSelected] = useState<Festival | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const matchingFestivals = useMemo(() => {
    const search = normalize(query);
    return festivals
      .filter((festival) =>
        !catalogue
          ? !isPast(festival, today) &&
            festival.status !== "cancelled" &&
            (bandGenres.length === 0 ||
              bandGenres.some((genre) => festival.genres.includes(genre)))
          : normalize(`${festival.name} ${festival.city}`).includes(search),
      )
      .sort((a, b) => {
        if (!catalogue || sort === "date") {
          return (
            (a.date_from || "9999").localeCompare(b.date_from || "9999") ||
            a.name.localeCompare(b.name)
          );
        }
        return a.name.localeCompare(b.name, "cs");
      });
  }, [festivals, catalogue, bandGenres, query, sort, today]);

  const results = matchingFestivals;
  const undatedFestivals = showFestivals
    ? matchingFestivals.filter((festival) => !festival.date_from)
    : [];
  const openCallFestivals = showFestivals
    ? matchingFestivals.filter((festival) => festival.open_call)
    : [];
  const cityFestivals = selectedCity
    ? matchingFestivals.filter(
        ({ country, city }) => `${country}|${city}` === selectedCity,
      )
    : [];
  const calendarDates = matchingFestivals
    .map(
      (festival) =>
        festival.date_from &&
        (festival.date_from < today ? today : festival.date_from),
    )
    .filter((date): date is string => Boolean(date))
    .sort();

  function resetCalendarSelection() {
    setSelectedDate("");
    setSelectedCity("");
  }

  function showDetails(festival: Festival) {
    setSelected(festival);
    dialog.current?.showModal();
  }

  return (
    <>
      <main>
        {!catalogue && (
          <section
            className={
              showFestivals ? "band-workspace has-map" : "band-workspace"
            }
            aria-label="Find festival opportunities"
          >
            <div className="band-form">
              <h1>Find a match for your band</h1>
              <label className="field">
                Band name
                <input
                  maxLength={100}
                  placeholder="e.g. The Echoes"
                  value={bandName}
                  onChange={(event) => setBandName(event.target.value)}
                />
              </label>
              <Bubbles
                label="Band genres (optional)"
                options={genreOptions}
                values={bandGenres}
                onChange={(genres) => {
                  setBandGenres(genres);
                  resetCalendarSelection();
                }}
                clearable
              />
              <Bubbles
                label="Opportunity types"
                options={opportunityOptions}
                values={opportunityTypes}
                onChange={(types) => {
                  setOpportunityTypes(types);
                  resetCalendarSelection();
                }}
              />
              <p className="snapshot-note">
                Saved dataset · {formatDate(generated)}
              </p>
            </div>
            {showFestivals && (
              <>
                <FestivalMap
                  festivals={matchingFestivals}
                  selectedDate={selectedDate}
                  selectedCity={selectedCity}
                  setSelectedCity={setSelectedCity}
                />
                <FestivalCalendar
                  key={`${bandGenres.join(",")}:${calendarDates[0] ?? today}`}
                  festivals={matchingFestivals}
                  cityFestivals={cityFestivals}
                  onClearCity={() => setSelectedCity("")}
                  onCityEvent={showDetails}
                  initialDate={selectedDate || calendarDates[0] || today}
                  selectedDate={selectedDate}
                  onEvent={(festival, date) => {
                    setSelectedDate(date);
                    showDetails(festival);
                  }}
                  onSelect={setSelectedDate}
                />
              </>
            )}
          </section>
        )}

        {showFestivals && (
          <div className="festival-event-panels">
            <section
              className="calendar-events festival-event-section"
              aria-labelledby="undated-festivals-title"
            >
              <h2 id="undated-festivals-title">Dates to be announced</h2>
              {undatedFestivals.length > 0 ? (
                <div
                  className="festival-event-scroll"
                  tabIndex={0}
                  role="group"
                  aria-label="Undated festivals"
                >
                  <CalendarEventList
                    festivals={undatedFestivals}
                    showGenres
                    onEvent={showDetails}
                  />
                </div>
              ) : (
                <p>No festivals awaiting dates for the current genres.</p>
              )}
            </section>

            <section
              className="calendar-events festival-event-section"
              aria-labelledby="open-calls-title"
            >
              <h2 id="open-calls-title">Open calls</h2>
              {openCallFestivals.length > 0 ? (
                <div
                  className="festival-event-scroll"
                  tabIndex={0}
                  role="group"
                  aria-label="Festivals with open calls"
                >
                  <CalendarEventList
                    festivals={openCallFestivals}
                    showGenres
                    onEvent={showDetails}
                  />
                </div>
              ) : (
                <p>No open calls listed for the current genres.</p>
              )}
            </section>
          </div>
        )}

        {(catalogue || showGigs) && (
          <section
            id="explore"
            aria-labelledby={catalogue ? "explore-title" : "gig-results"}
          >
            {catalogue && (
              <div className="festival-results">
                <div className="results">
                  <div className="results-heading">
                    <h1 id="explore-title">All festivals</h1>
                    <span
                      className="result-count"
                      role="status"
                      aria-live="polite"
                    >
                      {results.length}{" "}
                      {results.length === 1 ? "result" : "results"}
                    </span>
                  </div>
                  {catalogue && (
                    <div className="search-row">
                      <label className="search-field">
                        <span aria-hidden="true">⌕</span>
                        <span className="sr-only">
                          Search festivals or cities
                        </span>
                        <input
                          type="search"
                          placeholder="Search a festival or city…"
                          value={query}
                          onChange={(event) => {
                            setQuery(event.target.value);
                            setLimit(PAGE_SIZE);
                          }}
                        />
                      </label>
                      <label className="sort-field">
                        <span className="sr-only">Sort festivals</span>
                        <select
                          value={sort}
                          onChange={(e) => setSort(e.target.value)}
                        >
                          <option value="name">Name A–Z</option>
                          <option value="date">Date, earliest first</option>
                        </select>
                      </label>
                    </div>
                  )}
                  {results.length === 0 ? (
                    <div className="empty-state">
                      <span aria-hidden="true">∅</span>
                      <h3>No festivals match just yet.</h3>
                      <p>
                        {catalogue
                          ? "Try a different festival name or city."
                          : "Try another genre or clear the selected date."}
                      </p>
                    </div>
                  ) : (
                    <div className="festival-grid">
                      {results.slice(0, limit).map((f) => (
                        <article
                          className={`festival-card ${f.open_call ? "has-call" : ""}`}
                          key={f.id}
                        >
                          <div className="card-top">
                            <span className="location">
                              {f.city} ·{" "}
                              {f.country === "Slovakia" ? "SK" : "CZ"}
                            </span>
                            <span className="edition">{f.edition_year}</span>
                          </div>
                          <h3>{f.name}</h3>
                          <p className="festival-date">{dateRange(f)}</p>
                          <div className="tags">
                            {f.genres.map((g) => (
                              <span key={g}>{genreLabels[g] || g}</span>
                            ))}
                          </div>
                          <div className="edition-status">
                            {f.status === "cancelled" ? (
                              <span className="cancelled">
                                Cancelled edition
                              </span>
                            ) : isPast(f, today) ? (
                              <span>Past edition</span>
                            ) : f.status === "announced" ? (
                              <span>Announced edition</span>
                            ) : (
                              <span>Dates listed as confirmed</span>
                            )}
                          </div>
                          <div className="card-bottom">
                            <span
                              className={
                                f.open_call
                                  ? "call-status active"
                                  : "call-status"
                              }
                            >
                              {f.open_call
                                ? "Open call! 🎵"
                                : "No active call found"}
                            </span>
                            <button
                              className="details-button"
                              onClick={() => showDetails(f)}
                              aria-label={`View details for ${f.name}`}
                            >
                              Details <span aria-hidden="true">↗</span>
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                  {results.length > 0 && (
                    <div className="load-more">
                      <p>
                        Showing {Math.min(limit, results.length)} of{" "}
                        {results.length} festival records
                      </p>
                      {limit < results.length && (
                        <button
                          className="secondary-button"
                          onClick={() => setLimit((n) => n + PAGE_SIZE)}
                        >
                          Show more festivals <span aria-hidden="true">↓</span>
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
            {showGigs && (
              <div className="empty-state">
                <h2 id="gig-results" tabIndex={-1}>
                  Gig matches
                </h2>
                <p>
                  The saved dataset currently contains festival records only.
                </p>
              </div>
            )}
          </section>
        )}
      </main>

      <footer>
        <a href="/" className="footer-brand">
          festivaly.
        </a>
        <span>Built for bands finding their next stage.</span>
        <span>MAS · Competitive Intelligence</span>
      </footer>

      <dialog
        ref={dialog}
        className="detail-dialog"
        aria-labelledby="detail-title"
        onClick={(e) => {
          if (e.target === e.currentTarget) dialog.current?.close();
        }}
      >
        {selected && (
          <div className="detail-content">
            <div className="detail-top">
              <span className="eyebrow">FESTIVAL DETAILS</span>
              <button
                autoFocus
                className="close-button"
                onClick={() => dialog.current?.close()}
                aria-label="Close festival details"
              >
                ×
              </button>
            </div>
            <p className="location">
              {selected.city} · {selected.country}
            </p>
            <h2 id="detail-title">{selected.name}</h2>
            <div className="tags">
              {selected.genres.map((g) => (
                <span key={g}>{genreLabels[g] || g}</span>
              ))}
            </div>
            <dl className="detail-facts">
              <div>
                <dt>Edition</dt>
                <dd>
                  {selected.edition_year}
                  {isPast(selected, today) ? " · Past edition" : ""}
                </dd>
              </div>
              <div>
                <dt>Dates</dt>
                <dd>{dateRange(selected)}</dd>
              </div>
              <div>
                <dt>Status in dataset</dt>
                <dd>
                  {selected.status === "confirmed"
                    ? "Confirmed dates"
                    : selected.status === "cancelled"
                      ? "Cancelled"
                      : "Announced"}
                </dd>
              </div>
              <div>
                <dt>Event type</dt>
                <dd>
                  {selected.type === "one-off"
                    ? "One-off event"
                    : selected.type === "showcase"
                      ? "Showcase"
                      : "Festival"}
                </dd>
              </div>
            </dl>
            <section className="call-panel">
              <h3>
                {selected.open_call ? "Open call! 🎵" : "No active call found"}
              </h3>
              <p>
                {selected.open_call
                  ? "The saved record includes an application link. Check the organiser’s page for current deadlines and eligibility."
                  : "The dataset has no active application link for this edition. Check the organiser’s website for booking information."}
              </p>
              {selected.open_call && (
                <ExternalLink
                  url={selected.open_call_url}
                  className="primary-button"
                >
                  Check application
                </ExternalLink>
              )}
            </section>
            <div className="source-links">
              <ExternalLink url={selected.website} className="secondary-button">
                Festival website
              </ExternalLink>
              <ExternalLink url={selected.source_url} className="text-link">
                View original source
              </ExternalLink>
            </div>
            {!safeUrl(selected.website) && (
              <p className="detail-note">
                An official website has not been verified in this dataset.
              </p>
            )}
            <p className="detail-note">
              Saved dataset from {formatDate(generated)}. Record details and
              sources have not been rechecked by this app.
            </p>
          </div>
        )}
      </dialog>
    </>
  );
}
