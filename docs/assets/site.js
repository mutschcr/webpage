/* Interactions for the static MLPS site. The page content is ordinary HTML. */
(() => {
  "use strict";

  function followOldPublicationLink() {
    const count = document.querySelector('meta[name="mlps-publication-pages"]');
    if (!count) return false;
    const url = new URL(location.href);
    const value = url.searchParams.get("pg");
    if (!value || !/^[1-9]\d*$/.test(value)) return false;
    const page = Number(value);
    if (!Number.isSafeInteger(page) || page > Number(count.content)) return false;
    url.searchParams.delete("pg");
    if (page > 1) {
      const directory = url.pathname.replace(/\/index\.html$/i, "/").replace(/\/?$/, "/");
      url.pathname = directory + "page/" + page + "/";
    }
    location.replace(url.href);
    return true;
  }

  function updateHeaderHeight() {
    const header = document.querySelector(".si-sticky-header #sinatra-header-inner");
    const placeholder = document.getElementById("si-sticky-placeholder");
    if (!header || !placeholder) return;
    function measure() {
      const height = header.getBoundingClientRect().height + "px";
      placeholder.style.height = height;
      document.documentElement.style.setProperty("--mlps-header-height", height);
    }
    measure();
    if ("ResizeObserver" in window) new ResizeObserver(measure).observe(header);
    else window.addEventListener("resize", measure);
  }

  function prepareNavigation() {
    const header = document.getElementById("masthead");
    const burger = header?.querySelector(".si-hamburger");
    const nav = header?.querySelector(".site-navigation");
    if (!burger || !nav) return;
    const mobile = window.matchMedia("(max-width: 960px)");
    const toggles = [];

    function setSubmenu(button, open) {
      button.parentElement.classList.toggle("si-open", open);
      button.setAttribute("aria-expanded", String(open));
    }
    function setMenu(open) {
      document.body.classList.toggle("is-mobile-menu-active", open);
      burger.setAttribute("aria-expanded", String(open));
      if (!open) toggles.forEach(button => setSubmenu(button, false));
    }

    nav.querySelectorAll(".menu-item-has-children").forEach((item, index) => {
      const list = item.querySelector(":scope > .sub-menu");
      const link = item.querySelector(":scope > a");
      if (!link || !list) return;
      if (!list.id) list.id = "mlps-submenu-" + (index + 1);
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "mlps-submenu-toggle";
      toggle.setAttribute("aria-label", link.textContent.trim() + " submenu");
      toggle.setAttribute("aria-controls", list.id);
      toggle.setAttribute("aria-expanded", "false");
      const icon = link.querySelector(":scope > .si-icon")?.cloneNode(true);
      if (icon) {
        icon.setAttribute("aria-hidden", "true");
        toggle.append(icon);
      }
      item.insertBefore(toggle, list);
      toggles.push(toggle);
      toggle.addEventListener("click", () => setSubmenu(toggle, !item.classList.contains("si-open")));
      item.addEventListener("pointerenter", () => item.classList.remove("mlps-menu-dismissed"));
      item.addEventListener("focusout", event => {
        if (!item.contains(event.relatedTarget)) item.classList.remove("mlps-menu-dismissed");
      });
      item.addEventListener("keydown", event => {
        if (!mobile.matches && event.key === "ArrowDown" && event.target === link) {
          event.preventDefault();
          item.classList.remove("mlps-menu-dismissed");
          list.querySelector("a")?.focus();
        }
        if (event.key !== "Escape" || (mobile.matches && !item.classList.contains("si-open"))) return;
        event.preventDefault();
        event.stopPropagation();
        setSubmenu(toggle, false);
        if (mobile.matches) toggle.focus();
        else {
          link.focus();
          item.classList.add("mlps-menu-dismissed");
        }
      });
    });
    const syncViewport = () => {
      document.body.classList.toggle("sinatra-is-mobile", mobile.matches);
      setMenu(false);
    };
    syncViewport();
    mobile.addEventListener("change", syncViewport);
    burger.addEventListener("click", () => setMenu(!document.body.classList.contains("is-mobile-menu-active")));
    document.addEventListener("click", event => {
      if (!header.contains(event.target) && document.body.classList.contains("is-mobile-menu-active")) setMenu(false);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && document.body.classList.contains("is-mobile-menu-active")) {
        event.preventDefault();
        setMenu(false);
        burger.focus();
      }
    });
    header.addEventListener("focusout", event => {
      if (event.relatedTarget && !header.contains(event.relatedTarget) && mobile.matches) setMenu(false);
    });
  }

  function prepareScrollToTop() {
    const link = document.getElementById("si-scroll-top");
    if (!link) return;
    function sync() {
      const visible = window.scrollY > 300;
      link.classList.toggle("si-visible", visible);
      link.tabIndex = visible ? 0 : -1;
      link.setAttribute("aria-hidden", String(!visible));
    }
    sync();
    window.addEventListener("scroll", sync, {passive: true});
    link.addEventListener("click", event => {
      event.preventDefault();
      if (event.detail === 0) document.querySelector("#masthead a[href]")?.focus({preventScroll: true});
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({top: 0, behavior: reducedMotion ? "instant" : "smooth"});
    });
  }

  function prepareAccordions() {
    function setOpen(panel, open) {
      const button = document.getElementById(panel.getAttribute("aria-labelledby"));
      if (!button) return;
      button.setAttribute("aria-expanded", String(open));
      panel.closest(".wp-block-accordion-item")?.classList.toggle("is-open", open);
      if (open) panel.removeAttribute("hidden");
      else panel.setAttribute("hidden", "until-found");
    }
    document.querySelectorAll(".wp-block-accordion-heading__toggle").forEach(button => {
      const panel = document.getElementById(button.getAttribute("aria-controls"));
      if (!panel) return;
      setOpen(panel, button.getAttribute("aria-expanded") === "true");
      button.addEventListener("click", () => setOpen(panel, button.getAttribute("aria-expanded") !== "true"));
      panel.addEventListener("beforematch", () => setOpen(panel, true));
    });
    function revealAnchor() {
      if (!location.hash) return;
      let id;
      try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
      const target = document.getElementById(id);
      const item = target?.closest(".wp-block-accordion-item");
      const panel = item?.querySelector(".wp-block-accordion-panel");
      if (panel?.hasAttribute("hidden")) {
        setOpen(panel, true);
        target.scrollIntoView();
      }
    }
    revealAnchor();
    window.addEventListener("hashchange", revealAnchor);
  }

  function prepareTableOfContents() {
    const toc = document.getElementById("ez-toc-container");
    const checkbox = toc?.querySelector('input[type="checkbox"]');
    const list = toc?.querySelector("nav");
    if (!checkbox || !list) return;
    if (!list.id) list.id = "mlps-table-of-contents";
    list.setAttribute("aria-label", "Table of contents");
    checkbox.setAttribute("aria-label", "Show table of contents");
    checkbox.setAttribute("aria-controls", list.id);
  }

  function prepareCitations() {
    const buttons = document.querySelectorAll(".publication-bibtex-button");
    if (!buttons.length) return;
    const status = document.createElement("span");
    status.className = "screen-reader-text";
    status.setAttribute("role", "status");
    document.body.append(status);

    buttons.forEach(button => {
      const source = button.closest(".publication-card")?.querySelector(".publication-bibtex-source");
      if (!source) return;
      let timer;
      button.addEventListener("click", async () => {
        clearTimeout(timer);
        let copied = false;
        try {
          await navigator.clipboard.writeText(source.value);
          copied = true;
        } catch {
          // Local files or browsers that block clipboard writes still offer ordinary text selection.
          source.hidden = false;
          source.readOnly = true;
          source.classList.add("mlps-bibtex-fallback");
          source.setAttribute("aria-label", "BibTeX citation");
          source.focus({preventScroll: true});
          source.select();
          try { copied = document.execCommand("copy"); } catch { /* The selected citation stays visible. */ }
        }
        if (copied) {
          if (!source.hidden) {
            source.hidden = true;
            button.focus({preventScroll: true});
          }
          status.textContent = "BibTeX citation copied.";
          button.textContent = "Copied!";
          timer = setTimeout(() => { button.textContent = "BibTeX"; status.textContent = ""; }, 1500);
        } else {
          button.textContent = "BibTeX";
          status.textContent = "BibTeX selected. Use your usual copy command.";
        }
      });
    });
  }

  function initialize() {
    if (followOldPublicationLink()) return;
    prepareNavigation();
    updateHeaderHeight();
    prepareScrollToTop();
    prepareAccordions();
    prepareTableOfContents();
    prepareCitations();
    document.documentElement.classList.add("mlps-js");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, {once: true});
  else initialize();
})();
