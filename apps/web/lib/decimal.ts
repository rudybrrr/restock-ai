/** Sum API decimal strings without binary floating-point rounding. */
export function sumDecimals(values: string[]): string {
  if (!values.length) return "0";
  if (values.some((v) => !/^-?\d+(\.\d+)?$/.test(v))) return "Unavailable";
  const scale = Math.max(...values.map((v) => v.split(".")[1]?.length ?? 0));
  const total = values.reduce((sum, value) => {
    const negative = value.startsWith("-");
    const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
    const scaled = BigInt(whole + fraction.padEnd(scale, "0"));
    return sum + (negative ? -scaled : scaled);
  }, BigInt(0));
  const digits = (total < 0 ? -total : total)
    .toString()
    .padStart(scale + 1, "0");
  return `${total < 0 ? "-" : ""}${scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits}`;
}
