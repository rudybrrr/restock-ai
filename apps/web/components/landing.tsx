import Link from "next/link";
import { ArrowUpRight, Check } from "lucide-react";
import { Wordmark } from "./wordmark";
import "./restock.css";

export function Landing() {
  return (
    <div className="restock-site">
      <header className="site-nav">
        <Wordmark />
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
              <a href="#approach" className="text-link">
                Explore ReStock
              </a>
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
                  <h2>Ready for service.</h2>
                </div>
                <span className="mini-wordmark">ReStock.</span>
              </div>
              <div className="ledger-tabs">
                <strong>Kitchen stock</strong>
                <span>Incoming</span>
                <span>Purchase plan</span>
              </div>
              <div className="ledger-columns">
                <span>Ingredient</span>
                <span>Counted stock</span>
                <span>Unit</span>
              </div>
              {[
                ["Chicken", "17.000", "kg"],
                ["Rice", "25.000", "kg"],
                ["Eggs", "80", "pieces"],
                ["Vegetables", "12.000", "kg"],
              ].map(([name, qty, unit]) => (
                <div className="ledger-row" key={name}>
                  <span>{name}</span>
                  <strong>{qty}</strong>
                  <span>{unit}</span>
                </div>
              ))}
              <div className="ledger-footer">
                <Check size={16} />
                <span>Physical counts stay separate from estimates.</span>
              </div>
            </div>
            <div className="preview-footnote">
              <span>COUNT → PLAN → RECEIVE</span>
              <span>One clear record.</span>
            </div>
          </div>
        </section>
        <section className="approach-section" id="approach">
          <div className="section-heading">
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
              <article key={n}>
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
        <section className="closing-section">
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
