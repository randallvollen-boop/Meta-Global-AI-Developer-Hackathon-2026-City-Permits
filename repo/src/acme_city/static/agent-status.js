/* Refresh the read-only operator status without starting processing. */
(() => {
  const selector = "[data-status-refresh]";

  const editing = () => {
    const active = document.activeElement;
    return document.hidden || Boolean(active && active.matches("input, select, textarea"));
  };

  const refresh = async () => {
    if (editing()) return false;
    const response = await fetch(window.location.href, { credentials: "same-origin" });
    if (!response.ok) return false;
    const next = new DOMParser().parseFromString(await response.text(), "text/html");
    const currentParts = document.querySelectorAll(selector);
    const nextParts = next.querySelectorAll(selector);
    if (currentParts.length !== nextParts.length) return false;
    currentParts.forEach((part, index) => part.replaceWith(nextParts[index]));
    return true;
  };

  document.querySelectorAll("[data-status-refresh-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      void refresh();
    });
  });
  window.setInterval(() => { void refresh(); }, 5000);
})();
