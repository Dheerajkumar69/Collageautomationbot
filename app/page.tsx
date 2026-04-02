"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, Terminal, CheckCircle2, AlertCircle, Play } from "lucide-react";

export default function Home() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isFinished, setIsFinished] = useState(false);
  const [logs, setLogs] = useState<{ type: string; msg: string }[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [logs]);

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;

    setIsRunning(true);
    setIsFinished(false);
    setLogs([{ type: "log", msg: "Connecting to automation server..." }]);

    try {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        throw new Error("Failed to start automation");
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) throw new Error("No stream available");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n\n').filter(Boolean);

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.substring(6);
            try {
              const data = JSON.parse(dataStr);
              if (data.type === "end") {
                setIsFinished(true);
                setIsRunning(false);
              } else {
                setLogs((prev) => [...prev, data]);
              }
            } catch (err) {
              console.error("Failed to parse SSE", dataStr);
            }
          }
        }
      }
    } catch (err: any) {
      setLogs((prev) => [...prev, { type: "error", msg: err.message || String(err) }]);
      setIsRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4 sm:p-8 font-sans selection:bg-indigo-500/30">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-[20%] -left-[10%] w-[50%] h-[50%] rounded-full bg-indigo-600/20 blur-[120px]" />
        <div className="absolute -bottom-[20%] -right-[10%] w-[50%] h-[50%] rounded-full bg-blue-600/20 blur-[120px]" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 w-full max-w-5xl grid grid-cols-1 lg:grid-cols-2 gap-8 items-start"
      >
        {/* Left Col: Form */}
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h1 className="text-4xl md:text-5xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
              LMS Auto-Feedback
            </h1>
            <p className="text-slate-400 text-lg">
              Automate your SSN LMS feedback submissions seamlessly. No separate backend required.
            </p>
          </div>

          <motion.div
            className="bg-slate-900/50 backdrop-blur-xl border border-white/10 p-6 md:p-8 rounded-2xl shadow-2xl"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
          >
            <form onSubmit={handleStart} className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-slate-300 ml-1">Registration Number</label>
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={isRunning}
                  placeholder="e.g. 210101010"
                  className="w-full bg-slate-950/50 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all disabled:opacity-50"
                />
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-sm font-medium text-slate-300 ml-1">Password</label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isRunning}
                  placeholder="••••••••"
                  className="w-full bg-slate-950/50 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all disabled:opacity-50"
                />
              </div>

              <button
                type="submit"
                disabled={isRunning || !username || !password}
                className="mt-2 w-full group relative flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-500 to-blue-600 hover:from-indigo-400 hover:to-blue-500 text-white font-semibold py-3.5 px-6 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_0_20px_rgba(79,70,229,0.3)] hover:shadow-[0_0_30px_rgba(79,70,229,0.5)] overflow-hidden"
              >
                {isRunning ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>Processing...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-5 h-5 fill-current" />
                    <span>Start Automation</span>
                  </>
                )}
                <div className="absolute inset-0 -translate-x-full group-hover:animate-[shimmer_1.5s_infinite] bg-gradient-to-r from-transparent via-white/20 to-transparent skew-x-12" />
              </button>
            </form>
          </motion.div>
        </div>

        {/* Right Col: Terminal Logs */}
        <motion.div
          className="h-[500px] flex flex-col bg-[#0d1117] border border-white/10 rounded-2xl shadow-2xl overflow-hidden relative"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
        >
          {/* Mac-like Header */}
          <div className="flex items-center gap-2 px-4 py-3 bg-white/[0.02] border-b border-white/5">
            <div className="flex gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-500/80" />
              <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <div className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <div className="flex-1 text-center flex items-center justify-center gap-2 text-xs font-medium text-slate-400">
              <Terminal className="w-4 h-4" />
              <span>automation-logs.sh</span>
            </div>
          </div>

          {/* Logs Area */}
          <div className="flex-1 overflow-y-auto p-4 font-mono text-sm">
            {logs.length === 0 && !isRunning && !isFinished && (
              <div className="h-full flex flex-col items-center justify-center text-slate-500 space-y-2 opacity-50">
                <Terminal className="w-12 h-12" />
                <p>Waiting for execution to start...</p>
              </div>
            )}

            <AnimatePresence>
              {logs.map((log, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={`mb-1.5 flex items-start gap-2 ${
                    log.type === "error" ? "text-red-400" :
                    log.msg.includes("[SUCCESS]") || log.msg.includes("✅") ? "text-green-400" :
                    log.msg.includes("[WARNING]") || log.msg.includes("[SKIPPED]") ? "text-yellow-400" :
                    "text-slate-300"
                  }`}
                >
                  <span className="text-slate-600 select-none shrink-0">
                    [{new Date().toLocaleTimeString([], { hour12: false })}]
                  </span>
                  <span className="break-all">{log.msg}</span>
                </motion.div>
              ))}
            </AnimatePresence>

            {isRunning && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-2 text-indigo-400 mt-4"
              >
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Operating automation sequence...</span>
              </motion.div>
            )}

            {isFinished && logs.length > 0 && !logs[logs.length - 1].msg.includes("Error") && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="mt-4 p-3 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center gap-3 text-green-400"
              >
                <CheckCircle2 className="w-5 h-5 shrink-0" />
                <span>Job fully completed and exited successfully.</span>
              </motion.div>
            )}

            <div ref={logsEndRef} />
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
