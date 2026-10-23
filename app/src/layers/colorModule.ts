/**
 * The colour rule every cell-level layer shares (dots, filled shapes, shape edges): a cell's colour-by value,
 * second value (blends), category code and filter value become a colour, or a "drop" when the cell's category is
 * hidden, its value is zero with hide-zeros on, or it falls outside the filter. Colours come from two small
 * textures (colormap or blend LUT, category palette with alpha = visibility), so legend toggles, colormap and range
 * changes never touch per-cell data.
 */
import type { Device, Texture } from "@luma.gl/core";

export interface CellColorProps {
  mode: 0 | 1 | 2 | 3; // 0 continuous, 1 categorical, 2 not measured (constant grey), 3 two-channel blend
  vmin: number;
  vmax: number;
  filterOn: boolean;
  filterMin: number;
  filterMax: number;
  hideZeros: boolean;
  valueScale: number; // multiplies the unorm value before vmin/vmax mapping (per-sample max -> shared scale)
  valueCenter: number; // the value the scale pivots on: 0, or 0.5 for signed features quantized symmetrically around zero
  lut: Uint8Array | null; // 256*4 RGBA (mode 0) or BLEND_SIZE*BLEND_SIZE*4 (mode 3)
  catColors: Uint8Array | null; // N*4 RGBA (alpha 0 = hidden)
}

const uniformBlock = /* glsl */ `
uniform sscapeUniforms {
  float mode;
  float vmin;
  float vmax;
  float filterMin;
  float filterMax;
  float filterOn;
  float hideZeros;
  float catCount;
  float valueScale;
  float valueCenter;
} sscape;
`;

const colorFunction = /* glsl */ `
uniform sampler2D lutTexture;
uniform sampler2D catTexture;

// value, value2 and filterValue are unorm8 (0..1); category is unorm16 (code = round(category * 65535))
vec4 sscape_cellColor(float value, float value2, float category, float filterValue, out bool drop) {
  vec4 sc;
  drop = false;
  float v1 = (value - sscape.valueCenter) * sscape.valueScale + sscape.valueCenter;
  float v2 = (value2 - sscape.valueCenter) * sscape.valueScale + sscape.valueCenter;
  if (sscape.mode > 2.5) {
    float ta = clamp((v1 - sscape.vmin) / max(sscape.vmax - sscape.vmin, 1e-6), 0.0, 1.0);
    float tb = clamp((v2 - sscape.vmin) / max(sscape.vmax - sscape.vmin, 1e-6), 0.0, 1.0);
    sc = texture(lutTexture, vec2(ta, tb));
    if (sscape.hideZeros > 0.5 && abs(value - sscape.valueCenter) < 0.0025 && abs(value2 - sscape.valueCenter) < 0.0025) drop = true;
  } else if (sscape.mode > 1.5) {
    sc = vec4(0.36, 0.39, 0.44, 1.0);
  } else if (sscape.mode < 0.5) {
    float t = clamp((v1 - sscape.vmin) / max(sscape.vmax - sscape.vmin, 1e-6), 0.0, 1.0);
    sc = texture(lutTexture, vec2((t * 255.0 + 0.5) / 256.0, 0.5));
    if (sscape.hideZeros > 0.5 && abs(value - sscape.valueCenter) < 0.0025) drop = true;
  } else {
    float code = floor(category * 65535.0 + 0.5);
    sc = texture(catTexture, vec2((code + 0.5) / sscape.catCount, 0.5));
    if (sc.a < 0.01) drop = true;
  }
  if (sscape.filterOn > 0.5 && (filterValue < sscape.filterMin || filterValue > sscape.filterMax)) drop = true;
  return sc;
}
`;

/** luma.gl shader module: the uniforms in both stages, the colour function in the vertex stage. */
export const cellColorModule = {
  name: "sscape",
  vs: uniformBlock + colorFunction,
  fs: uniformBlock,
  uniformTypes: {
    mode: "f32",
    vmin: "f32",
    vmax: "f32",
    filterMin: "f32",
    filterMax: "f32",
    filterOn: "f32",
    hideZeros: "f32",
    catCount: "f32",
    valueScale: "f32",
    valueCenter: "f32",
  },
} as const;

export const cellColorDefaultProps = {
  mode: 1,
  vmin: 0,
  vmax: 1,
  filterOn: false,
  filterMin: 0,
  filterMax: 1,
  hideZeros: false,
  valueScale: 1,
  valueCenter: 0,
  lut: { type: "object", value: null, compare: false },
  catColors: { type: "object", value: null, compare: false },
  getValue: { type: "accessor", value: 0 },
  getValue2: { type: "accessor", value: 0 },
  getCategory: { type: "accessor", value: 0 },
  getFilter: { type: "accessor", value: 0 },
};

/** The four per-cell bytes as attributes; `stepMode` is "instance" for dots and edges, "dynamic" for filled shapes. */
export function cellColorAttributes(prefix: string, stepMode?: "dynamic") {
  const extra = stepMode ? { stepMode } : {};
  return {
    [`${prefix}Value`]: { size: 1, type: "unorm8", accessor: "getValue", defaultValue: 0, ...extra },
    [`${prefix}Value2`]: { size: 1, type: "unorm8", accessor: "getValue2", defaultValue: 0, ...extra },
    [`${prefix}Category`]: { size: 1, type: "unorm16", accessor: "getCategory", defaultValue: 0, ...extra },
    [`${prefix}Filter`]: { size: 1, type: "unorm8", accessor: "getFilter", defaultValue: 0, ...extra },
  };
}

/** The same bytes packed into two attributes, for layers that already use most of WebGL's 16 attribute slots
 *  (deck's PathLayer declares 13): `cellBytes` = value, value2, filter, unused; `cellCategory` = the category code. */
export const packedCellDefaultProps = {
  getCellBytes: { type: "accessor", value: [0, 0, 0, 0] },
  getCellCategory: { type: "accessor", value: 0 },
};

export function packedCellAttributes(prefix: string, stepMode?: "dynamic") {
  const extra = stepMode ? { stepMode } : {};
  return {
    [`${prefix}CellBytes`]: { size: 4, type: "unorm8", accessor: "getCellBytes", defaultValue: [0, 0, 0, 0], ...extra },
    [`${prefix}CellCategory`]: { size: 1, type: "unorm16", accessor: "getCellCategory", defaultValue: 0, ...extra },
  };
}

function makeTexture(device: Device, data: Uint8Array, width: number, height = 1, smooth = false): Texture {
  return device.createTexture({
    data,
    width,
    height,
    format: "rgba8unorm",
    sampler: { minFilter: smooth ? "linear" : "nearest", magFilter: smooth ? "linear" : "nearest", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
  });
}

/** The two colour textures of one layer, rebuilt only when their arrays change. */
export class CellColorTextures {
  lutTex?: Texture;
  catTex?: Texture;
  catCount = 1;

  update(device: Device, props: CellColorProps, oldProps: Partial<CellColorProps>) {
    if (props.lut !== oldProps.lut || !this.lutTex) {
      this.lutTex?.destroy();
      const lut: Uint8Array = props.lut ?? new Uint8Array(256 * 4).fill(255);
      const side = lut.length === 256 * 4 ? 256 : Math.round(Math.sqrt(lut.length / 4));
      this.lutTex = makeTexture(device, lut, side, lut.length === 256 * 4 ? 1 : side, lut.length !== 256 * 4);
    }
    if (props.catColors !== oldProps.catColors || !this.catTex) {
      this.catTex?.destroy();
      const cc: Uint8Array = props.catColors ?? new Uint8Array([200, 200, 200, 255]);
      this.catCount = Math.max(1, cc.length / 4);
      this.catTex = makeTexture(device, cc, this.catCount);
    }
  }

  /** Uniforms and texture bindings for one draw. */
  apply(model: any, p: CellColorProps) {
    model.shaderInputs.setProps({
      sscape: {
        mode: p.mode,
        vmin: p.vmin,
        vmax: p.vmax,
        filterMin: p.filterMin,
        filterMax: p.filterMax,
        filterOn: p.filterOn ? 1 : 0,
        hideZeros: p.hideZeros ? 1 : 0,
        catCount: this.catCount,
        valueScale: p.valueScale ?? 1,
        valueCenter: p.valueCenter ?? 0,
      },
    });
    model.setBindings({ lutTexture: this.lutTex, catTexture: this.catTex });
  }

  destroy() {
    this.lutTex?.destroy();
    this.catTex?.destroy();
  }
}
