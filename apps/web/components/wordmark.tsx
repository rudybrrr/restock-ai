import Link from "next/link";

export function Wordmark({ href = "/", showIcon = false }: { href?: string; showIcon?: boolean }) {
  return (
    <Link href={href} className="wordmark" aria-label="ReStock home">
      {showIcon && (
        <svg className="wordmark-icon" viewBox="0 0 64 64" width="36" height="36" aria-hidden="true" focusable="false">
          <rect width="64" height="64" rx="14" fill="#234d3c" />
          <path d="M19 46V17h14c9 0 14 4 14 11 0 5-3 8-8 10l10 8H38L27 36v10zm8-17h6c4 0 6-1 6-4s-2-4-6-4h-6z" fill="#f7f7ef" />
          <path d="M17 52h30" stroke="#afc493" strokeWidth="4" strokeLinecap="round" />
        </svg>
      )}
      <span className="wordmark-re">Re</span><span className="wordmark-stock">Stock</span>
      <span className="wordmark-period" aria-hidden="true">
        .
      </span>
    </Link>
  );
}
