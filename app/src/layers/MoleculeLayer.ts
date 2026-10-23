/**
 * One tile of molecules: a point per molecule, coloured by its gene through a small per-gene texture (RGBA, alpha 0
 * = not drawn), so changing the gene or the colour scheme never touches the tile's data. Molecules not assigned to a
 * cell draw dimmer.
 */
import { ScatterplotLayer, type ScatterplotLayerProps } from "@deck.gl/layers";
import type { Device, Texture } from "@luma.gl/core";

export interface MoleculeLayerExtraProps {
  geneColors: Uint8Array; // genes * 4 RGBA; alpha 0 hides the gene
  dimAlpha: number; // alpha multiplier for molecules without a cell
}
export type MoleculeLayerProps = ScatterplotLayerProps<unknown> & MoleculeLayerExtraProps;

const moleculeModule = {
  name: "molecule",
  vs: /* glsl */ `
uniform moleculeUniforms {
  float geneCount;
  float dimAlpha;
} molecule;
`,
  uniformTypes: { geneCount: "f32", dimAlpha: "f32" },
} as const;

const defaultProps = {
  ...(ScatterplotLayer as any).defaultProps,
  geneColors: { type: "object", value: null, compare: false },
  dimAlpha: 0.45,
  getGene: { type: "accessor", value: 0 },
  getFlags: { type: "accessor", value: 0 },
};

export class MoleculeLayer extends ScatterplotLayer<unknown, MoleculeLayerExtraProps> {
  static layerName = "MoleculeLayer";
  static defaultProps = defaultProps as any;

  declare state: ScatterplotLayer["state"] & { geneTex?: Texture; geneCount: number; geneColors?: Uint8Array };

  getShaders() {
    const shaders = super.getShaders();
    return {
      ...shaders,
      modules: [...shaders.modules, moleculeModule],
      inject: {
        ...(shaders as any).inject,
        "vs:#decl": /* glsl */ `
in float instanceGene;
in float instanceFlags;
uniform sampler2D geneTexture;
`,
        "vs:#main-end": /* glsl */ `
{
  float code = floor(instanceGene * 65535.0 + 0.5);
  vec4 gc = texture(geneTexture, vec2((code + 0.5) / molecule.geneCount, 0.5));
  float assigned = step(0.5, mod(floor(instanceFlags * 255.0 + 0.5), 2.0));
  vFillColor = vec4(gc.rgb, gc.a * layer.opacity * mix(molecule.dimAlpha, 1.0, assigned));
  if (gc.a < 0.01) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}
`,
      },
    };
  }

  initializeState() {
    super.initializeState();
    this.getAttributeManager()!.addInstanced({
      instanceGene: { size: 1, type: "unorm16", accessor: "getGene", defaultValue: 0 },
      instanceFlags: { size: 1, type: "unorm8", accessor: "getFlags", defaultValue: 0 },
    } as any);
    this.setState({ geneCount: 1 });
  }

  updateState(params: any) {
    super.updateState(params);
    const { props } = params;
    if (props.geneColors !== this.state.geneColors || !this.state.geneTex) {
      this.state.geneTex?.destroy();
      const gc: Uint8Array = props.geneColors ?? new Uint8Array([200, 200, 200, 255]);
      const n = Math.max(1, gc.length / 4);
      this.state.geneTex = makeTexture(this.context.device, gc, n);
      this.setState({ geneCount: n, geneColors: props.geneColors });
    }
  }

  finalizeState(context: any) {
    this.state.geneTex?.destroy();
    super.finalizeState(context);
  }

  draw(params: any) {
    const model = (this.state as any).model;
    if (!model) return;
    model.shaderInputs.setProps({ molecule: { geneCount: this.state.geneCount, dimAlpha: this.props.dimAlpha ?? 0.45 } });
    model.setBindings({ geneTexture: this.state.geneTex });
    super.draw(params);
  }
}

function makeTexture(device: Device, data: Uint8Array, width: number): Texture {
  return device.createTexture({
    data,
    width,
    height: 1,
    format: "rgba8unorm",
    sampler: { minFilter: "nearest", magFilter: "nearest", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
  });
}
