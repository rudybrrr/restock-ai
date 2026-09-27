"use client";
import Link from "next/link";
import { useRef, useState, useSyncExternalStore } from "react";

const key = "restock.quick-start.dismissed.v1";
const eventName = "restock:quick-start";
function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(eventName, listener);
  return () => { window.removeEventListener("storage", listener); window.removeEventListener(eventName, listener); };
}
function saved() { try { return localStorage.getItem(key) === "yes"; } catch { return false; } }

export function QuickStart() {
  const dialog = useRef<HTMLDialogElement>(null);
  const dismissed = useSyncExternalStore(subscribe, saved, () => false);
  const [closed, setClosed] = useState(false);
  function toggle(hide: boolean) {
    setClosed(hide);
    try { if (hide) localStorage.setItem(key, "yes"); else localStorage.removeItem(key); } catch { /* The guide still works when storage is unavailable. */ }
    window.dispatchEvent(new Event(eventName));
  }
  if (dismissed || closed) return <button className="guide-toggle" onClick={() => toggle(false)}>Show quick start</button>;
  return <>
    <section className="quick-start-prompt" aria-label="Getting started">
      <div><h2>New to ReStock?</h2><p>A short guide to your first day.</p></div>
      <button className="button button-secondary" onClick={() => dialog.current?.showModal()}>Open quick start</button>
      <button className="icon-button" aria-label="Dismiss quick start" onClick={() => toggle(true)}>✕</button>
    </section>
    <dialog ref={dialog} className="supplier-terms-dialog quick-start-dialog" aria-labelledby="quick-start-title" onClick={event => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
    }}>
    <header className="terms-header"><div><p className="eyebrow">GETTING STARTED</p><h2 id="quick-start-title">Your first day with ReStock</h2></div><button className="icon-button" aria-label="Close quick start" onClick={() => dialog.current?.close()}>✕</button></header>
    <div className="terms-body quick-start">
    <p>Start with the next-action banner on Today. Use these areas for the rest of your day.</p>
    <ol>
      <li><strong>During service</strong><p>Check stock and report sales for complete time intervals.</p><Link href="/workspace/sales">Open sales →</Link></li>
      <li><strong>When buying</strong><p>Review and approve a recommendation. Arrange the order yourself, then record the purchase and receipt.</p><Link href="/workspace/recommendations">Open purchasing →</Link></li>
      <li><strong>At closing</strong><p>Enter final sales and physical counts, then submit the closing update.</p><Link href="/workspace/daily">Open closing update →</Link></li>
    </ol>
    <p className="compact-note">Supplier changes and promotions belong in <Link href="/workspace/suppliers">Restaurant settings</Link>. Follow assessments in <Link href="/workspace/activity">Activity</Link>.</p>
    </div>
  </dialog></>;
}
