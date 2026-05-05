import { useEffect, useState } from "react";

import {
  getChromeStatus,
  getScraperHealth,
  launchChrome,
  type ChromeStatus,
  type ScraperHealth,
} from "../api";

export default function ScraperHealthPanel() {
  const [chromeStatus, setChromeStatus] = useState<ChromeStatus | null>(null);
  const [health, setHealth] = useState<ScraperHealth | null>(null);
  const [launching, setLaunching] = useState(false);

  async function checkChromeStatus() {
    try {
      const [status, h] = await Promise.all([getChromeStatus(), getScraperHealth()]);
      setChromeStatus(status);
      setHealth(h);
    } catch {
      setChromeStatus({ connected: false, error: "status check failed" });
    }
  }

  useEffect(() => {
    checkChromeStatus();
    const interval = window.setInterval(checkChromeStatus, 5000);
    return () => {
      window.clearInterval(interval);
    };
  }, []);

  async function handleLaunchChrome() {
    setLaunching(true);
    try {
      const data = await launchChrome();
      if (data.status === "launched" || data.status === "already_running") {
        await checkChromeStatus();
      } else {
        // keep UI simple; status banner refreshes every 5s
      }
    } finally {
      setLaunching(false);
    }
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-ink-900/70 p-4">
      {chromeStatus?.connected ? (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-200">
          <span>●</span>
          <span>Chrome connected · {chromeStatus.browser || ""} · Bot detection bypassed</span>
        </div>
      ) : (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
          <div>
            <p className="font-semibold">Chrome not connected</p>
            <p className="mt-1 text-[11px] text-rose-200/90">
              OS: {chromeStatus?.os || "unknown"} · Binary:{" "}
              {chromeStatus?.binary || chromeStatus?.binary_found || "(not detected)"}
            </p>
          </div>
          <button
            type="button"
            onClick={handleLaunchChrome}
            disabled={launching}
            className="rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-slate-900 disabled:opacity-70"
          >
            {launching ? "Launching..." : "Launch Chrome"}
          </button>
        </div>
      )}
      <h3 className="text-sm font-semibold text-white">Scraper Health</h3>
      <div className="mt-2 text-xs text-slate-300">
        <p className="mb-1 flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${chromeStatus?.connected ? "bg-emerald-400" : "bg-rose-400"}`} />
          <span className="font-semibold text-slate-200">Chrome Connection</span>
          {chromeStatus?.connected ? (
            <span className="text-emerald-300">{chromeStatus.browser || "Connected"}</span>
          ) : (
            <span className="text-rose-300">Disconnected</span>
          )}
        </p>
        {chromeStatus?.connected ? <p className="mt-2 text-emerald-300">Using real Chrome session via CDP</p> : null}
        <p className="mt-2">
          Browser mode: <span className="text-slate-100">{health?.browser_mode || "unknown"}</span>
        </p>
      </div>
    </section>
  );
}
