import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitepress";
import cliSidebar from "../reference/cli/sidebar.json" with { type: "json" };

// the one version string lives in the Python package; the nav label follows it
const init = readFileSync(fileURLToPath(new URL("../../python/src/spatialscape/__init__.py", import.meta.url)), "utf8");
const version = /__version__ = "([^"]+)"/.exec(init)?.[1] ?? "dev";

export default defineConfig({
  title: "spatialscape",
  description: "A static, reactive browser for spatial transcriptomics and snRNA-seq, and the CLI that builds its data bundles.",
  base: "/spatialscape/docs/",
  lastUpdated: true,
  cleanUrls: true,
  head: [["link", { rel: "icon", type: "image/svg+xml", href: "/spatialscape/docs/logo.svg" }]],
  themeConfig: {
    logo: { light: "/logo.svg", dark: "/logo.svg" },
    nav: [
      { text: "Guide", link: "/guide/getting-started" },
      { text: "Reference", link: "/reference/cli/" },
      { text: "Demo", link: "https://mictott.github.io/spatialscape/?d=examples/synthetic" },
      { text: `v${version}`, items: [{ text: "Changelog", link: "/changelog" }, { text: "Contributing", link: "/contributing" }] },
    ],
    sidebar: {
      "/guide/": [
        {
          text: "Guide",
          items: [
            { text: "Getting started", link: "/guide/getting-started" },
            { text: "In a notebook: show()", link: "/guide/notebooks" },
            { text: "Writing dataset.yaml", link: "/guide/dataset-yaml" },
            { text: "Inputs: what the CLI reads", link: "/guide/preparing-data" },
            { text: "Building and validating", link: "/guide/building" },
            { text: "Making changes", link: "/guide/changes" },
            { text: "Using the viewer", link: "/guide/viewer" },
            { text: "The gallery: site.yaml", link: "/guide/registry" },
            { text: "Publish your own site", link: "/guide/publish" },
            { text: "Hosting", link: "/guide/hosting" },
            { text: "Troubleshooting", link: "/guide/troubleshooting" },
          ],
        },
      ],
      "/reference/": [
        {
          text: "Reference",
          items: [
            { text: "CLI commands", link: "/reference/cli/", collapsed: false, items: cliSidebar },
            { text: "dataset.yaml schema", link: "/reference/dataset-schema" },
            { text: "site.yaml schema", link: "/reference/site-yaml" },
            { text: "Bundle format", link: "/reference/format" },
            { text: "URL parameters", link: "/reference/url" },
            { text: "Architecture", link: "/reference/architecture" },
          ],
        },
      ],
    },
    socialLinks: [{ icon: "github", link: "https://github.com/MicTott/spatialscape" }],
    search: { provider: "local" },
    editLink: { pattern: "https://github.com/MicTott/spatialscape/edit/main/docs/:path", text: "Edit this page" },
    footer: { message: "MIT licensed.", copyright: "© 2026 Michael Totty and contributors" },
    outline: { level: [2, 3] },
  },
});
