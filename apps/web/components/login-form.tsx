"use client";
import { Suspense, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { api, Identity } from "@/lib/api";
import { SessionNotice } from "./session-notice";
import { Wordmark } from "./wordmark";
import "./restock.css";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const result = await api<Identity>("/auth/login", {
        method: "POST",
        body: {
          username: data.get("username"),
          password: data.get("password"),
        },
      });
      if (result.role !== "manager")
        throw new Error("Please use the manager account.");
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(
        next?.startsWith("/workspace/") && !next.includes("\\")
          ? next
          : "/workspace/overview",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in.");
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="restock-app login-page">
      <section className="login-story">
        <Wordmark />
        <div>
          <p className="eyebrow">FROM COUNT TO COUNTER</p>
          <h1>
            A good day starts
            <br />
            with things
            <br />
            <em>in order.</em>
          </h1>
          <p>
            Your kitchen stock, purchasing plans, and deliveries.
            <br />
            One place to keep the day moving.
          </p>
        </div>
        <small>Restaurant inventory & purchasing</small>
      </section>
      <main className="login-main">
        <Link href="/" className="back-link">
          ← Back to ReStock
        </Link>
        <form onSubmit={submit} className="login-form">
          <p className="eyebrow">YOUR WORKSPACE</p>
          <h2>Welcome back.</h2>
          <Suspense>
            <SessionNotice />
          </Suspense>
          <p>Sign in to see what needs your attention.</p>
          <label>
            Username
            <input name="username" autoComplete="username" required autoFocus />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          {error && (
            <p role="alert" className="notice notice-error">
              {error}
            </p>
          )}
          <button
            disabled={pending}
            className="button button-primary"
            type="submit"
          >
            {pending ? "Signing in…" : "Sign in"}
            <ArrowRight size={17} />
          </button>
          <small>Use the manager account configured for your restaurant.</small>
        </form>
      </main>
    </div>
  );
}
