/** Presentation only. Exact decimal-string rounding; never a purchasing calculation. */
export function displayQuantity(raw: string | null | undefined): { text: string; rounded: boolean } {
  if (raw == null) return { text: "Unknown", rounded: false };
  const match = /^([+-]?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(raw);
  if (!match || raw.length > 500) return { text: raw, rounded: false };
  const exponent = Number(match[4] ?? 0);
  if (Math.abs(exponent) > 500) return { text: raw, rounded: false };
  const fraction = match[3] ?? "";
  const magnitude = BigInt(match[2] + fraction);
  const shift = 3 + exponent - fraction.length;
  const divisor = shift < 0 ? BigInt(10) ** BigInt(-shift) : BigInt(1);
  const remainder = shift < 0 ? magnitude % divisor : BigInt(0);
  const scaled = shift < 0 ? magnitude / divisor + (remainder * BigInt(2) >= divisor ? BigInt(1) : BigInt(0)) : magnitude * BigInt(10) ** BigInt(shift);
  const digits = scaled.toString().padStart(4, "0");
  const sign = match[1] === "-" && magnitude !== BigInt(0) ? "-" : "";
  const rounded = remainder !== BigInt(0);
  return { text: `${rounded ? "≈ " : ""}${sign}${digits.slice(0, -3)}.${digits.slice(-3)}`, rounded };
}
