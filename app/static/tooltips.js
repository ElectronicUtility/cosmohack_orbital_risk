import { esc } from "./model.js?v=20260919-7";

export function infoButton(text, label = "Подробнее") {
  return `<button type="button" class="info-button" aria-label="${esc(label)}" data-tip="${esc(text)}" data-tip-toggle><svg aria-hidden="true"><use href="#i-info"/></svg></button>`;
}

// One top-layer tooltip works in the workspace, modal dialogs and fullscreen.
// It never intercepts a normal action: touch toggling is reserved for info buttons.
export function initTooltips() {
  const bubble = document.createElement("div");
  bubble.id = "ui-tooltip";
  bubble.className = "ui-tooltip";
  bubble.setAttribute("role", "tooltip");
  bubble.setAttribute("popover", "manual");
  document.body.append(bubble);
  let trigger = null,
    timer,
    dismissed = null,
    pinned = false;
  const selector = "[data-tip], button[title], button[aria-label]";
  const description = (el) =>
    el?.getAttribute("title") ||
    el?.dataset.tip ||
    (el?.matches("button[aria-label]") && !el.textContent.trim()
      ? el.getAttribute("aria-label")
      : "");
  const find = (node) =>
    node instanceof Element ? node.closest(selector) : null;
  function hide() {
    clearTimeout(timer);
    if (trigger) {
      const ids = (trigger.getAttribute("aria-describedby") || "")
        .split(/\s+/)
        .filter((id) => id && id !== bubble.id);
      if (ids.length) trigger.setAttribute("aria-describedby", ids.join(" "));
      else trigger.removeAttribute("aria-describedby");
      if (trigger.hasAttribute("data-tip-toggle"))
        trigger.setAttribute("aria-expanded", "false");
    }
    bubble.hidePopover();
    trigger = null;
    pinned = false;
  }
  function place() {
    if (!trigger?.isConnected) return hide();
    const box = trigger.getBoundingClientRect(),
      width = document.documentElement.clientWidth;
    const height = window.innerHeight,
      tip = bubble.getBoundingClientRect();
    const left = Math.max(
      12,
      Math.min(
        width - tip.width - 12,
        box.left + box.width / 2 - tip.width / 2,
      ),
    );
    const below = box.bottom + 9;
    const top =
      below + tip.height < height - 12
        ? below
        : Math.max(12, box.top - tip.height - 9);
    bubble.style.left = `${left}px`;
    bubble.style.top = `${top}px`;
  }
  function show(el, pin = false) {
    const text = description(el);
    if (!text || !el?.isConnected || el === dismissed || el.disabled) return;
    hide();
    // Convert native titles to avoid two overlapping tooltips. Dynamic titles
    // (play/pause/fullscreen) are still read on each subsequent opening.
    if (el.hasAttribute("title")) {
      el.dataset.tip = text;
      el.removeAttribute("title");
    }
    trigger = el;
    pinned = pin;
    bubble.textContent = text;
    const ids = (el.getAttribute("aria-describedby") || "")
      .split(/\s+/)
      .filter(Boolean);
    el.setAttribute(
      "aria-describedby",
      [...new Set([...ids, bubble.id])].join(" "),
    );
    if (el.hasAttribute("data-tip-toggle"))
      el.setAttribute("aria-expanded", "true");
    bubble.showPopover();
    place();
  }
  document.addEventListener("pointerover", (e) => {
    if (e.pointerType === "touch" || pinned) return;
    const el = find(e.target);
    if (!el || el.contains(e.relatedTarget) || !description(el)) return;
    dismissed = null;
    clearTimeout(timer);
    timer = setTimeout(() => show(el), 280);
  });
  document.addEventListener("pointerout", (e) => {
    const el = find(e.target);
    if (
      !el ||
      el.contains(e.relatedTarget) ||
      bubble.contains(e.relatedTarget) ||
      pinned
    )
      return;
    dismissed = null;
    clearTimeout(timer);
    timer = setTimeout(hide, 160);
  });
  bubble.addEventListener("pointerenter", () => clearTimeout(timer));
  bubble.addEventListener("pointerleave", () => {
    if (!pinned) hide();
  });
  document.addEventListener("focusin", (e) => {
    dismissed = null;
    const el = find(e.target);
    if (el?.matches(":focus-visible")) show(el);
  });
  document.addEventListener("focusout", (e) => {
    if (e.target === trigger) hide();
  });
  document.addEventListener("click", (e) => {
    const el = find(e.target);
    if (el?.hasAttribute("data-tip-toggle")) {
      e.preventDefault();
      const close = trigger === el && pinned;
      dismissed = null;
      if (close) hide();
      else show(el, true);
    } else if (!bubble.contains(e.target)) hide();
  });
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape" && trigger) {
        dismissed = trigger;
        hide();
        // Dismiss the tooltip first, preserving an open parameter dialog.
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true,
  );
  document.addEventListener(
    "scroll",
    (e) => {
      if (!bubble.contains(e.target)) hide();
    },
    true,
  );
  window.addEventListener("resize", hide);
  document.addEventListener("fullscreenchange", hide);
  new MutationObserver(() => {
    if (
      trigger &&
      (!trigger.isConnected ||
        !trigger.getClientRects().length ||
        trigger.closest("[hidden]"))
    )
      hide();
    else if (trigger && bubble.textContent !== description(trigger)) {
      bubble.textContent = description(trigger);
      place();
    }
  }).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["hidden", "data-tip", "title", "aria-label"],
  });
  return { hide };
}
