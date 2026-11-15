"use client";

import { occursOn } from "./FestivalCalendar";
import geography from "../data/festival-map.json";
import { formatDate, type Festival } from "../lib/festivals";

const coordinates: Record<string, number[]> = geography.cities;
const MAP_WIDTH = 770;
const MAP_HEIGHT = 405;

export default function FestivalMap({
  festivals,
  selectedDate,
  selectedCity,
  setSelectedCity,
}: {
  festivals: Festival[];
  selectedDate: string;
  selectedCity: string;
  setSelectedCity: (city: string) => void;
}) {
  const cities = new Map<string, Festival[]>();
  let unmapped = 0;

  for (const festival of festivals) {
    if (selectedDate && !occursOn(festival, selectedDate)) continue;
    const key = `${festival.country}|${festival.city}`;
    if (!coordinates[key]) {
      unmapped++;
      continue;
    }
    const records = cities.get(key) ?? [];
    records.push(festival);
    cities.set(key, records);
  }

  return (
    <section
      id="match-map"
      tabIndex={-1}
      data-date-selected={Boolean(selectedDate)}
      className="match-map"
      aria-label="Festival matches map"
    >
      <h2>Explore matches on the map</h2>
      <p>
        Pick a city pin or bubble to see all its matches below the calendar.
        Pins show city locations.
      </p>
      {selectedDate && <p>Showing festivals on {formatDate(selectedDate)}.</p>}
      <div className="map-scroll">
        <div className="map-surface">
          <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} aria-hidden="true">
            {Object.entries(geography.paths).map(([code, path]) => (
              <path
                key={code}
                d={path}
                className={
                  code === "CZE" || code === "SVK"
                    ? "map-focus-country"
                    : undefined
                }
              />
            ))}
            <text x="210" y="105">
              Czechia
            </text>
            <text x="535" y="220">
              Slovakia
            </text>
          </svg>
          {Array.from(cities, ([key, records]) => {
            const [x, y] = coordinates[key];
            return (
              <button
                key={key}
                type="button"
                className="map-pin"
                data-date-match="true"
                style={{
                  left: `${(x / MAP_WIDTH) * 100}%`,
                  top: `${(y / MAP_HEIGHT) * 100}%`,
                }}
                aria-label={`${records[0].city}, ${records.length} festival ${records.length === 1 ? "match" : "matches"}`}
                aria-pressed={key === selectedCity}
                title={records[0].city}
                onClick={() => setSelectedCity(key)}
              >
                {records.length}
              </button>
            );
          })}
        </div>
        <div
          className="map-cities"
          role="group"
          aria-label="Cities with festival matches"
        >
          {Array.from(cities)
            .sort(
              (a, b) =>
                b[1].length - a[1].length ||
                a[1][0].city.localeCompare(b[1][0].city, "cs"),
            )
            .map(([key, records]) => (
              <button
                type="button"
                key={key}
                className="bubble"
                data-date-match="true"
                aria-pressed={key === selectedCity}
                onClick={() => setSelectedCity(key === selectedCity ? "" : key)}
              >
                {records[0].city} <small>{records.length}</small>
              </button>
            ))}
        </div>
      </div>
      {cities.size === 0 && <p>No matching city pins to show.</p>}
      {unmapped > 0 && (
        <p>
          {unmapped} {unmapped === 1 ? "match is" : "matches are"} available in
          the calendar without a map pin.
        </p>
      )}
      <p className="map-credit">
        Map data by{" "}
        <a href="https://www.naturalearthdata.com/">Natural Earth</a> and{" "}
        <a href="https://www.geonames.org/">GeoNames</a>.
      </p>
    </section>
  );
}
