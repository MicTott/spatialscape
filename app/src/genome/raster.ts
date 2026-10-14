/** Area-weighted mean of (start, end, score) spans over `n` uniform bins of `bin` bp from `start`; gaps count as zero.
 *  Shared by the data worker (bigWig features -> bins) and its tests. */
export function rasterize(starts: ArrayLike<number>, ends: ArrayLike<number>, scores: ArrayLike<number>, start: number, bin: number, n: number): Float32Array {
  const out = new Float32Array(n);
  const stop = start + n * bin;
  for (let i = 0; i < starts.length; i++) {
    const s = Math.max(starts[i], start);
    const e = Math.min(ends[i], stop);
    if (e <= s) continue;
    const v = scores[i];
    const last = Math.min(n - 1, Math.floor((e - 1 - start) / bin));
    for (let b = Math.floor((s - start) / bin); b <= last; b++) {
      const bs = start + b * bin;
      out[b] += v * (Math.min(e, bs + bin) - Math.max(s, bs));
    }
  }
  for (let b = 0; b < n; b++) out[b] /= bin;
  return out;
}
