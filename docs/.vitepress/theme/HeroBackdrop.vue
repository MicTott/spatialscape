<script setup lang="ts">
// The home page's first screen: the whole mouse brain playing behind the hero text.
// The loop is a real-time capture of the viewer (dist/launch/scripts/clipHero.mjs records it again).
import { onMounted, ref } from "vue";
import { withBase } from "vitepress";

const video = ref<HTMLVideoElement | null>(null);

onMounted(() => {
  const v = video.value;
  if (!v) return;
  // anyone who asks for less motion gets the still first frame
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    v.removeAttribute("autoplay");
    v.pause();
    v.currentTime = 0;
    return;
  }
  v.muted = true;
  v.play().catch(() => {});
});

function below() {
  document.querySelector(".VPHomeFeatures")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<template>
  <div class="hero-backdrop" aria-hidden="true">
    <video
      ref="video"
      autoplay
      muted
      loop
      playsinline
      preload="auto"
      :poster="withBase('/clips/whole-mouse-brain-loop.jpg')"
    >
      <source :src="withBase('/clips/whole-mouse-brain-loop.mp4')" type="video/mp4" />
    </video>
  </div>
  <button class="hero-below" type="button" aria-label="Scroll to the rest of the page" @click="below">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
  </button>
</template>
