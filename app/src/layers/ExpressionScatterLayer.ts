/**
 * ScatterplotLayer subclass with three extra per-instance bytes:
 *   instanceValue    unorm8   color-by channel (gene / continuous obs), 0..1
 *   instanceCategory unorm16  categorical code (code = round(v * 65535))
 *   instanceFilter   unorm8   filter-by channel, 0..1
 * Colors come from two tiny textures (colormap LUT, category palette with alpha = visibility),
 * so legend toggles, colormap and range changes never touch per-point data.
 * LOD: rows are pre-shuffled, so drawing the first `drawCount` instances is a uniform subsample.
 */
import { ScatterplotLayer, type ScatterplotLayerProps } from "@deck.gl/layers";
import type { Texture } from "@luma.gl/core";

export interface ExpressionScatterProps {
  mode: 0 | 1 | 2 | 3; // 0 continuous, 1 categorical, 2 not measured (constant grey), 3 two-channel blend
  vmin: number;
  vmax: number;
  filterOn: boolean;
  filterMin: number;
  filterMax: number;
  hideZeros: boolean;
  lut: Uint8Array; // 256*4 RGBA (mode 0) or BLEND_SIZE*BLEND_SIZE*4 (mode 3)
  catColors: Uint8Array; // N*4 RGBA (alpha 0 = hidden)
  drawCount: number;
}
export type ExpressionScatterLayerProps = ScatterplotLayerProps<unknown> & ExpressionScatterProps;

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
} sscape;
`;

const sscapeModule = {
  name: "sscape",
  vs: uniformBlock,
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
  },
} as const;

const defaultProps = {
  ...(ScatterplotLayer as any).defaultProps,
  mode: 1,
  vmin: 0,
  vmax: 1,
  filterOn: false,
  filterMin: 0,
  filterMax: 1,
  hideZeros: false,
  lut: { type: "object", value: null, compare: false },
  catColors: { type: "object", value: null, compare: false },
  drawCount: { type: "number", value: Infinity, compare: false },
  getValue: { type: "accessor", value: 0 },
  getValue2: { type: "accessor", value: 0 },
  getCategory: { type: "accessor", value: 0 },
  getFilter: { type: "accessor", value: 0 },
};

export class ExpressionScatterLayer extends ScatterplotLayer<unknown, ExpressionScatterProps> {
  static layerName = "ExpressionScatterLayer";
  static defaultProps = defaultProps as any;

  declare state: ScatterplotLayer["state"] & { lutTex?: Texture; catTex?: Texture; catCount: number };

  getShaders() {
    const shaders = super.getShaders();
    return {
      ...shaders,
      modules: [...shaders.modules, sscapeModule],
      inject: {
        ...(shaders as any).inject,
        "vs:#decl": /* glsl */ `
in float instanceValue;
in float instanceValue2;
in float instanceCategory;
in float instanceFilter;
uniform sampler2D lutTexture;
uniform sampler2D catTexture;
`,
        "vs:#main-end": /* glsl */ `
{
  vec4 sc;
  bool drop = false;
  if (sscape.mode > 2.5) {
    float ta = clamp((instanceValue - sscape.vmin) / max(sscape.vmax - sscape.vmin, 1e-6), 0.0, 1.0);
    float tb = clamp((instanceValue2 - sscape.vmin) / max(sscape.vmax - sscape.vmin, 1e-6), 0.0, 1.0);
    sc = texture(lutTexture, vec2(ta, tb));
    if (sscape.hideZeros > 0.5 && instanceValue < 0.001 && instanceValue2 < 0.001) drop = true;
  } else if (sscape.mode > 1.5) {
    sc = vec4(0.36, 0.39, 0.44, 1.0);
  } else if (sscape.mode < 0.5) {
    float t = (instanceValue - sscape.vmin) / max(sscape.vmax - sscape.vmin, 1e-6);
    t = clamp(t, 0.0, 1.0);
    sc = texture(lutTexture, vec2((t * 255.0 + 0.5) / 256.0, 0.5));
    if (sscape.hideZeros > 0.5 && instanceValue < 0.001) drop = true;
  } else {
    float code = floor(instanceCategory * 65535.0 + 0.5);
    sc = texture(catTexture, vec2((code + 0.5) / sscape.catCount, 0.5));
    if (sc.a < 0.01) drop = true;
  }
  if (sscape.filterOn > 0.5 && (instanceFilter < sscape.filterMin || instanceFilter > sscape.filterMax)) drop = true;
  vFillColor = vec4(sc.rgb, layer.opacity);
  if (drop) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}
`,
      },
    };
  }

  initializeState() {
    super.initializeState();
    this.getAttributeManager()!.addInstanced({
      instanceValue: { size: 1, type: "unorm8", accessor: "getValue", defaultValue: 0 },
      instanceValue2: { size: 1, type: "unorm8", accessor: "getValue2", defaultValue: 0 },
      instanceCategory: { size: 1, type: "unorm16", accessor: "getCategory", defaultValue: 0 },
      instanceFilter: { size: 1, type: "unorm8", accessor: "getFilter", defaultValue: 0 },
    });
    this.setState({ catCount: 1 });
  }

  updateState(params: any) {
    super.updateState(params);
    const { props, oldProps } = params;
    if (props.lut !== oldProps.lut || !this.state.lutTex) {
      this.state.lutTex?.destroy();
      const lut: Uint8Array = props.lut ?? new Uint8Array(256 * 4).fill(255);
      const side = lut.length === 256 * 4 ? 256 : Math.round(Math.sqrt(lut.length / 4));
      this.state.lutTex = this._makeTexture(lut, side, lut.length === 256 * 4 ? 1 : side, lut.length !== 256 * 4);
    }
    if (props.catColors !== oldProps.catColors || !this.state.catTex) {
      this.state.catTex?.destroy();
      const cc: Uint8Array = props.catColors ?? new Uint8Array([200, 200, 200, 255]);
      const n = Math.max(1, cc.length / 4);
      this.state.catTex = this._makeTexture(cc, n);
      this.setState({ catCount: n });
    }
  }

  finalizeState(context: any) {
    this.state.lutTex?.destroy();
    this.state.catTex?.destroy();
    super.finalizeState(context);
  }

  private _makeTexture(data: Uint8Array, width: number, height = 1, smooth = false): Texture {
    return this.context.device.createTexture({
      data,
      width,
      height,
      format: "rgba8unorm",
      sampler: { minFilter: smooth ? "linear" : "nearest", magFilter: smooth ? "linear" : "nearest", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
    });
  }

  draw(params: any) {
    const model = (this.state as any).model;
    if (!model) return;
    const p = this.props;
    model.shaderInputs.setProps({
      sscape: {
        mode: p.mode,
        vmin: p.vmin,
        vmax: p.vmax,
        filterMin: p.filterMin,
        filterMax: p.filterMax,
        filterOn: p.filterOn ? 1 : 0,
        hideZeros: p.hideZeros ? 1 : 0,
        catCount: this.state.catCount,
      },
    });
    model.setBindings({ lutTexture: this.state.lutTex, catTexture: this.state.catTex });
    const total = this.getNumInstances();
    model.setInstanceCount(Math.max(0, Math.min(total, Math.floor(p.drawCount ?? total))));
    super.draw(params);
  }
}
