"""Browser script for the catalog page.

It is a plain string, not an f-string, so braces need no doubling. Text for the user comes
from the JSON block with id "i18n" that the page embeds, in the page's language.
"""

CATALOG_JS = """
(() => {
  "use strict";
  const body = document.body;
  const i18n = JSON.parse(document.getElementById("i18n").textContent);
  const tbody = document.querySelector("tbody");
  const toast = document.getElementById("toast");
  const toastText = toast.querySelector("span");
  const toastUndo = toast.querySelector("button");
  let toastTimer = 0;
  const fill = (text, values) => text.replace(/\\{(\\w+)\\}/g, (_, key) => values[key]);

  const hideToast = () => {
    toast.hidden = true;
    clearTimeout(toastTimer);
  };
  const showToast = (message, undo) => {
    toastText.textContent = message;
    toastUndo.hidden = !undo;
    toastUndo.onclick = undo ? () => { hideToast(); undo(); } : null;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 7000);
  };

  const save = async (url, patch) => {
    const response = await fetch("/api/jobs/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, ...patch }),
      keepalive: true,
    });
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  };

  const marksOf = (row) => ({
    favorite: row.classList.contains("is-fav"),
    hidden: row.classList.contains("is-hidden"),
    viewed: row.classList.contains("viewed"),
    rating: Number(row.dataset.rating || 0),
  });

  const paint = (row, marks) => {
    row.classList.toggle("is-fav", marks.favorite);
    row.classList.toggle("is-hidden", marks.hidden);
    row.classList.toggle("viewed", marks.viewed);
    row.dataset.rating = String(marks.rating);
    const pressed = { favorite: marks.favorite, hidden: marks.hidden, viewed: marks.viewed };
    row.querySelectorAll(".act").forEach((button) => {
      button.setAttribute("aria-pressed", String(pressed[button.dataset.act]));
    });
    row.querySelectorAll(".star").forEach((button) => {
      const value = Number(button.dataset.value);
      button.classList.toggle("on", value <= marks.rating);
      button.setAttribute("aria-pressed", String(value === marks.rating));
    });
  };

  // Shows the change at once, then keeps what the server confirmed. Changes to one row are
  // sent one after another, so quick clicks cannot arrive out of order. Resolves to the
  // earlier marks, or null when the change could not be saved.
  const queues = new WeakMap();
  const change = (row, patch) => {
    const before = marksOf(row);
    const next = { ...before, ...patch };
    if (patch.favorite) next.hidden = false;
    if (patch.hidden) next.favorite = false;
    paint(row, next);
    const run = (queues.get(row) || Promise.resolve()).then(async () => {
      try {
        const saved = await save(row.dataset.url, patch);
        // Only the last change may repaint, or it would undo a newer click.
        if (queues.get(row) === run) paint(row, saved);
        return before;
      } catch (error) {
        if (queues.get(row) === run) paint(row, before);
        showToast(i18n.toastError);
        return null;
      }
    });
    queues.set(row, run);
    return run;
  };

  const opened = (row) => {
    if (!row.classList.contains("viewed")) change(row, { viewed: true });
  };

  const dialog = document.getElementById("company-reviews");
  const openCompany = (button) => {
    const data = JSON.parse(button.dataset.review);
    dialog.querySelector("h2").textContent = data.name;
    const rate = dialog.querySelector(".company-rate");
    const band = data.rating >= 70 ? "good" : data.rating >= 50 ? "mid" : "low";
    rate.className = "company-rate" + (data.rating == null ? "" : " " + band);
    const show = (node, text) => {
      node.hidden = !text;
      node.textContent = text || "";
    };
    show(rate, data.rating == null ? "" : fill(i18n.companyRate, { n: data.rating }));
    show(
      dialog.querySelector(".company-votes"),
      data.votes ? fill(i18n.companyVotes, { n: data.votes }) : ""
    );
    show(
      dialog.querySelector(".company-count"),
      data.reviews ? fill(i18n.companyReviews, { n: data.reviews }) : ""
    );
    dialog.querySelector(".company-none").hidden = data.rating != null;
    const list = dialog.querySelector(".company-links");
    list.replaceChildren();
    (data.links || []).forEach((link) => {
      const item = document.createElement("li");
      const anchor = document.createElement("a");
      anchor.href = link.href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = link.label;
      item.append(anchor);
      list.append(item);
    });
    dialog.showModal();
  };
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  tbody.addEventListener("click", async (event) => {
    const company = event.target.closest("button.company-open");
    if (company) {
      openCompany(company);
      return;
    }
    const row = event.target.closest("tr[data-url]");
    if (!row) return;
    if (event.target.closest("a[data-open]")) {
      opened(row);
      return;
    }
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const pressed = button.getAttribute("aria-pressed") === "true";
    const act = button.dataset.act;
    if (act === "favorite") {
      change(row, { favorite: !pressed });
    } else if (act === "viewed") {
      change(row, { viewed: !pressed });
    } else if (act === "rating") {
      const value = Number(button.dataset.value);
      change(row, { rating: marksOf(row).rating === value ? 0 : value });
    } else if (act === "hidden") {
      const before = await change(row, { hidden: !pressed });
      if (before && !pressed && body.dataset.showsHidden !== "1") {
        row.hidden = true;
        showToast(i18n.toastHidden, async () => {
          await change(row, { hidden: false, favorite: before.favorite });
          row.hidden = false;
        });
      }
    }
  });

  tbody.addEventListener("auxclick", (event) => {
    if (event.button !== 1) return;
    const row = event.target.closest("tr[data-url]");
    if (row && event.target.closest("a[data-open]")) opened(row);
  });

  const more = document.getElementById("more");
  if (more) {
    more.addEventListener("click", async () => {
      const params = new URLSearchParams(location.search);
      params.set("page", more.dataset.next);
      const label = more.textContent;
      more.disabled = true;
      more.textContent = i18n.loading;
      try {
        const response = await fetch("/fragments/rows?" + params);
        if (!response.ok) throw new Error(String(response.status));
        const data = await response.json();
        tbody.insertAdjacentHTML("beforeend", data.html);
        const shown = document.getElementById("shown");
        shown.textContent =
          fill(i18n.showing, { first: shown.dataset.first, last: data.last, total: data.total }) +
          (shown.dataset.note || "");
        const pager = document.querySelector(".pager");
        if (pager) pager.hidden = true;
        if (data.next) {
          more.dataset.next = String(data.next);
          more.textContent = data.more_label;
          more.disabled = false;
        } else {
          more.hidden = true;
        }
      } catch (error) {
        more.textContent = i18n.loadError;
        more.disabled = false;
        setTimeout(() => { more.textContent = label; }, 3000);
      }
    });
  }

  // On a phone the filters start folded, so the list is the first thing on screen.
  if (window.matchMedia("(max-width: 640px)").matches) {
    document.querySelectorAll("details[open]").forEach((box) => { box.open = false; });
  }

  const form = document.getElementById("filters");
  if (form) {
    form.addEventListener("change", (event) => {
      if (event.target.matches("select, input[type=checkbox]")) form.requestSubmit();
    });
  }

  if (body.dataset.refreshing === "1") {
    setInterval(async () => {
      try {
        const response = await fetch("/api/status");
        if (!response.ok) return;
        const data = await response.json();
        if (data.running === false) location.reload();
      } catch (error) {
        /* keep polling; one failed status check should not freeze the page */
      }
    }, 4000);
  }
})();
"""
