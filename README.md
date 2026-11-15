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

## First version

On the home page, enter a band name and select one or more genre and opportunity bubbles. Festival matching accepts any of the selected genres and excludes past and cancelled editions. Use the open-call filter to narrow the results to entries with a listed call. Gig matching shows a data notice because this snapshot contains festivals only. Open `/festivals` to browse the complete catalogue independently.

The browser also supports searches by festival name or city, filters for country, genre, edition and status, upcoming editions, and records with an open call. Clicking a festival opens its dates, status and source links. Records appear in batches of 24.

Open calls are explicitly described as listed in the saved dataset. A false open-call value displays “No active call found”. Dates marked confirmed are shown as confirmed in the dataset. This app does not fetch or verify external pages. Cancelled and past editions are labelled. Unknown dates remain unknown. Source links open in a new tab.

## Updating the data

Replace `data/festivals.json` with a new file using the same wrapper and record fields. Save it and reload the website. Keep IDs unique. The first two agents can supply this file later.

Adam's snapshot uses another schema, including `url`, country codes and an object for `open_call`. Map that output to the `Festival` type before connecting it. Band results use Natural Earth boundaries and GeoNames city coordinates. Select a city pin to explore festival details. The results list also includes festivals whose locations could not be matched. Venue coordinates, venue data, live agent execution and the chatbot are further integration work.

## Check and build

```sh
pnpm check
pnpm build
pnpm start
```

`pnpm check` checks TypeScript. `pnpm build` creates a production build. `pnpm start` serves that build locally.

## Sharing the project

The application is self-contained in this folder. Its source files, copied dataset and pnpm lockfile can be committed to a GitHub repository. `.gitignore` excludes installed packages, build output, local environment files and macOS metadata. The current version requires no API keys.
