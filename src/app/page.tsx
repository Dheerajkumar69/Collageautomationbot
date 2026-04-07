"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type KeyboardEvent,
  type FormEvent,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────────────
type Status = "idle" | "running" | "done" | "error";

interface LogEntry {
  id: number;
  text: string;
  kind: "info" | "success" | "error" | "warn" | "divider" | "system";
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function classifyLog(text: string): LogEntry["kind"] {
  if (text.startsWith("─") || text.startsWith("—")) return "divider";
  if (/error|fail|exception|traceback|❌/i.test(text)) return "error";
  if (/warn|warning|⚠/i.test(text)) return "warn";
  if (/✅|success|done|complete|finish|submitt/i.test(text)) return "success";
  if (/⚡|connecting|connected|streaming/i.test(text)) return "system";
  return "info";
}

const LOG_COLORS: Record<LogEntry["kind"], string> = {
  info:    "text-zinc-300",
  success: "text-zinc-100",
  error:   "text-red-400",
  warn:    "text-amber-400",
  divider: "text-zinc-800",
  system:  "text-zinc-500",
};

// ── SVG Icons (inline, no extra deps) ─────────────────────────────────────────
function IconBot({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 2a2 2 0 0 1 2 2v2m-4 0V4a2 2 0 0 1 2-2m0 4H8a4 4 0 0 0-4 4v8a4 4 0 0 0 4 4h8a4 4 0 0 0 4-4v-8a4 4 0 0 0-4-4h-4Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h.01M15 12h.01M9 16h6" />
    </svg>
  );
}

function IconPlay({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5.14v14l11-7-11-7Z" />
    </svg>
  );
}

function IconStop({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function IconTerminal({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5 10.5 12l-3.75 4.5M13.5 16.5h3.75" />
      <rect x="2.25" y="3.75" width="19.5" height="16.5" rx="2.25" />
    </svg>
  );
}

function IconUser({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
    </svg>
  );
}

function IconLock({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
    </svg>
  );
}

function IconEye({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>
  );
}

function IconEyeOff({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
    </svg>
  );
}

function IconCopy({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
    </svg>
  );
}

function IconCheck({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
    </svg>
  );
}

function IconPalette({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.53 16.122a3 3 0 0 0-5.78 1.128 2.25 2.25 0 0 1-2.4 2.245 4.5 4.5 0 0 0 8.4-2.245c0-.399-.078-.78-.22-1.128Zm0 0a15.998 15.998 0 0 0 3.388-1.62m-5.043-.025a15.994 15.994 0 0 1 1.622-3.395m3.42 3.42a15.995 15.995 0 0 0 4.764-4.648l3.813-3.814a3.182 3.182 0 0 0-4.497-4.497l-3.813 3.814a15.996 15.996 0 0 0-4.648 4.764m4.496 4.496L12 12m0 0-3.42-3.42" />
    </svg>
  );
}

// ── Spinner SVG ────────────────────────────────────────────────────────────────
function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      className="animate-spin-slow"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        d="M12 3a9 9 0 0 1 9 9"
        strokeOpacity={0.9}
      />
      <path
        strokeLinecap="round"
        d="M12 3a9 9 0 0 0-9 9"
        strokeOpacity={0.25}
      />
    </svg>
  );
}

// ── Status badge ───────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: Status }) {
  const cfg = {
    idle:    { label: "Idle",    dot: "bg-zinc-600",       text: "text-zinc-500" },
    running: { label: "Running", dot: "bg-white",          text: "text-zinc-300", pulse: true },
    done:    { label: "Done",    dot: "bg-zinc-300",       text: "text-zinc-300" },
    error:   { label: "Error",   dot: "bg-red-500",        text: "text-red-500" },
  }[status];

  return (
    <span className={`flex items-center gap-1.5 text-[10px] font-mono ${cfg.text}`}>
      <span
        className={`w-1.5 h-1.5 rounded-full ${cfg.dot} ${cfg.pulse ? "animate-status-pulse" : ""}`}
      />
      {cfg.label}
    </span>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function Home() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass]  = useState(false);
  const [logs, setLogs]          = useState<LogEntry[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus]       = useState<Status>("idle");
  const [errorMsg, setErrorMsg]   = useState("");
  const [copied, setCopied]       = useState(false);

  // Themes
  const themes = ["dark", "light", "cat", "synthwave"];
  const [themeIdx, setThemeIdx] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", themes[themeIdx]);
  }, [themeIdx, themes]);

  const cycleTheme = () => setThemeIdx((prev) => (prev + 1) % themes.length);

  const bottomRef  = useRef<HTMLDivElement>(null);
  const abortRef   = useRef<AbortController | null>(null);
  const logIdRef   = useRef(0);
  const termRef    = useRef<HTMLDivElement>(null);

  // Auto-scroll terminal
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const addLog = useCallback((text: string) => {
    const entry: LogEntry = {
      id:   logIdRef.current++,
      text,
      kind: classifyLog(text),
    };
    setLogs((prev) => [...prev, entry]);
  }, []);

  // ── Copy logs to clipboard ─────────────────────────────────────────────────
  const handleCopyLogs = useCallback(async () => {
    const text = logs.map((l) => l.text).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback — select text in terminal
      if (termRef.current) {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(termRef.current);
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }
  }, [logs]);

  // ── Fetch & stream ─────────────────────────────────────────────────────────
  const handleStart = useCallback(
    async (e?: FormEvent) => {
      if (e) e.preventDefault();

      const u = username.trim();
      const p = password.trim();
      if (!u || !p || isRunning) return;

      // Reset
      setLogs([]);
      logIdRef.current = 0;
      setStatus("running");
      setIsRunning(true);
      setErrorMsg("");

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      addLog("⚡  Connecting to automation server…");

      try {
        const baseUrl =
          (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "") ||
          "http://localhost:8000";

        const response = await fetch(`${baseUrl}/api/run`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ username: u, password: p }),
          signal:  ctrl.signal,
        });

        if (!response.ok) {
          let errBody = "";
          try { errBody = await response.text(); } catch { /* empty */ }
          throw new Error(
            `Server returned ${response.status}${errBody ? `: ${errBody}` : ""}`
          );
        }

        if (!response.body) throw new Error("No response body received from server.");

        addLog("✅  Connected — streaming live logs:");
        addLog("─".repeat(50));

        const reader  = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let   buffer  = "";
        let   finished = false;
        let   failed = false;

        const processEvent = (data: string) => {
          if (data === "[DONE]") {
            addLog("─".repeat(50));
            addLog("✅  Automation completed successfully.");
            setStatus("done");
            finished = true;
            return;
          }

          if (data === "[FAILED]") {
            addLog("─".repeat(50));
            addLog("❌  Automation failed. See error logs above.");
            setErrorMsg("Automation failed. See terminal logs for details.");
            setStatus("error");
            failed = true;
            return;
          }

          addLog(data);
        };

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE messages are separated by double-newline
          const parts  = buffer.split("\n\n");
          buffer = parts.pop() ?? "";          // last may be partial

          for (const part of parts) {
            for (const line of part.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              const data = line.slice(6).trim();
              if (!data) continue;

              processEvent(data);
            }
          }
        }

        // Flush remaining buffer
        if (buffer.trim()) {
          for (const line of buffer.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const data = line.slice(6).trim();
            if (!data) continue;
            processEvent(data);
          }
        }

        if (!finished && !failed) {
          const message = "Automation stream ended unexpectedly before completion.";
          addLog(`❌  ${message}`);
          setErrorMsg(message);
          setStatus("error");
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          addLog("⛔  Automation stopped by user.");
          setStatus("idle");
        } else {
          const msg = err instanceof Error ? err.message : String(err);
          setErrorMsg(msg);
          addLog(`❌  Error: ${msg}`);
          setStatus("error");
        }
      } finally {
        setIsRunning(false);
        abortRef.current = null;
      }
    },
    [username, password, isRunning, addLog]
  );

  const handleStop = () => abortRef.current?.abort();

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") { e.preventDefault(); handleStart(); }
  };

  const canSubmit = username.trim().length > 0 && password.trim().length > 0 && !isRunning;

  // ── JSX ────────────────────────────────────────────────────────────────────
  return (
    <main className="relative z-10 min-h-screen w-full flex flex-col items-center justify-center p-4 sm:p-8 py-12 transition-colors duration-300">
      
      {/* ── Theme Switcher ────────────────────────────────────────────────── */}
      <button
        onClick={cycleTheme}
        className="absolute top-4 right-4 sm:top-8 sm:right-8 flex items-center gap-2 px-3 py-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] hover:bg-[var(--bg-input)] transition-all duration-200 shadow-sm z-50 text-[var(--text-primary)]"
        aria-label="Switch theme"
        title={`Current theme: ${themes[themeIdx]}`}
      >
        <IconPalette className="w-4 h-4 text-[var(--color-accent)]" />
        <span className="text-xs font-medium uppercase tracking-widest hidden sm:inline-block">Theme: {themes[themeIdx]}</span>
      </button>

      {/* ── Hero text ─────────────────────────────────────────────────────── */}
      <div className="mb-10 text-center animate-fade-in-up">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-muted)] text-xs font-medium mb-5 tracking-wide shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--border-focus)]" />
          Adamas University · LMS Automation
        </div>

        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight text-[var(--text-primary)] mb-3 transition-colors duration-300">
          Auto&#8209;Feedback Bot
        </h1>
        <p className="text-base sm:text-lg text-[var(--text-dim)] max-w-md mx-auto leading-relaxed transition-colors duration-300">
          Submit all LMS feedback forms in seconds. Fully headless &amp; automated — watch it run live.
        </p>
      </div>

      {/* ── Two-column grid ───────────────────────────────────────────────── */}
      <div className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-6 lg:gap-8 items-start">

        {/* ─── LEFT: Form panel ─────────────────────────────────────────── */}
        <div
          className="glass-card p-6 sm:p-8 flex flex-col gap-6 shadow-2xl animate-fade-in-up"
          style={{ animationDelay: "80ms" }}
        >
          {/* Form */}
          <form onSubmit={handleStart} className="flex flex-col gap-5 pt-2" noValidate>

            {/* Registration Number */}
            <div className="flex flex-col gap-2">
              <label htmlFor="regNumber" className="text-xs font-medium text-[var(--text-dim)] tracking-wide">
                Registration Number
              </label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--text-muted)]">
                  <IconUser className="w-4 h-4" />
                </span>
                <input
                  id="regNumber"
                  name="username"
                  type="text"
                  required
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="e.g. BCA2024001"
                  disabled={isRunning}
                  spellCheck={false}
                  className="
                    input-field w-full
                    bg-[var(--bg-input)] border border-[var(--border)] rounded-xl
                    pl-10 pr-4 py-3
                    text-[var(--text-primary)] text-sm placeholder-[var(--text-muted)]
                    transition-all duration-200
                    disabled:opacity-50 disabled:cursor-not-allowed
                    font-mono tracking-wide
                  "
                />
              </div>
            </div>

            {/* Password */}
            <div className="flex flex-col gap-2">
              <label htmlFor="lmsPassword" className="text-xs font-medium text-[var(--text-dim)] tracking-wide">
                Password
              </label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--text-muted)]">
                  <IconLock className="w-4 h-4" />
                </span>
                <input
                  id="lmsPassword"
                  name="password"
                  type={showPass ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="••••••••"
                  disabled={isRunning}
                  className="
                    input-field w-full
                    bg-[var(--bg-input)] border border-[var(--border)] rounded-xl
                    pl-10 pr-11 py-3
                    text-[var(--text-primary)] text-sm placeholder-[var(--text-muted)]
                    transition-all duration-200
                    disabled:opacity-50 disabled:cursor-not-allowed
                  "
                />
                <button
                  type="button"
                  aria-label={showPass ? "Hide password" : "Show password"}
                  onClick={() => setShowPass((v) => !v)}
                  tabIndex={-1}
                  className="
                    absolute right-3 top-1/2 -translate-y-1/2
                    text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors duration-150
                    focus:outline-none
                  "
                >
                  {showPass ? (
                    <IconEyeOff className="w-4 h-4" />
                  ) : (
                    <IconEye className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            {/* Error banner */}
            {errorMsg && (
              <div
                role="alert"
                className="
                  bg-red-500/10 border border-red-500/20 rounded-xl
                  px-4 py-3 text-red-400 text-xs font-mono break-words
                  leading-relaxed
                "
              >
                <span className="font-semibold">Error: </span>
                {errorMsg}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-3 pt-1">
              <button
                id="startBtn"
                type="submit"
                disabled={!canSubmit}
                className="
                  btn-primary flex-1 rounded-xl
                  py-3.5 px-5
                  text-white text-sm font-semibold
                  flex items-center justify-center gap-2
                  disabled:cursor-not-allowed
                "
              >
                {isRunning ? (
                  <>
                    <Spinner size={15} />
                    Running…
                  </>
                ) : (
                  <>
                    <IconPlay className="w-4 h-4" />
                    Start Automation
                  </>
                )}
              </button>

              {isRunning && (
                <button
                  id="stopBtn"
                  type="button"
                  onClick={handleStop}
                  className="btn-danger rounded-xl py-3.5 px-4 text-white text-sm font-semibold flex items-center gap-2 cursor-pointer"
                >
                  <IconStop className="w-4 h-4" />
                  Stop
                </button>
              )}
            </div>
          </form>

          {/* Info note */}
          <div className="text-[11px] text-[var(--text-muted)] leading-relaxed pt-1">
            <span className="text-[var(--color-accent)] mr-1">ℹ</span>
            Your credentials are sent directly to the automation server and are never stored or logged anywhere.
          </div>
        </div>

        {/* ─── RIGHT: Terminal panel ────────────────────────────────────── */}
        <div
          className="flex flex-col h-[520px] sm:h-[580px] rounded-2xl border border-[var(--terminal-border)] bg-[var(--terminal-bg)] shadow-2xl overflow-hidden animate-fade-in-up"
          style={{ animationDelay: "160ms" }}
        >
          {/* Title bar */}
          <div className="flex items-center px-4 py-3 border-b border-[var(--terminal-border)] bg-[var(--terminal-header)] shrink-0 gap-3">
            {/* Traffic lights */}
            <div className="flex items-center gap-1.5 opacity-80">
              <div className="w-3 h-3 rounded-full bg-[#ff5f57] border border-black/10" />
              <div className="w-3 h-3 rounded-full bg-[#febc2e] border border-black/10" />
              <div className="w-3 h-3 rounded-full bg-[#28c840] border border-black/10" />
            </div>

            {/* Title */}
            <div className="flex-1 flex items-center justify-center gap-1.5 text-xs font-mono text-zinc-500">
              <IconTerminal className="w-3.5 h-3.5" />
              automation-logs
            </div>

            {/* Right side: status + copy */}
            <div className="flex items-center gap-3">
              <StatusBadge status={status} />

              {logs.length > 0 && (
                <button
                  type="button"
                  aria-label="Copy logs"
                  onClick={handleCopyLogs}
                  className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors duration-150 focus:outline-none"
                  title="Copy all logs"
                >
                  {copied ? (
                    <IconCheck className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <IconCopy className="w-3.5 h-3.5" />
                  )}
                </button>
              )}
            </div>
          </div>

          {/* Log area */}
          <div
            ref={termRef}
            className="flex-1 overflow-y-auto p-4 font-mono text-[12.5px] leading-[1.65] scroll-smooth"
            aria-live="polite"
            aria-label="Automation log output"
          >
            {logs.length === 0 ? (
              /* Empty state */
              <div className="h-full flex flex-col items-center justify-center text-[var(--text-muted)] select-none gap-4">
                <IconTerminal className="w-10 h-10 opacity-50" />
                <div className="text-center">
                  <p className="text-sm text-[var(--text-dim)] mb-1">Waiting for execution…</p>
                  <p className="text-xs text-[var(--text-muted)] opacity-60">
                    Enter credentials and press{" "}
                    <kbd className="bg-[var(--border)] px-1.5 py-0.5 rounded text-[var(--text-primary)]">Start</kbd>
                  </p>
                </div>

                {/* Fake typing cursor */}
                <span className="text-[var(--color-accent)] text-base animate-blink">▊</span>
              </div>
            ) : (
              <div className="flex flex-col gap-[2px] pb-2">
                {logs.map((entry) => (
                  <div key={entry.id} className={`terminal-log-line ${LOG_COLORS[entry.kind]}`}>
                    {entry.kind !== "divider" && (
                      <span className="terminal-prompt select-none shrink-0">›</span>
                    )}
                    <span className="break-words whitespace-pre-wrap flex-1">
                      {entry.text}
                    </span>
                  </div>
                ))}

                {/* Running cursor */}
                {isRunning && (
                  <div className="terminal-log-line text-[var(--color-accent)] opacity-60">
                    <span className="terminal-prompt select-none">›</span>
                    <span className="animate-blink">▊</span>
                  </div>
                )}

                <div ref={bottomRef} />
              </div>
            )}
          </div>

          {/* Footer bar */}
          <div className="shrink-0 border-t border-[var(--terminal-border)] bg-[var(--terminal-header)] px-4 py-2 flex items-center justify-between">
            <span className="text-[10px] font-mono text-[var(--text-muted)] opacity-70">
              {logs.filter((l) => l.kind !== "divider" && l.kind !== "system").length} lines
            </span>
            {status === "done" && (
              <span className="text-[10px] font-mono text-emerald-400/60">
                ✓ Finished
              </span>
            )}
            {status === "error" && (
              <span className="text-[10px] font-mono text-red-400/60">
                ✗ Error — check logs above
              </span>
            )}
          </div>
        </div>

      </div>

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <p className="mt-10 text-center text-[11px] text-[var(--text-muted)] animate-fade-in-up" style={{ animationDelay: "300ms" }}>
        LMS Auto-Feedback · Runs headless Playwright in the cloud · No data is stored
      </p>
    </main>
  );
}
