/** Colormaps as 256x1 RGBA8 lookup tables, plus category palette textures. */

type RGB = [number, number, number];

// Polynomial fits (Matt Zucker, 2019) for matplotlib colormaps; Turbo fit from Google.
function poly(c: number[][], t: number): RGB {
  const [c0, c1, c2, c3, c4, c5, c6] = c;
  const out: number[] = [];
  for (let i = 0; i < 3; i++) {
    out.push(c0[i] + t * (c1[i] + t * (c2[i] + t * (c3[i] + t * (c4[i] + t * (c5[i] + t * c6[i]))))));
  }
  return out as RGB;
}
const VIRIDIS = [
  [0.274344, 0.004462, 0.331359],
  [0.108915, 1.397291, 1.388110],
  [-0.319631, 0.243490, 0.156419],
  [-4.629188, -5.882803, -19.646115],
  [6.181719, 14.388598, 57.442181],
  [4.876952, -13.955112, -66.125783],
  [-5.513165, 4.709245, 26.582180],
];
const MAGMA = [
  [-0.002136, -0.000749, -0.005386],
  [0.251660, 0.677523, 2.494026],
  [8.353717, -3.577719, 0.314474],
  [-27.668735, 14.264731, -13.649214],
  [52.176131, -27.943605, 12.944169],
  [-50.768526, 29.046583, 4.234152],
  [18.655707, -11.489775, -5.601961],
];
const INFERNO = [
  [0.000216, 0.001651, -0.019481],
  [0.106513, 0.563956, 3.932712],
  [11.602496, -3.972853, -15.942394],
  [-41.703991, 17.436398, 44.354145],
  [77.162935, -33.402214, -81.807329],
  [-71.319428, 32.626064, 73.209516],
  [25.131120, -12.242661, -23.070329],
];
const PLASMA = [
  [0.058733, 0.023812, 0.543352],
  [2.176514, 0.238383, 0.753960],
  [-2.689460, -7.455851, 3.110799],
  [6.130348, 42.346186, -28.518855],
  [-11.107432, -82.665631, 60.139843],
  [10.023067, 71.413614, -54.072187],
  [-3.658714, -22.931156, 18.191907],
];
function turbo(t: number): RGB {
  const r = [0.13572138, 4.6153926, -42.66032258, 132.13108234, -152.94239396, 59.28637943];
  const g = [0.09140261, 2.19418839, 4.84296658, -14.18503333, 4.27729857, 2.82956604];
  const b = [0.1066733, 12.64194608, -60.58204836, 110.36276771, -89.90310912, 27.34824973];
  const f = (c: number[]) => c[0] + t * (c[1] + t * (c[2] + t * (c[3] + t * (c[4] + t * c[5]))));
  return [f(r), f(g), f(b)];
}
const CIVIDIS_STOPS: RGB[] = [
  [0.0, 0.135, 0.304],
  [0.0, 0.183, 0.380],
  [0.236, 0.255, 0.417],
  [0.347, 0.322, 0.431],
  [0.436, 0.388, 0.438],
  [0.520, 0.456, 0.440],
  [0.604, 0.527, 0.432],
  [0.694, 0.600, 0.410],
  [0.788, 0.676, 0.375],
  [0.886, 0.756, 0.320],
  [0.995, 0.843, 0.232],
];
function stops(st: RGB[], t: number): RGB {
  const x = t * (st.length - 1);
  const i = Math.min(st.length - 2, Math.floor(x));
  const f = x - i;
  return [0, 1, 2].map((k) => st[i][k] * (1 - f) + st[i + 1][k] * f) as RGB;
}

export const COLORMAPS: Record<string, (t: number) => RGB> = {
  viridis: (t) => poly(VIRIDIS, t),
  magma: (t) => poly(MAGMA, t),
  inferno: (t) => poly(INFERNO, t),
  plasma: (t) => poly(PLASMA, t),
  turbo,
  cividis: (t) => stops(CIVIDIS_STOPS, t),
  greys: (t) => [0.95 - 0.9 * t, 0.95 - 0.9 * t, 0.95 - 0.9 * t],
};

export function colormapLUT(name: string, reverse = false): Uint8Array {
  const fn = COLORMAPS[name] ?? COLORMAPS.viridis;
  const out = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = reverse ? 1 - i / 255 : i / 255;
    const [r, g, b] = fn(t);
    out[i * 4] = Math.max(0, Math.min(255, Math.round(r * 255)));
    out[i * 4 + 1] = Math.max(0, Math.min(255, Math.round(g * 255)));
    out[i * 4 + 2] = Math.max(0, Math.min(255, Math.round(b * 255)));
    out[i * 4 + 3] = 255;
  }
  return out;
}

export function hexToRGB(hex: string): RGB {
  let h = hex.trim().replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h.slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** N x 1 RGBA8 palette; alpha 0 marks a hidden category. Width is padded to >= 1. */
export function categoryPalette(colors: string[], hidden: ReadonlySet<number> | number[] = []): Uint8Array {
  const hid = hidden instanceof Set ? hidden : new Set(hidden);
  const n = Math.max(1, colors.length);
  const out = new Uint8Array(n * 4);
  for (let i = 0; i < colors.length; i++) {
    const [r, g, b] = hexToRGB(colors[i]);
    out[i * 4] = r;
    out[i * 4 + 1] = g;
    out[i * 4 + 2] = b;
    out[i * 4 + 3] = hid.has(i) ? 0 : 255;
  }
  return out;
}

/** Two-channel blend schemes: corner colors for (A=0,B=0), (A=1,B=0), (A=0,B=1), (A=1,B=1). */
export const BLEND_SCHEMES: Record<string, { name: string; a: string; b: string; both: string; none: string }> = {
  yb: { name: "yellow / blue → green", none: "#2a2e35", a: "#f5d324", b: "#3d7fe0", both: "#35c46a" },
  cm: { name: "cyan / magenta → white", none: "#2a2e35", a: "#28c8ea", b: "#ea4fc3", both: "#f7f7f7" },
  rg: { name: "red / green → yellow", none: "#2a2e35", a: "#e8484e", b: "#34c25e", both: "#f3e24a" },
};
export const BLEND_SIZE = 32;

/** BLEND_SIZE x BLEND_SIZE RGBA8 texture: x = channel A, y = channel B, bilinear mix of the four corners. */
export function blendLUT(scheme: string): Uint8Array {
  const sc = BLEND_SCHEMES[scheme] ?? BLEND_SCHEMES.yb;
  const c00 = hexToRGB(sc.none);
  const c10 = hexToRGB(sc.a);
  const c01 = hexToRGB(sc.b);
  const c11 = hexToRGB(sc.both);
  const n = BLEND_SIZE;
  const out = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) {
    const tb = y / (n - 1);
    for (let x = 0; x < n; x++) {
      const ta = x / (n - 1);
      const o = (y * n + x) * 4;
      for (let k = 0; k < 3; k++) {
        const v = c00[k] * (1 - ta) * (1 - tb) + c10[k] * ta * (1 - tb) + c01[k] * (1 - ta) * tb + c11[k] * ta * tb;
        out[o + k] = Math.max(0, Math.min(255, Math.round(v)));
      }
      out[o + 3] = 255;
    }
  }
  return out;
}

/** CSS gradient string for legends. */
export function colormapCSS(name: string): string {
  const fn = COLORMAPS[name] ?? COLORMAPS.viridis;
  const parts: string[] = [];
  for (let i = 0; i <= 10; i++) {
    const [r, g, b] = fn(i / 10).map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255));
    parts.push(`rgb(${r},${g},${b}) ${i * 10}%`);
  }
  return `linear-gradient(90deg, ${parts.join(", ")})`;
}
