"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { safeUrl } from "../lib/festivals";

// Veřejná adresa backendu chatbota (není tajemství). Klíč Gemini zůstává jen na serveru.
const API_URL = (process.env.NEXT_PUBLIC_CHAT_API_URL || "").replace(/\/+$/, "");
const MAX_CHARS = 500;
const HISTORY_TURNS = 6;
const URL_RE = /(https?:\/\/[^\s<>()"']+[^\s<>()"'.,;:!?])/g;

type ChatFestival = { id: string; name: string | null; website: string | null; sources: string[] };
type SearchRequest = { queued: boolean; already_pending?: boolean; reason?: string; note?: string };
type Message = {
  role: "user" | "model";
  text: string;
  festivals?: ChatFestival[];
  searchRequests?: SearchRequest[];
  error?: boolean;
};

const EXAMPLES = [
  "Metal festivals in Czechia in summer 2027?",
  "Which festivals have an open call for bands?",
  "Punkové festivaly na Slovensku v roce 2027?",
];

function errorText(status: number): string {
  if (status === 429) return "Too many questions in a short time. Please wait a minute and try again.";
  if (status === 400) return "The question could not be processed. Keep it under 500 characters.";
  if (status === 403) return "This website is not allowed to use the assistant.";
  return "The assistant is not available right now. Please try again later.";
}

/** Odpověď modelu jako prostý text; odkazy jen http(s), React vše escapuje (žádné innerHTML). */
function LinkedText({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <>
      {parts.map((part, i) => {
        const href = i % 2 === 1 ? safeUrl(part) : undefined;
        return href ? (
          <a key={i} href={href} target="_blank" rel="noopener noreferrer nofollow">
            {part}
          </a>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </>
  );
}

function SourceList({ festivals }: { festivals: ChatFestival[] }) {
  const items = festivals
    .map((f) => ({ ...f, href: safeUrl(f.website) || safeUrl(f.sources[0] ?? null) }))
    .filter((f) => f.href);
  if (!items.length) return null;
  return (
    <details className="chat-sources">
      <summary>Sources ({items.length})</summary>
      <ul>
        {items.map((f) => (
          <li key={f.id}>
            <a href={f.href} target="_blank" rel="noopener noreferrer nofollow">
              {f.name || f.id}
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}

function SearchNote({ requests }: { requests: SearchRequest[] }) {
  const r = requests[0];
  if (!r) return null;
  const text = r.queued
    ? r.already_pending
      ? "A search for this area is already waiting in the queue."
      : r.note
        ? "Your search request was recorded. Automatic searching for this kind of data is not running yet."
        : "A search for missing data was requested. New results appear after validation."
    : `No search was requested${r.reason ? `: ${r.reason}` : "."}`;
  return <p className="chat-note">{text}</p>;
}

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, busy]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  async function ask(question: string) {
    const message = question.trim();
    if (!message || busy || message.length > MAX_CHARS) return;
    const history = messages
      .filter((m) => !m.error)
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, text: m.text }));
    setMessages((prev) => [...prev, { role: "user", text: message }]);
    setInput("");
    if (!API_URL) {
      setMessages((prev) => [...prev, { role: "model", text: "The assistant is not configured on this site yet.", error: true }]);
      return;
    }
    setBusy(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60_000);
    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(errorText(res.status));
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "model",
          text: typeof data.answer === "string" ? data.answer : "",
          festivals: Array.isArray(data.festivals) ? data.festivals : [],
          searchRequests: Array.isArray(data.search_requests) ? data.search_requests : [],
        },
      ]);
    } catch (err) {
      const text =
        err instanceof Error && err.message && err.name !== "AbortError" && err.name !== "TypeError"
          ? err.message
          : "The assistant could not be reached. Please try again later.";
      setMessages((prev) => [...prev, { role: "model", text, error: true }]);
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(input);
  }

  return (
    <>
      <button
        type="button"
        className="chat-launcher"
        aria-expanded={open}
        aria-controls="chat-panel"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Close" : "Ask the assistant"}
      </button>
      {open && (
        <section id="chat-panel" className="chat-panel" aria-label="Festival assistant">
          <header className="chat-head">
            <div>
              <strong>Festival assistant</strong>
              <p>Answers come only from validated festival data, with sources.</p>
            </div>
            <button type="button" className="chat-close" aria-label="Close assistant" onClick={() => setOpen(false)}>
              ×
            </button>
          </header>

          <div className="chat-log" ref={listRef} aria-live="polite">
            {messages.length === 0 && (
              <div className="chat-empty">
                <p>Ask about festivals in Czechia and Slovakia by genre, place or season.</p>
                {EXAMPLES.map((q) => (
                  <button key={q} type="button" className="chat-example" onClick={() => void ask(q)}>
                    {q}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg chat-${m.role}${m.error ? " chat-error" : ""}`}>
                <p className="chat-text">
                  {m.role === "model" && !m.error ? <LinkedText text={m.text} /> : m.text}
                </p>
                {m.searchRequests && <SearchNote requests={m.searchRequests} />}
                {m.festivals && <SourceList festivals={m.festivals} />}
              </div>
            ))}
            {busy && <p className="chat-msg chat-model chat-typing">Thinking…</p>}
          </div>

          <form className="chat-form" onSubmit={onSubmit}>
            <textarea
              ref={inputRef}
              value={input}
              maxLength={MAX_CHARS}
              rows={2}
              placeholder="e.g. Indie festivals in Slovakia in July 2027"
              aria-label="Your question"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask(input);
                }
              }}
            />
            <div className="chat-form-row">
              <span className="chat-count">
                {input.length}/{MAX_CHARS}
              </span>
              <button type="submit" className="primary-button" disabled={busy || !input.trim()}>
                Send
              </button>
            </div>
          </form>
        </section>
      )}
    </>
  );
}
