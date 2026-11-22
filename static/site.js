const menuButton = document.querySelector(".site-menu-toggle");
const navigation = document.querySelector(".site-nav");

if (menuButton && navigation) {
  menuButton.addEventListener("click", () => {
    const isOpen = menuButton.getAttribute("aria-expanded") === "true";
    menuButton.setAttribute("aria-expanded", String(!isOpen));
    menuButton.setAttribute("aria-label", isOpen ? "Ouvrir le menu" : "Fermer le menu");
    navigation.classList.toggle("is-open", !isOpen);
  });

  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      menuButton.setAttribute("aria-expanded", "false");
      menuButton.setAttribute("aria-label", "Ouvrir le menu");
      navigation.classList.remove("is-open");
    }
  });
}

const revealItems = document.querySelectorAll(".reveal");
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const revealGroups = document.querySelectorAll(".method-steps, .subject-grid, .promise-grid");

revealGroups.forEach((group) => {
  group.querySelectorAll(".reveal").forEach((item, index) => {
    item.style.setProperty("--reveal-delay", `${index * 110}ms`);
  });
});

if ("IntersectionObserver" in window && !motionPreference.matches) {
  const revealObserver = new IntersectionObserver((entries, observer) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.16 });

  revealItems.forEach((item) => revealObserver.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

const header = document.querySelector(".site-header");
let progressFrame = 0;

function updateScrollProgress() {
  if (!header || progressFrame) return;
  progressFrame = window.requestAnimationFrame(() => {
    const scrollableHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = scrollableHeight > 0 ? window.scrollY / scrollableHeight : 0;
    header.style.setProperty("--scroll-progress", String(Math.min(1, Math.max(0, progress))));
    progressFrame = 0;
  });
}

window.addEventListener("scroll", updateScrollProgress, { passive: true });
window.addEventListener("resize", updateScrollProgress);
updateScrollProgress();

const hero = document.querySelector(".hero");
const heroArt = document.querySelector(".hero-art");
const sceneTilt = document.querySelector(".scene3d-tilt");
const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");

// 3D scene follows the pointer (desktop only, respects reduced motion)
if (hero && sceneTilt && finePointer.matches && !motionPreference.matches) {
  let pointerFrame = 0;
  let pointerPosition = null;

  hero.addEventListener("pointermove", (event) => {
    pointerPosition = { x: event.clientX, y: event.clientY };
    if (pointerFrame) return;

    pointerFrame = window.requestAnimationFrame(() => {
      const bounds = hero.getBoundingClientRect();
      const x = (pointerPosition.x - bounds.left) / bounds.width;
      const y = (pointerPosition.y - bounds.top) / bounds.height;
      hero.style.setProperty("--pointer-x", `${(x * 100).toFixed(1)}%`);
      hero.style.setProperty("--pointer-y", `${(y * 100).toFixed(1)}%`);
      sceneTilt.style.setProperty("--tilt-x", `${((x - 0.5) * 22).toFixed(2)}deg`);
      sceneTilt.style.setProperty("--tilt-y", `${((0.5 - y) * 12).toFixed(2)}deg`);
      pointerFrame = 0;
    });
  });

  hero.addEventListener("pointerleave", () => {
    hero.style.setProperty("--pointer-x", "72%");
    hero.style.setProperty("--pointer-y", "45%");
    sceneTilt.style.setProperty("--tilt-x", "0deg");
    sceneTilt.style.setProperty("--tilt-y", "0deg");
  });
}

// Pause the 3D animation while the hero is off-screen or the tab is hidden
if (heroArt && "IntersectionObserver" in window) {
  let heroVisible = true;
  const syncPause = () => heroArt.classList.toggle("is-paused", !heroVisible || document.hidden);
  new IntersectionObserver(([entry]) => { heroVisible = entry.isIntersecting; syncPause(); }).observe(heroArt);
  document.addEventListener("visibilitychange", syncPause);
}

// Header elevation after scrolling
if (header) {
  const syncHeader = () => header.classList.toggle("is-scrolled", window.scrollY > 8);
  window.addEventListener("scroll", syncHeader, { passive: true });
  syncHeader();
}

// Subject tiles: 3D tilt and glare under the pointer
if (finePointer.matches && !motionPreference.matches) {
  document.querySelectorAll(".subject-tile").forEach((tile) => {
    let frame = 0;
    tile.addEventListener("pointermove", (event) => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        const bounds = tile.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width;
        const y = (event.clientY - bounds.top) / bounds.height;
        tile.classList.add("is-tilting");
        tile.style.setProperty("--ry", `${((x - 0.5) * 12).toFixed(2)}deg`);
        tile.style.setProperty("--rx", `${((0.5 - y) * 10).toFixed(2)}deg`);
        tile.style.setProperty("--gx", `${(x * 100).toFixed(1)}%`);
        tile.style.setProperty("--gy", `${(y * 100).toFixed(1)}%`);
        frame = 0;
      });
    });
    tile.addEventListener("pointerleave", () => {
      tile.classList.remove("is-tilting");
      tile.style.setProperty("--rx", "0deg");
      tile.style.setProperty("--ry", "0deg");
    });
  });
}

const themeToggle = document.querySelector(".theme-toggle");
const darkPreference = window.matchMedia("(prefers-color-scheme: dark)");

function currentTheme() {
  return document.documentElement.dataset.theme || (darkPreference.matches ? "dark" : "light");
}

function syncThemeToggle() {
  if (!themeToggle) return;
  const isDark = currentTheme() === "dark";
  themeToggle.setAttribute("aria-pressed", String(isDark));
  themeToggle.setAttribute("aria-label", isDark ? "Activer le mode clair" : "Activer le mode sombre");
}

if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const nextTheme = currentTheme() === "dark" ? "light" : "dark";
    const root = document.documentElement;
    if (!motionPreference.matches) {
      root.classList.add("theme-anim");
      window.setTimeout(() => root.classList.remove("theme-anim"), 450);
      themeToggle.classList.remove("is-spinning");
      void themeToggle.offsetWidth;
      themeToggle.classList.add("is-spinning");
    }
    root.dataset.theme = nextTheme;
    try { localStorage.setItem("classe-claire-theme", nextTheme); } catch (error) { }
    syncThemeToggle();
  });
  darkPreference.addEventListener("change", syncThemeToggle);
  syncThemeToggle();
}
