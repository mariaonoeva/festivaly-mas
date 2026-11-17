# Agent 5 – Chatbot pro kapely (Matyáš)

Gemini s nástroji nad validovaným datasetem. Jen standardní knihovna Pythonu: žádný SDK,
žádné balíčky navíc (nehrozí slopsquatting), Gemini se volá přes REST.

```sh
cd agents
python pipeline.py --candidates ../data/festivals.json --seed-baseline   # naplní .agent-state/validator.sqlite
python -m chatbot.server --port 8787                                     # čte ../.env
curl -X POST localhost:8787/api/chat -H 'Content-Type: application/json' \
     -d '{"message":"Punk festivals in Slovakia in summer 2027?","history":[]}'
python -m unittest discover -s tests                                     # 50 testů, bez sítě
```

## API
`POST /api/chat` `{"message": "...", "history": [{"role":"user|model","text":"..."}]}`
→ `{"answer": "...", "festivals": [{"id","name","website","sources"}], "search_requests": [...]}`

`festivals` se skládá z výsledků nástrojů, ne z textu modelu: web ukazuje jen ověřené odkazy.
`answer` je prostý text, ve frontendu vkládat jako text (nikdy `innerHTML`).
`GET /api/health` → 200, když je klíč i dataset, jinak 503.

## Nástroje modelu
| nástroj | KIQ | co dělá |
|---|---|---|
| `search_festivals` | 1, 2 | žánr, země, město, období, jen s open callem; bez proběhlých a zrušených |
| `get_festival` | 2, 3 | detail se zdroji, line-upem a změnami |
| `lineup_overlap` | 4 | festivaly se sdílenými interprety (konkurence) |
| `recent_changes` | 5 | nové ročníky, posuny termínů, zrušení, nové open cally |
| `search_venues` | 6 | venues v TTL; prázdné = chybí platná cache |
| `request_search` | – | ad hoc hledání z pevné šablony (druh, země, město, žánr, měsíce) |

## Bezpečnost
| riziko | opatření |
|---|---|
| zápis do datasetu | dataset se otevírá `mode=ro` + `query_only`; ven jde jen `record_state='validated'` |
| prompt injection z webů | nástroje nemají dopad; jediný zápis je ad hoc požadavek z enumů a ověřeného města; max. 1 na dotaz |
| útok na peněženku | délka zprávy 500 znaků, 6 dotazů/min a 60/den na klienta, 300 volání Gemini/den, max. 4 kola nástrojů, 20 ad hoc hledání/den, dedupe |
| únik klíče | klíč jen v `.env` na serveru, v hlavičce (ne v URL), nikdy v logu ani v odpovědi |
| CORS / XSS | povolené jen domény z `CHAT_ALLOWED_ORIGINS`; JSON s `nosniff` a `CSP default-src 'none'` |
| výpadek Gemini | při 500/503 jeden opakovaný pokus, pak záložní model (`GEMINI_FALLBACK_MODEL`); každý pokus se počítá do denního stropu |
| fail closed | bez klíče, když selže i záloha nebo chybí DB → 503 s obecnou chybou |
| osobní údaje | IP se neukládá, jen solený hash pro limity |

Free tier Gemini: data se mohou použít ke zlepšení produktů Googlu. Posíláme jen dotaz kapely
a veřejná data o festivalech, žádné osobní údaje.

## Tok ad hoc hledání
Chatbot → `chatbot.sqlite` (`adhoc_requests`) → `pipeline.py --refresh` je převede na úkol
`search` pro Průzkumníka (priorita 5) → Extraktor → Validátor → po schválení je chatbot najde.
Gigy se zatím jen zaznamenají (`unsupported`), pipeline venues ještě neexistuje. Chatbot to kapele řekne
(`note` u požadavku) a nic neslibuje.

## Web
`components/ChatPanel.tsx` (v `app/layout.tsx`, na všech stránkách). Adresa backendu z `NEXT_PUBLIC_CHAT_API_URL`
(`.env.local`, na Vercelu Environment Variables). Odpověď se vykresluje jako text, odkazy jen `http(s)`,
seznam zdrojů jen z pole `festivals`. Ověřeno v prohlížeči (Playwright): `<img onerror>` i `javascript:` z odpovědi
modelu se zobrazí jako text a nespustí se.

## Nasazení (obhajoba): backend přes Cloudflare Quick Tunnel
Render ani Vercel nejdou: Python backend potřebuje trvalé `.agent-state/` (SQLite) a Render free
má dočasný disk a po 15 min usíná. Backend proto běží na počítači člena týmu a ven ho vystaví tunel.

1. `winget install --id Cloudflare.cloudflared`
2. `.env`: `CHAT_CLIENT_IP_HEADER=CF-Connecting-IP` a v `CHAT_ALLOWED_ORIGINS` doména webu
   (`https://festivaly-mas.vercel.app`).
3. Terminál 1: `cd agents` → `python -m chatbot.server --port 8787`
4. Terminál 2: `cloudflared tunnel --url http://127.0.0.1:8787` → vypíše `https://<náhodné>.trycloudflare.com`
5. Kontrola: `https://<náhodné>.trycloudflare.com/api/health` → `{"ok": true}`
6. Vercel → Settings → Environment Variables: `NEXT_PUBLIC_CHAT_API_URL=https://<náhodné>.trycloudflare.com`,
   pak **Redeploy** (proměnná `NEXT_PUBLIC_` se vkládá při buildu).

Adresa tunelu se mění při každém spuštění → kroky 4–6 zopakovat. Tunel nemá záruku dostupnosti:
záloha na obhajobě je lokální běh (`pnpm dev` + `http://127.0.0.1:3000`).
Na Vercel nepatří žádný klíč, jen veřejná adresa backendu.
