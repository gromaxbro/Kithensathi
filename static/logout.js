document.querySelectorAll("[data-logout]").forEach((el) => {
  el.addEventListener("click", async (event) => {
    event.preventDefault();
    try { await fetch("/api/logout", { method: "POST" }); } catch {}
    location.replace("/login");
  });
});
