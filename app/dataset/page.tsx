import type { Metadata } from "next";
import dataset from "../../data/festivals.json";
import { formatDate, type Festival } from "../../lib/festivals";

export const metadata: Metadata = { title: "About Festivaly · Festivaly" };

export default function DatasetPage() {
  const { festivals, generated } = dataset;
  const czechCount = festivals.filter(
    ({ country }) => country === "Czech Republic",
  ).length;
  const slovakCount = festivals.filter(
    ({ country }) => country === "Slovakia",
  ).length;
  const cityCount = new Set(
    festivals.filter(({ city }) => city.trim()).map(({ country, city }) => `${country}|${city.trim()}`),
  ).size;
  const openCalls = festivals.filter(({ open_call }) => open_call).length;
  const lineupCount = (festivals as Festival[]).filter(
    ({ lineup }) => lineup?.some(({ artists }) => artists.length > 0),
  ).length;

  return (
    <main className="dataset-page">
      <h1>About Festivaly</h1>
      <p className="dataset-intro">
        Festivaly is a Competitive Intelligence course project. It asks where a
        band should apply next season for a realistic chance of getting booked.
      </p>
      <div className="dataset-notes">
        <section>
          <h2>Why it’s competitive intelligence</h2>
          <p>
            A band deciding where to apply needs to know who gets booked.
            Lineups from past editions can show whether comparable artists
            and acts from similar labels have played there, which stages they
            played, and who else might compete for a slot. Combined with genre
            fit, dates, and application deadlines, that evidence helps a band
            decide which opportunities to pursue first.
          </p>
          <p>
            The prototype supports festival discovery by genre, city, and date.
            Comparing past lineups and labels, matching a band to stage size,
            and finding gigs are planned capabilities.
          </p>
        </section>
        <section>
          <h2>How the project follows the intelligence cycle</h2>
          <p>
            The team starts with questions about booking fit and uses them to
            guide what it collects. The Scout finds public sources, the
            Extractor structures the data, and the Validator checks it.
            The map and calendar share the resulting snapshot with bands.
            The Freshness Manager queues rechecks as records age or deadlines
            approach.
          </p>
        </section>
      </div>
      <h2>About the dataset</h2>
      <p className="dataset-intro">
        Festivaly uses a saved collection of festival, showcase, and one-off
        event records from Czechia and Slovakia. Gig listings are outside this
        snapshot’s coverage. This snapshot was generated on{" "}
        {formatDate(generated)}.
      </p>
      <p className="dataset-intro">
        With more research time and a larger AI token budget, the team could
        extend coverage to neighbouring countries by collecting and verifying
        festival listings from local sources.
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
          <dt>Cities</dt>
          <dd>{cityCount}</dd>
        </div>
        <div>
          <dt>Listed open calls</dt>
          <dd>{openCalls}</dd>
        </div>
        <div>
          <dt>Records with lineups</dt>
          <dd>{lineupCount}</dd>
        </div>
      </dl>
      <div className="dataset-notes">
        <section>
          <h2>What each record contains</h2>
          <p>
            Name, city, country, genre, edition dates and status, and a source
            link. Where available, festival details can also show lineup artists,
            open-call deadlines, and the last source check. A festival held in
            multiple cities can have a separate record for each location.
          </p>
        </section>
        <section>
          <h2>How the agents update the dataset</h2>
          <p>
            A manually run Python pipeline refreshes the saved snapshot from
            public festival websites. The website loads that snapshot when you
            browse.
          </p>
          <ol className="dataset-workflow">
            <li>
              <strong>Scout.</strong> Uses Exa to discover festival websites.
              The Extractor can also start from a known festival URL.
            </li>
            <li>
              <strong>Extractor.</strong> Reads public web pages and records
              fields such as edition dates, genres, and application links,
              together with their sources.
            </li>
            <li>
              <strong>Validator.</strong> Uses deterministic Python rules to
              normalize records, check dates and links, identify duplicates, and
              assign confidence. The runner merges approved records into the
              website’s dataset.
            </li>
            <li>
              <strong>Freshness Manager.</strong> Queues rechecks for aging
              records and approaching events or deadlines. The queue is
              processed when the refresh command is run.
            </li>
          </ol>
          <p>
            A trial on Colours of Ostrava found nine lineup artists. That
            result is in a separate review copy.
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
            below the map and calendar.
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
