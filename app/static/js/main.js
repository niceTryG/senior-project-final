(() => {
  const root = document.documentElement;
  const body = document.body;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  root.classList.add("js-enhanced");
  if (body) body.classList.add("is-entering");

  const finishEntrance = () => {
    if (!body) return;
    requestAnimationFrame(() => {
      body.classList.remove("is-entering");
      body.classList.add("is-entered");
    });
  };

  if (document.readyState === "complete") {
    finishEntrance();
  } else {
    window.addEventListener("load", finishEntrance, { once: true });
  }

  const revealSelector = [
    "[data-animate]",
    ".ad-home-card",
    ".ad-home-feature-card",
    ".ad-home-role-card",
    ".ad-home-step-item",
    ".adras-panel",
    ".adras-kpi-card",
    ".adras-detail-stat-card",
    ".adras-task-card",
    ".adras-mini-action-card",
    ".flash-message"
  ].join(", ");

  const revealTargets = [...new Set(document.querySelectorAll(revealSelector))];

  revealTargets.forEach((element, index) => {
    if (!element.dataset.animate) {
      element.dataset.animate = "rise";
    }
    if (!element.style.getPropertyValue("--reveal-delay")) {
      element.style.setProperty("--reveal-delay", `${Math.min(index * 45, 360)}ms`);
    }
  });

  if (!reduceMotion && "IntersectionObserver" in window) {
    const revealObserver = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.14, rootMargin: "0px 0px -8% 0px" }
    );

    revealTargets.forEach((element) => revealObserver.observe(element));
  } else {
    revealTargets.forEach((element) => element.classList.add("is-visible"));
  }

  document.querySelectorAll("[data-tilt]").forEach((element) => {
    const reset = () => {
      element.style.setProperty("--tilt-x", "0deg");
      element.style.setProperty("--tilt-y", "0deg");
      element.style.setProperty("--glow-x", "50%");
      element.style.setProperty("--glow-y", "50%");
    };

    reset();
    if (reduceMotion) return;

    element.addEventListener("pointermove", (event) => {
      const rect = element.getBoundingClientRect();
      const relativeX = (event.clientX - rect.left) / rect.width;
      const relativeY = (event.clientY - rect.top) / rect.height;
      const tiltY = (relativeX - 0.5) * 10;
      const tiltX = (0.5 - relativeY) * 10;

      element.style.setProperty("--tilt-x", `${tiltX.toFixed(2)}deg`);
      element.style.setProperty("--tilt-y", `${tiltY.toFixed(2)}deg`);
      element.style.setProperty("--glow-x", `${(relativeX * 100).toFixed(2)}%`);
      element.style.setProperty("--glow-y", `${(relativeY * 100).toFixed(2)}%`);
    });

    element.addEventListener("pointerleave", reset);
  });

  document.querySelectorAll("[data-spotlight]").forEach((element) => {
    const reset = () => {
      element.style.setProperty("--spotlight-x", "50%");
      element.style.setProperty("--spotlight-y", "50%");
    };

    reset();
    if (reduceMotion) return;

    element.addEventListener("pointermove", (event) => {
      const rect = element.getBoundingClientRect();
      const relativeX = ((event.clientX - rect.left) / rect.width) * 100;
      const relativeY = ((event.clientY - rect.top) / rect.height) * 100;
      element.style.setProperty("--spotlight-x", `${relativeX.toFixed(2)}%`);
      element.style.setProperty("--spotlight-y", `${relativeY.toFixed(2)}%`);
    });

    element.addEventListener("pointerleave", reset);
  });

  document.querySelectorAll("[data-magnetic]").forEach((element) => {
    const reset = () => {
      element.style.setProperty("--magnetic-x", "0px");
      element.style.setProperty("--magnetic-y", "0px");
    };

    reset();
    if (reduceMotion) return;

    element.addEventListener("pointermove", (event) => {
      const rect = element.getBoundingClientRect();
      const offsetX = ((event.clientX - rect.left) / rect.width - 0.5) * 12;
      const offsetY = ((event.clientY - rect.top) / rect.height - 0.5) * 12;
      element.style.setProperty("--magnetic-x", `${offsetX.toFixed(2)}px`);
      element.style.setProperty("--magnetic-y", `${offsetY.toFixed(2)}px`);
    });

    element.addEventListener("pointerleave", reset);
  });

  document.querySelectorAll("[data-countup]").forEach((element) => {
    const raw = (element.textContent || "").trim();
    const parsed = Number(raw.replace(/[^0-9.-]/g, ""));

    if (!Number.isFinite(parsed)) return;
    if (reduceMotion) return;

    const duration = 1100;
    const startTime = performance.now();
    const format = new Intl.NumberFormat();

    const tick = (now) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = Math.round(parsed * eased);
      element.textContent = format.format(value);
      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    };

    element.textContent = "0";
    requestAnimationFrame(tick);
  });

  const setScrollProgress = () => {
    const doc = document.documentElement;
    const scrollable = Math.max(doc.scrollHeight - window.innerHeight, 1);
    const progress = Math.min(Math.max(window.scrollY / scrollable, 0), 1);
    root.style.setProperty("--scroll-progress", progress.toFixed(4));
  };

  setScrollProgress();
  window.addEventListener("scroll", setScrollProgress, { passive: true });
  window.addEventListener("resize", setScrollProgress);

  const parallaxItems = [...document.querySelectorAll("[data-parallax]")];
  const setParallax = () => {
    if (reduceMotion) return;
    const viewportHeight = window.innerHeight || 1;

    parallaxItems.forEach((element) => {
      const speed = Number(element.getAttribute("data-parallax-speed") || "0.14");
      const rect = element.getBoundingClientRect();
      const center = rect.top + rect.height / 2;
      const offset = (center - viewportHeight / 2) / viewportHeight;
      const moveY = offset * -48 * speed;
      const rotate = offset * -8 * speed;

      element.style.setProperty("--parallax-y", `${moveY.toFixed(2)}px`);
      element.style.setProperty("--parallax-rotate", `${rotate.toFixed(2)}deg`);
    });
  };

  setParallax();
  window.addEventListener("scroll", setParallax, { passive: true });
  window.addEventListener("resize", setParallax);

  document.querySelectorAll("[data-ripple]").forEach((element) => {
    element.addEventListener("pointerdown", (event) => {
      const rect = element.getBoundingClientRect();
      const ripple = document.createElement("span");
      ripple.className = "mm-ripple";
      ripple.style.left = `${event.clientX - rect.left}px`;
      ripple.style.top = `${event.clientY - rect.top}px`;
      element.appendChild(ripple);

      ripple.addEventListener("animationend", () => {
        ripple.remove();
      });
    });
  });
})();
