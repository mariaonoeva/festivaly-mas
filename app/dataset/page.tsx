import type { Metadata } from "next";
import dataset from "../../data/festivals.json";
import { formatDate } from "../../lib/festivals";

export const metadata: Metadata = { title: "About the dataset · Festivaly" };

export default function DatasetPage() {
  const { festivals, generated } = dataset;
  const czechCount = festivals.filter(
    ({ country }) => country === "Czech Republic",
  ).length;
  const slovakCount = festivals.filter(
    ({ country }) => country === "Slovakia",
  ).length;
  const openCalls = festivals.filter(({ open_call }) => open_call).length;

  return (
    <main className="dataset-page">
      <h1>About the dataset</h1>
      <p className="dataset-intro">
        Festivaly uses a saved collection of festival, showcase, and one-off
        event records from Czechia and Slovakia. This snapshot was generated on{" "}
        {formatDate(generated)}.
      </p>
      <dl className="dataset-stats">
        <div>
          <dt>Records</dt>
          <dd>{festivals.length}</dd>
        </div>
        <div>
          <dt>Czechia</dt>
          <dd>{czechCount}</dd>
        </div>
        <div>
          <dt>Slovakia</dt>
          <dd>{slovakCount}</dd>
        </div>
        <div>
          <dt>Listed open calls</dt>
          <dd>{openCalls}</dd>
        </div>
      </dl>
      <div className="dataset-notes">
        <section>
          <h2>What each record contains</h2>
          <p>
            Name, city, country, genre, edition dates and status, and a source
            link. A festival held in multiple cities can have a separate record
            for each location.
          </p>
        </section>
        <section>
          <h2>How the agents update the dataset</h2>
          <p>
            The project uses an agent pipeline to collect and refresh festival
            records from public sources. The website reads the exported snapshot
            shown above.
          </p>
          <ol className="dataset-workflow">
            <li>
              <strong>Explorer.</strong> Searches for festival websites and new
              editions with Exa. It passes candidate links to the Extractor.
            </li>
            <li>
              <strong>Extractor.</strong> Reads pages with Firecrawl and records
              fields such as edition dates, genres, and application links,
              together with their sources.
            </li>
            <li>
              <strong>Validator.</strong> Uses deterministic Python rules to
              normalize records, check dates and links, identify duplicates, and
              assign confidence. Approved records can be exported from the
              shared SQLite database.
            </li>
            <li>
              <strong>Freshness Manager.</strong> Queues rechecks for aging
              records and approaching events or deadlines. When new source data
              is collected and validated, the pipeline logs changes such as new
              editions, date changes, and cancellations.
            </li>
          </ol>
          <p>
            The Validator and Freshness Manager run locally. The website loads a
            saved export, so the snapshot date tells you which version you are
            viewing.
          </p>
        </section>
        <section>
          <h2>Open calls and availability</h2>
          <p>
            “Open call!” means the saved record lists an application
            opportunity. Follow the organiser’s link to check whether
            applications are still open and confirm deadlines and eligibility.
          </p>
        </section>
        <section>
          <h2>Map and calendar coverage</h2>
          <p>
            Pins mark cities. Festivals without a reliable city location are
            still accessible through the calendar. Entries awaiting dates appear
            below the map and calendar. The snapshot currently covers festivals,
            showcases, and one-off events.
          </p>
          <p>
            Map boundaries and city coordinates come from{" "}
            <a href="https://www.naturalearthdata.com/">Natural Earth</a> and{" "}
            <a href="https://www.geonames.org/">GeoNames</a>.
          </p>
        </section>
      </div>
    </main>
  );
}
