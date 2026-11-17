"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export default function SiteHeader() {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const prefersDark = localStorage.getItem("festivaly-theme") === "dark";
    document.documentElement.dataset.theme = prefersDark ? "dark" : "light";
    setDark(prefersDark);
  }, []);

  function toggleTheme() {
    const theme = dark ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("festivaly-theme", theme);
    setDark(!dark);
  }

  return (
    <header className="topbar">
      <Link className="brand" href="/" aria-label="Festivaly home">
        <span className="brand-mark" aria-hidden="true">
          f.
        </span>
        festivaly<span className="brand-dot">.</span>
      </Link>
      <nav className="site-nav" aria-label="Main navigation">
        <Link
          href="/festivals"
          aria-current={pathname === "/festivals" ? "page" : undefined}
        >
          All festivals
        </Link>
        <Link
          href="/gigs"
          aria-current={pathname === "/gigs" ? "page" : undefined}
        >
          Gigs
        </Link>
        <Link
          href="/dataset"
          aria-current={pathname === "/dataset" ? "page" : undefined}
        >
          About
        </Link>
        <button
          className="theme-toggle"
          type="button"
          aria-pressed={dark}
          onClick={toggleTheme}
        >
          <span aria-hidden="true">{dark ? "☀" : "☾"}</span>
          <span>Dark mode</span>
        </button>
      </nav>
    </header>
  );
}
