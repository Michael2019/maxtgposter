(() => {
  const root = document.documentElement;
  const toggle = document.getElementById("themeToggle");
  const saved = localStorage.getItem("theme");
  if (saved) {
    root.setAttribute("data-bs-theme", saved);
  }
  if (toggle) {
    toggle.addEventListener("click", () => {
      const current = root.getAttribute("data-bs-theme") || "light";
      const next = current === "light" ? "dark" : "light";
      root.setAttribute("data-bs-theme", next);
      localStorage.setItem("theme", next);
    });
  }

  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", () => {
      const loader = form.querySelector(".js-loader");
      if (loader) loader.classList.remove("d-none");
    });
  });

  const postForm = document.getElementById("postForm");
  if (!postForm) return;

  const channelSelect = document.getElementById("channel");
  const telegramHidden = document.getElementById("telegram_chat_id");
  const maxHidden = document.getElementById("max_chat_id");
  const categorySelect = document.getElementById("category");
  const moduleSelect = document.getElementById("module");
  const lessonSelect = document.getElementById("lesson");
  const timeSelect = document.getElementById("time");

  const months = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
  ];

  function syncChannelIds() {
    if (!channelSelect || !telegramHidden || !maxHidden) return;
    const option = channelSelect.options[channelSelect.selectedIndex];
    telegramHidden.value = option?.dataset?.telegram || "";
    maxHidden.value = option?.dataset?.max || "";
  }

  function updateModules() {
    if (!categorySelect || !moduleSelect) return;
    const category = categorySelect.value;
    moduleSelect.innerHTML = '<option value="">-- Модуль --</option>';
    const options = (category === "Робик 1" || category === "Робик 2")
      ? months.map((m) => ({ value: m, text: m.charAt(0).toUpperCase() + m.slice(1) }))
      : [{ value: "1", text: "Модуль 1" }, { value: "2", text: "Модуль 2" }];

    options.forEach((opt) => {
      const option = document.createElement("option");
      option.value = opt.value;
      option.textContent = opt.text;
      moduleSelect.appendChild(option);
    });
    updateLessons();
  }

  function updateLessons() {
    if (!moduleSelect || !lessonSelect) return;
    const moduleVal = moduleSelect.value;
    lessonSelect.innerHTML = '<option value="">-- Занятие --</option>';
    let maxLesson = 0;
    if (moduleVal === "1") maxLesson = 17;
    else if (moduleVal === "2") maxLesson = 20;
    else if (months.includes(moduleVal)) maxLesson = 5;
    for (let i = 1; i <= maxLesson; i += 1) {
      const option = document.createElement("option");
      option.value = String(i);
      option.textContent = `Занятие ${i}`;
      lessonSelect.appendChild(option);
    }
  }

  function fillTimeOptions() {
    if (!timeSelect || timeSelect.options.length > 1) return;
    for (let hour = 10; hour <= 20; hour += 1) {
      for (let minute = 0; minute < 60; minute += 15) {
        if (hour === 20 && minute > 0) break;
        const hh = String(hour).padStart(2, "0");
        const mm = String(minute).padStart(2, "0");
        const time = `${hh}:${mm}`;
        const option = document.createElement("option");
        option.value = time;
        option.textContent = time;
        timeSelect.appendChild(option);
      }
    }
  }

  channelSelect?.addEventListener("change", syncChannelIds);
  categorySelect?.addEventListener("change", updateModules);
  moduleSelect?.addEventListener("change", updateLessons);

  syncChannelIds();
  if (categorySelect) updateModules();
  fillTimeOptions();
})();
