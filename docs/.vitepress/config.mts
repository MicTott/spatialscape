import { defineConfig } from "vitepress";
import cliSidebar from "../reference/cli/sidebar.json" with { type: "json" };

export default defineConfig({
  title: "spatialscape",
  description: "A static, reactive browser for spatial transcriptomics and snRNA-seq, and the CLI that builds its data bundles.",
  base: "/spatialscape/docs/",
  lastUpdated: true,
  cleanUrls: true,
  head: [["link", { rel: "icon", href: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><circle cx='8' cy='8' r='6' fill='%2340c4ff'/></svg>" }]],
  themeConfig: {
    logo: { light: "/logo.svg", dark: "/logo.svg" },
    nav: [
      { text: "Guide", link: "/guide/getting-started" },
      { text: "Reference", link: "/reference/cli/" },
      { text: "Demo", link: "https://mictott.github.io/spatialscape/" },
      { text: "v0.1.0", items: [{ text: "Changelog", link: "/changelog" }, { text: "Contributing", link: "/contributing" }] },
    ],
    sidebar: {
      "/guide/": [
        {
          text: "Guide",
          items: [
            { text: "Getting started", link: "/guide/getting-started" },
            { text: "Preparing your data", link: "/guide/preparing-data" },
            { text: "Writing dataset.yaml", link: "/guide/dataset-yaml" },
            { text: "Building and validating", link: "/guide/building" },
            { text: "Using the viewer", link: "/guide/viewer" },
            { text: "Publish your own site", link: "/guide/publish" },
            { text: "Hosting", link: "/guide/hosting" },
            { text: "Registry and site bar", link: "/guide/registry" },
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
