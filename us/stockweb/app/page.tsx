"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth, AuthProvider } from "@/lib/auth";

function LoginForm() {
  const { token, login } = useAuth();
  const router  = useRouter();
  const [user, setUser]     = useState("");
  const [pass, setPass]     = useState("");
  const [err, setErr]       = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady]   = useState(false);

  useEffect(() => { setReady(true); }, []);

  useEffect(() => {
    if (ready && token) router.replace("/dashboard");
  }, [ready, token, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setLoading(true);
    const error = await login(user, pass);
    setLoading(false);
    if (error) setErr(error);
    else router.replace("/dashboard");
  };

  if (!ready) return null;
  if (token)  return null;

  return (
    <div className="min-h-screen grid-bg flex items-center justify-center relative overflow-hidden">
      <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full bg-accent/5 blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-64 h-64 rounded-full bg-bull/5 blur-3xl pointer-events-none" />
      <div className="w-full max-w-sm px-4 fade-up">
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-2 h-2 rounded-full bg-bull glow-pulse" />
            <span className="ticker-tag text-xs text-dim tracking-widest uppercase">US Equity System</span>
            <div className="w-2 h-2 rounded-full bg-bull glow-pulse" />
          </div>
          <h1 className="ticker-tag text-3xl font-bold text-text mb-1">SSD</h1>
          <p className="text-dim text-xs tracking-wider">Stock Scoring Dashboard</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="bg-card border border-border rounded-lg p-6 space-y-4">
            <div>
              <label className="block text-xs text-dim mb-2 tracking-wider uppercase">Username</label>
              <input type="text" value={user} onChange={e => setUser(e.target.value)}
                className="w-full bg-surface border border-border rounded px-3 py-2.5 text-sm text-text placeholder:text-muted focus:outline-none focus:border-accent/60 transition-colors font-mono"
                placeholder="username" autoComplete="username" required />
            </div>
            <div>
              <label className="block text-xs text-dim mb-2 tracking-wider uppercase">Password</label>
              <input type="password" value={pass} onChange={e => setPass(e.target.value)}
                className="w-full bg-surface border border-border rounded px-3 py-2.5 text-sm text-text placeholder:text-muted focus:outline-none focus:border-accent/60 transition-colors font-mono"
                placeholder="••••••••" autoComplete="current-password" required />
            </div>
            {err && (
              <div className="flex items-center gap-2 text-bear text-xs bg-bear-dim border border-bear/20 rounded px-3 py-2">
                <span>⚠</span> {err}
              </div>
            )}
            <button type="submit" disabled={loading}
              className="w-full bg-accent/10 hover:bg-accent/20 border border-accent/30 hover:border-accent/60 text-accent rounded py-2.5 text-sm font-mono tracking-wider transition-all disabled:opacity-40 disabled:cursor-not-allowed">
              {loading ? <span className="cursor-blink">AUTHENTICATING</span> : "SIGN IN →"}
            </button>
          </div>
        </form>
        <p className="text-center text-muted text-xs mt-6">Restricted access · Internal use only</p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <AuthProvider><LoginForm /></AuthProvider>;
}
