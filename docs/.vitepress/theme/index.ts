import { h } from "vue";
import DefaultTheme from "vitepress/theme";
import HeroBackdrop from "./HeroBackdrop.vue";
import "./custom.css";

export default {
  extends: DefaultTheme,
  // the home page's hero plays the whole mouse brain behind its text
  Layout: () => h(DefaultTheme.Layout, null, { "home-hero-info-before": () => h(HeroBackdrop) }),
};
