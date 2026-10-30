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

// The per-gene colours sit in a texture GENE_TEX_WIDTH wide and as many rows as the genes need: a whole-transcriptome
// panel (18,000 genes and more) is wider than the largest texture many GPUs allow (16,384 px, 8,192 on some), and a
// texture that cannot be made samples black.
export const GENE_TEX_WIDTH = 1024;

export function geneTextureRows(genes: number): number {
  return Math.max(1, Math.ceil(genes / GENE_TEX_WIDTH));
}

/** `colors` (genes * 4 RGBA) padded to fill GENE_TEX_WIDTH * rows texels. */
export function geneTextureData(colors: Uint8Array): Uint8Array {
  const rows = geneTextureRows(colors.length / 4);
  const out = new Uint8Array(GENE_TEX_WIDTH * rows * 4);
  out.set(colors.subarray(0, out.length));
  return out;
}

const moleculeModule = {
  name: "molecule",
  vs: /* glsl */ `
uniform moleculeUniforms {
  float texWidth;
  float texRows;
  float dimAlpha;
} molecule;
`,
  uniformTypes: { texWidth: "f32", texRows: "f32", dimAlpha: "f32" },
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

  declare state: ScatterplotLayer["state"] & { geneTex?: Texture; texRows: number; geneColors?: Uint8Array };

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
  float row = floor(code / molecule.texWidth);
  float col = code - row * molecule.texWidth;
  vec4 gc = texture(geneTexture, vec2((col + 0.5) / molecule.texWidth, (row + 0.5) / molecule.texRows));
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
    this.setState({ texRows: 1 });
  }

  updateState(params: any) {
    super.updateState(params);
    const { props } = params;
    if (props.geneColors !== this.state.geneColors || !this.state.geneTex) {
      this.state.geneTex?.destroy();
      const gc: Uint8Array = props.geneColors ?? new Uint8Array([200, 200, 200, 255]);
      const rows = geneTextureRows(gc.length / 4);
      this.state.geneTex = makeTexture(this.context.device, geneTextureData(gc), GENE_TEX_WIDTH, rows);
      this.setState({ texRows: rows, geneColors: props.geneColors });
    }
  }

  finalizeState(context: any) {
    this.state.geneTex?.destroy();
    super.finalizeState(context);
  }

  draw(params: any) {
    const model = (this.state as any).model;
    if (!model) return;
    model.shaderInputs.setProps({ molecule: { texWidth: GENE_TEX_WIDTH, texRows: this.state.texRows, dimAlpha: this.props.dimAlpha ?? 0.45 } });
    model.setBindings({ geneTexture: this.state.geneTex });
    super.draw(params);
  }
}

function makeTexture(device: Device, data: Uint8Array, width: number, height: number): Texture {
  return device.createTexture({
    data,
    width,
    height,
    format: "rgba8unorm",
    sampler: { minFilter: "nearest", magFilter: "nearest", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
  });
}
