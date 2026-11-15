"use client";

import { useState } from "react";
import {
  dateRange,
  formatDate,
  genreLabels,
  type Festival,
} from "../lib/festivals";

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function occursOn(festival: Festival, day: string) {
  const start = festival.date_from;
  return Boolean(start && start <= day && day <= (festival.date_to || start));
}

export default function FestivalCalendar({
  festivals,
  cityFestivals,
  onCityEvent,
  onClearCity,
  initialDate,
  selectedDate,
  onSelect,
  onEvent,
}: {
  festivals: Festival[];
  cityFestivals: Festival[];
  onCityEvent: (festival: Festival) => void;
  onClearCity: () => void;
  initialDate: string;
  selectedDate: string;
  onSelect: (date: string) => void;
  onEvent: (festival: Festival, date: string) => void;
}) {
  const [month, setMonth] = useState(initialDate.slice(0, 7));
  const [year, monthNumber] = month.split("-").map(Number);
  const offset =
    (new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay() + 6) % 7;
  const days = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const label = new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, monthNumber - 1, 1)));

  const firstDay = `${month}-01`;
  const lastDay = `${month}-${days}`;
  const events = festivals.filter(
    ({ date_from, date_to }) =>
      date_from && date_from <= lastDay && (date_to || date_from) >= firstDay,
  );
  const shownEvents = selectedDate
    ? events.filter((festival) => occursOn(festival, selectedDate))
    : events;

  function moveMonth(step: number) {
    onSelect("");
    setMonth(
      new Date(Date.UTC(year, monthNumber - 1 + step, 1))
        .toISOString()
        .slice(0, 7),
    );
  }

  return (
    <section className="festival-calendar" aria-label="Festival calendar">
      <h2>Festival calendar</h2>
      <div className="calendar-month">
        <button
          type="button"
          aria-label="Previous month"
          onClick={() => moveMonth(-1)}
        >
          ‹
        </button>
        <strong aria-live="polite">{label}</strong>
        <button
          type="button"
          aria-label="Next month"
          onClick={() => moveMonth(1)}
        >
          ›
        </button>
      </div>
      <div className="calendar-grid">
        {weekdays.map((day) => (
          <span key={day}>{day}</span>
        ))}
        {Array.from({ length: offset }, (_, index) => (
          <span aria-hidden="true" key={`blank-${index}`} />
        ))}
        {Array.from({ length: days }, (_, index) => {
          const day = index + 1;
          const date = `${month}-${String(day).padStart(2, "0")}`;
          const count = festivals.filter((festival) =>
            occursOn(festival, date),
          ).length;
          return (
            <button
              type="button"
              key={date}
              disabled={!count}
              aria-label={`${formatDate(date)}, ${count} ${count === 1 ? "festival" : "festivals"}`}
              aria-pressed={selectedDate === date}
              onClick={() => onSelect(selectedDate === date ? "" : date)}
            >
              {day}
            </button>
          );
        })}
      </div>
      <div className="calendar-events">
        <h3>
          {selectedDate ? formatDate(selectedDate) : `Events in ${label}`}
        </h3>
        {shownEvents.length ? (
          <CalendarEventList
            festivals={shownEvents}
            onEvent={(festival) =>
              onEvent(
                festival,
                selectedDate ||
                  (festival.date_from && festival.date_from > firstDay
                    ? festival.date_from
                    : firstDay),
              )
            }
          />
        ) : (
          <p>No dated festival matches this month.</p>
        )}
      </div>
      {selectedDate ? (
        <button
          className="text-button calendar-clear"
          type="button"
          onClick={() => onSelect("")}
        >
          Clear {formatDate(selectedDate)}
        </button>
      ) : (
        <p>Pick an event to open its details.</p>
      )}
      {cityFestivals.length > 0 && (
        <section
          className="calendar-events calendar-city-events"
          aria-labelledby="city-events-title"
        >
          <div className="calendar-city-header">
            <h3 id="city-events-title">Festivals in {cityFestivals[0].city}</h3>
            <button className="text-button" type="button" onClick={onClearCity}>
              Clear city
            </button>
          </div>
          <CalendarEventList festivals={cityFestivals} onEvent={onCityEvent} />
        </section>
      )}
    </section>
  );
}

export function CalendarEventList({
  festivals,
  onEvent,
  showGenres = false,
}: {
  festivals: Festival[];
  showGenres?: boolean;
  onEvent: (festival: Festival) => void;
}) {
  return (
    <ul>
      {festivals.map((festival) => (
        <li key={festival.id}>
          <button type="button" onClick={() => onEvent(festival)}>
            <strong>{festival.name}</strong>
            {festival.open_call && (
              <span className="open-call-badge">
                Open call!{!showGenres && " 🎵"}
              </span>
            )}
            <span>
              {festival.city} · {dateRange(festival)}
            </span>
            {showGenres && (
              <span className="event-genres">
                {festival.genres
                  .map((genre) => genreLabels[genre] ?? genre)
                  .join(" · ")}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
