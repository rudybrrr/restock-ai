import Link from "next/link";

export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="wordmark" aria-label="ReStock home">
      <span>Re</span>Stock
      <span className="wordmark-period" aria-hidden="true">
        .
      </span>
    </Link>
  );
}
