/** Date helpers on ISO yyyy-mm-dd strings, in local time (no timezone drift). */
export function parse(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function addDays(day: string, n: number): string {
  const d = parse(day);
  d.setDate(d.getDate() + n);
  return iso(d);
}

/** The next `n` weekdays after `day`. */
export function weekdaysAfter(day: string, n: number): string[] {
  const out: string[] = [];
  let cur = day;
  while (out.length < n) {
    cur = addDays(cur, 1);
    const wd = parse(cur).getDay();
    if (wd !== 0 && wd !== 6) out.push(cur);
  }
  return out;
}

export function workingDays(a: string, b: string): number {
  let n = 0;
  for (let cur = a; cur <= b; cur = addDays(cur, 1)) {
    const wd = parse(cur).getDay();
    if (wd !== 0 && wd !== 6) n += 1;
  }
  return n;
}

export const short = (day: string) => parse(day).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
