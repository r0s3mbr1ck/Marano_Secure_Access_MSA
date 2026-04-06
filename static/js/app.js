function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  const main = document.getElementById("main-shell");
  const btn = document.querySelector(".menu-toggle");
  const isOpen = sidebar.classList.contains("open");

  btn.classList.toggle("active");

  if (isOpen) {
    sidebar.classList.remove("open");
    backdrop.classList.remove("show");
    main.classList.remove("shifted");
  } else {
    sidebar.classList.add("open");
    backdrop.classList.add("show");
    if (window.innerWidth > 900) {
      main.classList.add("shifted");
    }
  }
}

function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebar-backdrop").classList.remove("show");
  document.getElementById("main-shell").classList.remove("shifted");
  const btn = document.querySelector(".menu-toggle");
  if (btn) btn.classList.remove("active");
}

window.addEventListener("resize", () => {
  if (window.innerWidth <= 900) {
    document.getElementById("main-shell").classList.remove("shifted");
  }
});

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form").forEach((f) => {
    f.addEventListener("submit", () => {
      const btn = f.querySelector("button");
      if (btn) {
        btn.classList.add("loading");
        btn.innerText = "Processando...";
      }
    });
  });
});
