# Festivaly local frontend

A Next.js and React festival browser for the MAS course project. The interface is in English and uses the team's existing Czech and Slovak festival records.

## Start on this Mac

Open Terminal in this folder and run

```sh
sh start-local.sh
```

Open the Local URL printed in Terminal, normally http://127.0.0.1:3000. Leave Terminal running while using the website. Press Control+C to stop it. The script can use the Node.js runtime bundled with Codex when Node.js is absent from your normal terminal PATH.

## Start on another computer

Install a current supported Node.js version (at least 20.9) and pnpm. From this folder run

```sh
pnpm install --frozen-lockfile
pnpm dev
```

## How the pieces fit together

1. `data/festivals.json` is a copy of the supplied dataset. It has 216 records and a generation date of 13 November 2026.
2. `app/page.tsx` reads that JSON and passes it to the browser component. The current date in Prague determines which editions are past.
3. `components/FestivalBrowser.tsx` implements search, filters, sorting, pagination and the detail dialog. These interactions run in the browser.
4. `lib/festivals.ts` defines the expected record format and provides date formatting, accent-insensitive searching and HTTP/HTTPS link checks.
5. `app/globals.css` controls the responsive design. DM Sans and Bricolage Grotesque load from Google Fonts. The display font stack prefers Miox when available. A licensed Miox webfont can be added with an @font-face rule in app/globals.css.
6. `app/layout.tsx` sets the page title, language and shared styles.

## Browse festivals

On the home page, select one or more genre bubbles to update festival matches. With no genres selected, all genres are included. Home-page matching excludes past and cancelled editions. Scroll over the map to zoom, then drag to pan. Select a map pin or city bubble to see the city's festivals below the map. The calendar filters map results by date, and the selected city's list covers matching festivals across dates.

Open `/festivals` for the full catalogue, `/dataset` for the project and data overview, and `/gigs` for the planned gig feature. Click a festival to see its dates, status and source links, plus lineups or booking deadlines when available. The home page also lists festivals awaiting dates and those with listed open calls.

## Updating the data

The website reads `data/festivals.json`. The Python runner described below converts and merges validated agent output into that file. Nothing runs automatically when a visitor opens the site. Open calls reflect the saved snapshot, and festival details link to the original sources.

## Check and build

```sh
pnpm check
pnpm build
pnpm start
```

`pnpm check` checks TypeScript. `pnpm build` creates a production build. `pnpm start` serves that build locally.

## Sharing the project

The application is self-contained in this folder. Its source files, copied dataset and pnpm lockfile can be committed to a GitHub repository. `.gitignore` excludes installed packages, build output, local environment files and macOS metadata. Browsing the saved data requires no API keys. Live discovery with Exa requires an Exa key.

## Refresh the festival snapshot

Run the Python agents from the app repository root. The Scout and Extractor use
a collector database. The Validator and Freshness Manager use a second database
because their table schemas differ. The runner exchanges candidate JSON and
queued tasks between them. The website reads the resulting `data/festivals.json`.

Use Python 3.10 or later. The Extractor and Validator use the standard library.
For live Exa discovery, install the Scout dependencies in a virtual environment
and supply `EXA_API_KEY` in your shell. Set `NOMINATIM_CONTACT_EMAIL` to enable
geocoding when a festival page has no coordinates.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r agents/requirements.txt

# Start with one known festival URL, or discover up to five with Exa.
python agents/pipeline.py --url https://www.colours.cz/
python agents/pipeline.py --scout --country "Czech Republic" --genre metal --limit 5

# Import an existing Extractor --export-web file without making network calls.
python agents/pipeline.py --candidates /path/to/candidates.json

# Process a batch of queued rechecks and, with an Exa key, discovery tasks.
python agents/pipeline.py --refresh --limit 5
```

Add `--seed-baseline` to a run to register the saved website records for future
checks. Keep the same `--state` directory between runs so the agents remember
their queues and prior checks. For a dry run, use `--dataset` with a copy of
`data/festivals.json` and `--state` with a separate directory. Intermediate files,
the validator's snapshots, and the SQLite databases are in `.agent-state/`
by default. Review and commit only the intended changes to the website dataset
before deploying. Run one refresh process at a time.

Published agent records have passed the Validator. Existing website entries are
preserved until an approved update replaces them. The runner targets festival
records in Czechia and Slovakia. The venue extraction code is available in
`agents/extraktor.py`, and the public demo currently uses festival data.

Run the Python tests with `cd agents && python3 -m unittest discover -s tests`.
The integration tests use fixture search results and HTML with no live API calls.
