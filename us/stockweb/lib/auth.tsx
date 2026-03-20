"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";

// Semua request lewat Next.js proxy — tidak ada URL FastAPI di browser
const API = "/proxy";

interface AuthCtx {
  token: string | null;
  login: (u: string, p: string) => Promise<string | null>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({ token: null, login: async () => null, logout: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const t = localStorage.getItem("ssd_token");
    if (t) setToken(t);
  }, []);

  const login = async (username: string, password: string): Promise<string | null> => {
    try {
      const res = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) return "Username atau password salah";
      const data = await res.json();
      localStorage.setItem("ssd_token", data.access_token);
      setToken(data.access_token);
      return null;
    } catch {
      return "Tidak bisa terhubung ke server";
    }
  };

  const logout = () => {
    localStorage.removeItem("ssd_token");
    setToken(null);
  };

  return <Ctx.Provider value={{ token, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth() { return useContext(Ctx); }

export async function apiFetch(path: string, token: string) {
  const res = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}
