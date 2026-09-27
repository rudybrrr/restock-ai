"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { tourSteps, tourStorageKey } from "@/lib/workspace-tour";
import "./workspace-tour.css";

type Highlight = { top: number; left: number; width: number; height: number };

export function WorkspaceTour({ username }: { username: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const currentPath = params.toString() ? `${pathname}?${params}` : pathname;
  // -1 is the welcome slide; null means closed.
  const [index, setIndex] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const replay = useRef<HTMLButtonElement>(null);
  const origin = useRef<string | null>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const step = index !== null && index >= 0 ? tourSteps[index] : null;
  const key = tourStorageKey(username);

  useEffect(() => {
    let seen = false;
    try { seen = !!localStorage.getItem(key); } catch { /* Storage may be disabled. Tour still works. */ }
    if (seen) return;
    const timer = window.setTimeout(() => {
      restoreFocus.current = document.activeElement as HTMLElement;
      setIndex(-1);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [key]);

  useEffect(() => {
    if (index === null) return;
    const element = dialog.current;
    if (!element) return;
    element.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    heading.current?.focus();
    return () => {
      element.close();
      document.body.style.overflow = previousOverflow;
    };
  }, [index]);

  useEffect(() => {
    if (!step) return;
    const update = () => {
      if (currentPath !== step.href) { setHighlight(null); return; }
      // Spotlight the actual page tab; Today/Activity use their area introduction.
      const target = document.querySelector<HTMLElement>(`.area-tabs a[href="${step.href}"]`) ?? document.querySelector<HTMLElement>(".area-intro");
      if (!target) { setHighlight(null); return; }
      const rect = target.getBoundingClientRect();
      const next = { top: Math.max(8, rect.top - 6), left: Math.max(8, rect.left - 6), width: Math.min(rect.width + 12, window.innerWidth - 16), height: Math.min(rect.height + 12, 190) };
      setHighlight(previous => previous && Object.keys(next).every(k => previous[k as keyof Highlight] === next[k as keyof Highlight]) ? previous : next);
    };
    const frame = requestAnimationFrame(update);
    const timer = window.setInterval(update, 150);
    window.addEventListener("resize", update);
    return () => { cancelAnimationFrame(frame); window.clearInterval(timer); window.removeEventListener("resize", update); };
  }, [step, currentPath]);

  function finish() {
    try { localStorage.setItem(key, "seen"); } catch { /* Browser-local preference only. */ }
    setIndex(null);
    setHighlight(null);
    if (origin.current) router.replace(origin.current);
    origin.current = null;
    requestAnimationFrame(() => {
      const target = restoreFocus.current;
      if (target?.isConnected && target !== document.body) target.focus();
      else replay.current?.focus();
    });
  }

  function go(next: number) {
    if (next >= tourSteps.length) { finish(); return; }
    if (origin.current === null) origin.current = currentPath;
    setHighlight(null);
    setIndex(next);
    router.replace(tourSteps[next].href);
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  return <>
    <button ref={replay} type="button" className="tour-replay" onClick={() => {
      restoreFocus.current = document.activeElement as HTMLElement;
      setIndex(-1);
    }}>Workspace tour</button>
    {index !== null && <dialog ref={dialog} className="workspace-tour" aria-labelledby="tour-title" aria-describedby="tour-description" onCancel={event => { event.preventDefault(); finish(); }}>
      {step && highlight && <div className="tour-spotlight" aria-hidden="true" style={highlight} />}
      <section className={`tour-card ${step ? "" : "tour-welcome"}`} style={highlight ? { "--tour-clearance": `${highlight.top + highlight.height + 32}px` } as CSSProperties : undefined}>
        <div className="tour-top"><span>{step ? `${index + 1} / ${tourSteps.length} · ${step.area}` : "WELCOME TO RESTOCK"}</span><button type="button" className="tour-skip" onClick={finish}>Skip tour</button></div>
        {step && <div className="tour-progress" aria-hidden="true"><span style={{ width: `${((index + 1) / tourSteps.length) * 100}%` }} /></div>}
        <div key={index} className="tour-copy" aria-live="polite">
          <h2 id="tour-title" ref={heading} tabIndex={-1}>{step?.title ?? "A quick tour of your workspace"}</h2>
          <div id="tour-description">
            {step ? <><ul>{step.items.map(item => <li key={item}>{item}</li>)}</ul><p className="tour-note">{step.note}</p></> : <><p>Get to know all five areas, one screen at a time. We’ll highlight where each task lives and explain what you can do there.</p><p className="tour-note">The tour only opens screens—it never submits data or places orders. Save any unfinished form before starting. You can skip now or replay it later.</p></>}
          </div>
        </div>
        <div className="tour-actions">
          {step && <button type="button" className="button button-secondary" disabled={index === 0 || currentPath !== step.href} onClick={() => go(index - 1)}>Back</button>}
          <button type="button" className="button button-primary" disabled={!!step && currentPath !== step.href} onClick={() => go(index + 1)}>{!step ? "Start tour" : index === tourSteps.length - 1 ? "Finish tour" : "Next"}</button>
        </div>
      </section>
    </dialog>}
  </>;
}
