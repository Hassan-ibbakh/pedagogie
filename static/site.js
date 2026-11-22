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
const lessonSheet = document.querySelector(".lesson-sheet");
const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");

if (hero && lessonSheet && finePointer.matches && !motionPreference.matches) {
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
      lessonSheet.style.setProperty("--sheet-tilt-x", `${((x - 0.5) * 5).toFixed(2)}deg`);
      lessonSheet.style.setProperty("--sheet-tilt-y", `${((0.5 - y) * 4).toFixed(2)}deg`);
      pointerFrame = 0;
    });
  });

  hero.addEventListener("pointerleave", () => {
    hero.style.setProperty("--pointer-x", "72%");
    hero.style.setProperty("--pointer-y", "45%");
    lessonSheet.style.setProperty("--sheet-tilt-x", "0deg");
    lessonSheet.style.setProperty("--sheet-tilt-y", "0deg");
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
    document.documentElement.dataset.theme = nextTheme;
    try { localStorage.setItem("classe-claire-theme", nextTheme); } catch (error) { }
    syncThemeToggle();
  });
  darkPreference.addEventListener("change", syncThemeToggle);
  syncThemeToggle();
}
