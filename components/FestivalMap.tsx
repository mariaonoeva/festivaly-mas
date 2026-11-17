"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { CalendarEventList, occursOn } from "./FestivalCalendar";
import geography from "../data/festival-map.json";
import { formatDate, type Festival } from "../lib/festivals";

const cityCoordinates: Record<string, number[]> = geography.cities;
const MAP_WIDTH = 770;
const MAP_HEIGHT = 405;
const MIN_ZOOM = 1;
const MAX_ZOOM = 3;

function mapPoint(festival: Festival) {
  const cached = cityCoordinates[`${festival.country}|${festival.city}`];
  if (cached) return cached;
  if (festival.lat == null || festival.lon == null) return undefined;
  // Same projection as the bundled boundary coordinates.
  const x = (festival.lon - 11.6) * 70;
  const y = (51.5 - festival.lat) * 105;
  return x >= 0 && x <= MAP_WIDTH && y >= 0 && y <= MAP_HEIGHT
    ? [x, y]
    : undefined;
}

export default function FestivalMap({
  festivals,
  selectedDate,
  selectedCity,
  setSelectedCity,
  cityFestivals,
  onCityEvent,
}: {
  festivals: Festival[];
  selectedDate: string;
  selectedCity: string;
  setSelectedCity: (city: string) => void;
  cityFestivals: Festival[];
  onCityEvent: (festival: Festival) => void;
}) {
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const drag = useRef<{
    pointerId: number;
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const zoomAnchor = useRef({ x: 0.5, y: 0.5, offsetX: 0, offsetY: 0 });

  const changeZoom = useCallback((nextZoom: number, pointer?: WheelEvent) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const bounds = viewport.getBoundingClientRect();
    const offsetX = pointer ? pointer.clientX - bounds.left : viewport.clientWidth / 2;
    const offsetY = pointer ? pointer.clientY - bounds.top : viewport.clientHeight / 2;
    zoomAnchor.current = {
      x: (viewport.scrollLeft + offsetX) / viewport.scrollWidth,
      y: (viewport.scrollTop + offsetY) / viewport.scrollHeight,
      offsetX,
      offsetY,
    };
    setZoom(nextZoom);
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const pageHeight = () => viewport.clientHeight;
    function onWheel(event: WheelEvent) {
      if (!event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
      const deltaScale = [1, 16, pageHeight()][event.deltaMode] ?? 1;
      const nextZoom = Math.min(
        MAX_ZOOM,
        Math.max(MIN_ZOOM, zoom * Math.exp((-event.deltaY * deltaScale) / 300)),
      );
      if (nextZoom === zoom && !event.ctrlKey) return;
      event.preventDefault();
      if (nextZoom !== zoom) changeZoom(nextZoom, event);
    }
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, [changeZoom, zoom]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || zoom === MIN_ZOOM) {
      viewport?.scrollTo(0, 0);
      return;
    }
    const { x, y, offsetX, offsetY } = zoomAnchor.current;
    viewport.scrollLeft = x * viewport.scrollWidth - offsetX;
    viewport.scrollTop = y * viewport.scrollHeight - offsetY;
  }, [zoom]);

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (zoom === MIN_ZOOM || event.pointerType !== "mouse" || event.button !== 0) return;
    if (!(event.target instanceof Element) || !event.target.closest(".map-surface")) return;
    const viewport = event.currentTarget;
    drag.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: viewport.scrollLeft,
      top: viewport.scrollTop,
    };
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const start = drag.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const viewport = event.currentTarget;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (!viewport.hasPointerCapture(event.pointerId)) {
      if (Math.hypot(dx, dy) < 4) return;
      viewport.setPointerCapture(event.pointerId);
      viewport.dataset.dragging = "true";
    }
    viewport.scrollLeft = start.left - dx;
    viewport.scrollTop = start.top - dy;
  }

  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    delete event.currentTarget.dataset.dragging;
  }

  const cities = new Map<string, Festival[]>();
  const points = new Map<string, number[]>();
  let unmapped = 0;

  for (const festival of festivals) {
    if (selectedDate && !occursOn(festival, selectedDate)) continue;
    const key = `${festival.country}|${festival.city}`;
    const point = mapPoint(festival);
    if (point && !points.has(key)) points.set(key, point);
    const records = cities.get(key) ?? [];
    records.push(festival);
    cities.set(key, records);
  }

  for (const [key, records] of cities) {
    if (points.has(key)) continue;
    unmapped += records.length;
    cities.delete(key);
  }

  const cityBubbles = selectedCity && cityFestivals.length
    ? [[selectedCity, cities.get(selectedCity) ?? cityFestivals] as const]
    : Array.from(cities).sort(
        ([, a], [, b]) =>
          b.length - a.length || a[0].city.localeCompare(b[0].city, "cs"),
      );

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
        Pick a city to see its matches. Scroll to zoom, then drag to move the map.
      </p>
      {selectedDate && <p>Showing festivals on {formatDate(selectedDate)}.</p>}
      <div className="map-scroll">
        <button
          className="text-button map-reset"
          type="button"
          disabled={zoom === MIN_ZOOM}
          onClick={() => changeZoom(MIN_ZOOM)}
        >
          Reset zoom
        </button>
        <div
          className="map-viewport"
          ref={viewportRef}
          role="region"
          aria-label="Scrollable festival map"
          tabIndex={0}
          data-zoomed={zoom > MIN_ZOOM}
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
          onPointerLeave={(event) => {
            if (!event.currentTarget.hasPointerCapture(event.pointerId)) endDrag(event);
          }}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return;
            const step = event.key === "+" ? 0.5 : event.key === "-" ? -0.5 : 0;
            if (!step) return;
            event.preventDefault();
            changeZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom + step)));
          }}
        >
          <div className="map-surface" style={{ width: `${zoom * 100}%` }}>
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
              const [x, y] = points.get(key)!;
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
                  {zoom > MIN_ZOOM && (
                    <span className="map-pin-label" aria-hidden="true">
                      {records[0].city}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
        <div
          className="map-cities"
          role="group"
          aria-label="Cities with festival matches"
        >
          {cityBubbles.map(([key, records]) => (
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
      {cityFestivals.length > 0 && (
        <section
          className="calendar-events calendar-city-events"
          aria-labelledby="city-events-title"
        >
          <div className="calendar-city-header">
            <h3 id="city-events-title">Festivals in {cityFestivals[0].city}</h3>
            <button
              className="text-button"
              type="button"
              onClick={() => setSelectedCity("")}
            >
              Clear city filter
            </button>
          </div>
          <CalendarEventList festivals={cityFestivals} onEvent={onCityEvent} />
        </section>
      )}
    </section>
  );
}
