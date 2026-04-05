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
  const COMPENSATORY = "Компенсирующее занятие";
  const categorySelect = document.getElementById("category");
  const moduleSelect = document.getElementById("module");
  const lessonSelect = document.getElementById("lesson");
  const weekdaySelect = document.getElementById("weekday");
  const timeSelect = document.getElementById("time");
  const moduleLessonFields = document.getElementById("moduleLessonFields");

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

  function applyCompensatoryUi() {
    const isComp = categorySelect && categorySelect.value === COMPENSATORY;
    if (moduleLessonFields) {
      moduleLessonFields.classList.toggle("d-none", isComp);
    }
    if (moduleSelect) {
      moduleSelect.required = !isComp;
      if (isComp) moduleSelect.value = "";
    }
    if (lessonSelect) {
      lessonSelect.required = !isComp;
      if (isComp) lessonSelect.value = "";
    }
    if (isComp) return;
    updateModules();
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
  categorySelect?.addEventListener("change", applyCompensatoryUi);
  moduleSelect?.addEventListener("change", updateLessons);

  syncChannelIds();
  if (categorySelect) applyCompensatoryUi();
  fillTimeOptions();

  const previewOverlay = document.getElementById("previewOverlay");
  const previewContent = document.getElementById("previewContent");
  const previewFinalHidden = document.getElementById("preview_final_text");
  const submitBtn = document.getElementById("submitBtn");
  const confirmPublishBtn = document.getElementById("confirmPublishBtn");
  const closePreviewBtn = document.getElementById("closePreviewBtn");
  const cancelPreviewBtn = document.getElementById("cancelPreviewBtn");
  if (previewOverlay && previewContent && submitBtn && confirmPublishBtn) {
    const resetPreviewHidden = () => {
      if (previewFinalHidden) previewFinalHidden.value = "";
    };

    const openPreview = () => {
      previewOverlay.classList.remove("d-none");
      if (confirmPublishBtn) {
        confirmPublishBtn.disabled = false;
        confirmPublishBtn.textContent = "✅ Подтверждаю публикацию";
      }
    };

    const closePreview = () => {
      previewOverlay.classList.add("d-none");
      resetPreviewHidden();
    };

    const loadPreview = async () => {
      resetPreviewHidden();
      const payload = Object.fromEntries(new FormData(postForm).entries());
      try {
        submitBtn.disabled = true;
        submitBtn.textContent = "Подготовка предпросмотра...";
        const resp = await fetch("/api/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        previewContent.value = data.preview_text || data.error || "Нет данных";
      } catch (e) {
        previewContent.value = `Ошибка предпросмотра: ${e}`;
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Опубликовать";
      }
    };

    submitBtn?.addEventListener("click", async () => {
      const mode = postForm.dataset.formMode || "";
      if (mode === "camp") {
        const ta = postForm.querySelector("[name=user_text]");
        const mediaInput = document.getElementById("media_files");
        const hasText = ta && ta.value.trim().length > 0;
        const hasFiles = mediaInput && mediaInput.files && mediaInput.files.length > 0;
        if (!hasText && !hasFiles) {
          alert("Введите текст поста или прикрепите фото/видео.");
          return;
        }
      }
      if (!postForm.reportValidity()) return;
      await loadPreview();
      openPreview();
    });

    confirmPublishBtn?.addEventListener("click", () => {
      if (previewFinalHidden) {
        previewFinalHidden.value = (previewContent.value || "").trim();
      }
      confirmPublishBtn.disabled = true;
      confirmPublishBtn.textContent = "Публикуем...";
      previewOverlay.classList.add("d-none");
      const loader = postForm.querySelector(".js-loader");
      if (loader) loader.classList.remove("d-none");
      postForm.submit();
    });

    closePreviewBtn?.addEventListener("click", closePreview);
    cancelPreviewBtn?.addEventListener("click", closePreview);
  }
})();
