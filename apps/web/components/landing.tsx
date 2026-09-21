"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUpRight, Check } from "lucide-react";
import { Wordmark } from "./wordmark";
import "./restock.css";
import "./landing.css";

const previews = [
  {
    label: "Kitchen stock",
    title: "Ready for service.",
    columns: ["Ingredient", "Counted stock", "Unit"],
    rows: [
      ["Chicken", "17.000", "kg"],
      ["Rice", "25.000", "kg"],
      ["Eggs", "80", "pieces"],
      ["Vegetables", "12.000", "kg"],
    ],
    note: "Physical counts stay separate from estimates.",
  },
  {
    label: "Incoming",
    title: "Know what’s next.",
    columns: ["Ingredient", "Expected arrival", "Quantity"],
    rows: [
      ["Chicken", "Today, 10 am", "5 kg"],
      ["Vegetables", "Today, 11 am", "8 kg"],
      ["Rice", "Tomorrow", "10 kg"],
      ["Eggs", "Tomorrow", "60 pieces"],
    ],
    note: "Arranged purchases are not stock until received.",
  },
  {
    label: "Purchase plan",
    title: "Your call, clearly.",
    columns: ["Ingredient", "Suggested quantity", "Supplier"],
    rows: [
      ["Chicken", "5 kg", "Fresh"],
      ["Rice", "10 kg", "Pantry"],
      ["Tofu", "4 kg", "Market"],
      ["Oil", "3 litres", "Pantry"],
    ],
    note: "A recommendation, not an order. You decide.",
  },
];

export function Landing() {
  const [preview, setPreview] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const selected = previews[preview];
  useEffect(() => {
    const nodes = root.current?.querySelectorAll<HTMLElement>("[data-reveal]");
    if (!nodes || matchMedia("(prefers-reduced-motion: reduce)").matches)
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );
    nodes.forEach((node) => {
      node.classList.add("reveal-ready");
      observer.observe(node);
    });
    return () => observer.disconnect();
  }, []);
  return (
    <div className="restock-site landing-dynamic" ref={root}>
      <header className="site-nav">
        <Wordmark showIcon />
        <nav aria-label="Main navigation">
          <a href="#approach">Our approach</a>
          <a href="#workspace">The workspace</a>
          <Link className="button button-dark" href="/login">
            Manager login
          </Link>
        </nav>
      </header>
      <main id="main-content">
        <section className="landing-hero">
          <div className="hero-copy">
            <p className="eyebrow">A little more order in your kitchen</p>
            <h1>
              Good service starts
              <br />
              with the right <em>stock.</em>
            </h1>
            <p className="hero-description">
              Keep an eye on your ingredients, plan your next purchase, and stay
              ready when the day changes. Your restaurant, all in order.
            </p>
            <div className="hero-actions">
              <Link href="/login" className="button button-primary">
                Open workspace
              </Link>
            </div>
            <p className="quiet hero-note">
              You make the decisions. ReStock keeps the details together.
            </p>
          </div>
          <div className="preview-wrap" id="workspace">
            <div className="preview-label">
              Inside ReStock <span>Illustrative preview</span>
            </div>
            <div className="ledger-preview">
              <div className="ledger-heading">
                <div>
                  <p className="eyebrow">MONDAY, 16 FEBRUARY</p>
                  <h2>{selected.title}</h2>
                </div>
                <span className="mini-wordmark">ReStock.</span>
              </div>
              <div
                className="ledger-tabs"
                aria-label="Explore illustrative workspace"
              >
                {previews.map((item, index) => (
                  <button
                    key={item.label}
                    type="button"
                    aria-pressed={preview === index}
                    onClick={() => setPreview(index)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <div key={preview} className="preview-content" aria-live="polite">
                <div className="ledger-columns">
                  {selected.columns.map((column) => (
                    <span key={column}>{column}</span>
                  ))}
                </div>
                {selected.rows.map(([name, qty, unit]) => (
                  <div className="ledger-row" key={name}>
                    <span>{name}</span>
                    <strong>{qty}</strong>
                    <span>{unit}</span>
                  </div>
                ))}
                <div className="ledger-footer">
                  <Check size={16} />
                  <span>{selected.note}</span>
                </div>
              </div>
            </div>
            <div className="service-note">
              <span className="service-dot" /> THE SERVICE BOARD{" "}
              <span>Try the three views above ↗</span>
            </div>
            <div className="preview-footnote">
              <span>COUNT → PLAN → RECEIVE</span>
              <span>One clear record.</span>
            </div>
          </div>
          <a className="hero-scroll" href="#approach" aria-label="Explore ReStock" title="Explore ReStock">
            <ArrowDown size={26} strokeWidth={1.5} aria-hidden="true" />
          </a>
        </section>
        <section className="approach-section" id="approach">
          <div className="section-heading" data-reveal>
            <p className="eyebrow">Built around a working kitchen</p>
            <h2>
              From the first count
              <br />
              to the next delivery.
            </h2>
            <p>
              Less time piecing information together.
              <br />
              More clarity about what comes next.
            </p>
          </div>
          <div className="approach-list">
            {[
              [
                "01",
                "Know what’s on hand",
                "See your physical counts, sales-based estimates, and expiry dates together. Always know which numbers were counted and which were calculated.",
              ],
              [
                "02",
                "Buy with a clear plan",
                "Review quantities, suppliers, arrivals, and costs before approving a recommendation. Record the purchase once you have arranged it.",
              ],
              [
                "03",
                "Keep up with the day",
                "Track partial deliveries and supplier changes, and review assessments as conditions change. Existing purchases stay in the picture.",
              ],
            ].map(([n, title, body]) => (
              <article key={n} data-reveal>
                <span className="step-number">{n}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
                <ArrowUpRight size={20} />
              </article>
            ))}
          </div>
        </section>
        <section className="closing-section" data-reveal>
          <div>
            <p className="eyebrow">A clearer view of the everyday</p>
            <h2>
              Your next service,
              <br />a little more considered.
            </h2>
          </div>
          <Link href="/login" className="button button-light">
            Open workspace
          </Link>
        </section>
      </main>
      <footer className="site-footer">
        <Wordmark />
        <span>Restaurant inventory & purchasing</span>
        <span>Made for the everyday.</span>
      </footer>
    </div>
  );
}
