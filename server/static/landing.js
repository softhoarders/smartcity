(function () {
    const nav = document.getElementById("landing-nav");
    const toggle = document.getElementById("landing-nav-toggle");
    const mobileMenu = document.getElementById("landing-mobile-menu");
    const navLinks = document.querySelectorAll(".landing-nav-links a[data-nav]");

    /* Sticky nav shadow */
    if (nav) {
        const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 16);
        onScroll();
        window.addEventListener("scroll", onScroll, { passive: true });
    }

    /* Mobile menu */
    if (toggle && mobileMenu) {
        toggle.addEventListener("click", () => {
            const open = toggle.getAttribute("aria-expanded") === "true";
            toggle.setAttribute("aria-expanded", open ? "false" : "true");
            mobileMenu.hidden = open;
        });
        mobileMenu.querySelectorAll("a").forEach((link) => {
            link.addEventListener("click", () => {
                toggle.setAttribute("aria-expanded", "false");
                mobileMenu.hidden = true;
            });
        });
    }

    /* Smooth scroll for anchor links */
    document.querySelectorAll('.landing-nav a[href^="#"], .landing-mobile-menu a[href^="#"], .landing-footer a[href^="#"]').forEach((anchor) => {
        anchor.addEventListener("click", (event) => {
            const id = anchor.getAttribute("href");
            if (!id || id === "#") return;
            const target = document.querySelector(id);
            if (!target) return;
            event.preventDefault();
            const offset = (nav ? nav.offsetHeight : 0) + 12;
            const top = target.getBoundingClientRect().top + window.scrollY - offset;
            window.scrollTo({ top, behavior: "smooth" });
        });
    });

    /* Active nav link on scroll */
    if (navLinks.length) {
        const sections = Array.from(navLinks)
            .map((link) => {
                const id = link.getAttribute("href");
                const el = id ? document.querySelector(id) : null;
                return el ? { link, el } : null;
            })
            .filter(Boolean);

        const setActive = () => {
            const offset = (nav ? nav.offsetHeight : 0) + 80;
            let current = sections[0];
            for (const item of sections) {
                if (item.el.getBoundingClientRect().top <= offset) {
                    current = item;
                }
            }
            navLinks.forEach((l) => l.classList.remove("is-active"));
            if (current) current.link.classList.add("is-active");
        };

        setActive();
        window.addEventListener("scroll", setActive, { passive: true });
    }

    /* How-it-works tabs */
    const flowTabs = document.querySelectorAll("[data-flow-tab]");
    const flowPanels = document.querySelectorAll(".landing-flow-panel");

    flowTabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            const id = tab.getAttribute("data-flow-tab");
            flowTabs.forEach((t) => {
                const active = t === tab;
                t.classList.toggle("is-active", active);
                t.setAttribute("aria-selected", active ? "true" : "false");
            });
            flowPanels.forEach((panel) => {
                const match = panel.id === `flow-panel-${id}`;
                panel.classList.toggle("is-active", match);
                panel.hidden = !match;
            });
        });
    });

    /* Scroll reveal */
    const reveals = document.querySelectorAll(".landing-reveal");
    if (reveals.length && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("is-visible");
                        observer.unobserve(entry.target);
                    }
                });
            },
            { rootMargin: "0px 0px -6% 0px", threshold: 0.06 }
        );
        reveals.forEach((el) => observer.observe(el));
    } else {
        reveals.forEach((el) => el.classList.add("is-visible"));
    }

    /* Hero app mockup scene tabs */
    const mockupScenes = document.querySelectorAll("[data-mockup-scene]");
    const mockupTabs = document.querySelectorAll("[data-mockup-tab]");
    if (mockupScenes.length && mockupTabs.length) {
        let mockupTimer = null;
        const sceneOrder = ["find", "home"];
        let sceneIndex = 0;

        const setMockupScene = (name) => {
            mockupScenes.forEach((scene) => {
                const active = scene.getAttribute("data-mockup-scene") === name;
                scene.classList.toggle("is-active", active);
                scene.hidden = !active;
            });
            mockupTabs.forEach((tab) => {
                const active = tab.getAttribute("data-mockup-tab") === name;
                tab.classList.toggle("is-active", active);
                tab.setAttribute("aria-pressed", active ? "true" : "false");
            });
            sceneIndex = sceneOrder.indexOf(name);
        };

        const scheduleMockupRotation = () => {
            if (mockupTimer) window.clearInterval(mockupTimer);
            if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
            mockupTimer = window.setInterval(() => {
                sceneIndex = (sceneIndex + 1) % sceneOrder.length;
                setMockupScene(sceneOrder[sceneIndex]);
            }, 6000);
        };

        mockupTabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                const name = tab.getAttribute("data-mockup-tab");
                if (!name) return;
                setMockupScene(name);
                scheduleMockupRotation();
            });
        });

        scheduleMockupRotation();
    }
})();
