(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const form = $("upload-form");
  if (!form) return;

  const drop = $("drop");
  const input = $("file");
  const fileRow = $("file-row");
  const fileName = $("file-name");
  const fileSize = $("file-size");
  const preview = $("preview");
  const clearBtn = $("clear-file");
  const title = $("title");
  const titleCount = $("title-count");
  const privacy = $("privacy");
  const submit = $("submit");
  const progress = $("progress");
  const barFill = $("bar-fill");
  const progressLabel = $("progress-label");
  const progressPct = $("progress-pct");
  const formError = $("form-error");
  const postsBox = $("posts");
  const refreshBtn = $("refresh");
  const modeHint = $("mode-hint");

  const STATUS = {
    CREATED: "Создано",
    PROCESSING_UPLOAD: "Загружаем видео",
    PROCESSING_DOWNLOAD: "TikTok обрабатывает видео",
    SEND_TO_USER_INBOX: "Отправлено в черновики TikTok",
    PUBLISH_COMPLETE: "Опубликовано",
    FAILED: "Ошибка",
  };
  const FINAL = new Set(["PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"]);
  const ACCEPTED = ["mp4", "mov", "webm", "m4v"];

  let selectedFile = null;
  let previewUrl = null;
  let pollingTimer = null;

  const MB = 1024 * 1024;
  const maxBytes = (window.APP?.maxMb || 500) * MB;

  function humanSize(bytes) {
    if (bytes >= MB) return (bytes / MB).toFixed(1) + " МБ";
    return Math.max(1, Math.round(bytes / 1024)) + " КБ";
  }

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }

  function hideError() {
    formError.hidden = true;
    formError.textContent = "";
  }

  function setFile(file) {
    if (!file) return;
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      showError("Нужен файл MP4, MOV, WEBM или M4V.");
      return;
    }
    if (file.size > maxBytes) {
      showError("Файл больше " + (window.APP?.maxMb || 500) + " МБ.");
      return;
    }
    hideError();
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = humanSize(file.size);
    fileRow.hidden = false;
    drop.hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    submit.disabled = false;
  }

  function clearFile() {
    selectedFile = null;
    input.value = "";
    fileRow.hidden = true;
    drop.hidden = false;
    submit.disabled = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    preview.removeAttribute("src");
  }

  drop.addEventListener("click", () => input.click());
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("over");
    const file = event.dataTransfer?.files?.[0];
    if (file) setFile(file);
  });
  input.addEventListener("change", () => setFile(input.files?.[0]));
  clearBtn.addEventListener("click", clearFile);

  title.addEventListener("input", () => {
    titleCount.textContent = String(title.value.length);
  });

  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      if (radio.checked && radio.value === "direct") {
        modeHint.textContent =
          "Прямая публикация требует одобренного доступа Content Posting API. " +
          "До аудита TikTok может отклонить пост или сохранить его как приватный.";
      } else if (radio.checked) {
        modeHint.textContent =
          "Видео появится в черновиках TikTok. Вы сами добавите звук и опубликуете — " +
          "этот режим работает без аудита приложения.";
      }
    });
  });

  function setProgress(percent, label) {
    progress.hidden = false;
    barFill.style.width = Math.min(100, Math.max(0, percent)) + "%";
    progressLabel.textContent = label;
    progressPct.textContent = Math.round(percent) + "%";
  }

  function statusClass(status) {
    return "status " + String(status || "").toLowerCase();
  }

  function makePostEl(post) {
    const article = document.createElement("article");
    article.className = "post";
    article.dataset.id = post.id;
    article.dataset.status = post.status;

    const main = document.createElement("div");
    main.className = "post-main";
    const titleEl = document.createElement("div");
    titleEl.className = "post-title";
    titleEl.textContent = post.title || "Без описания";
    const meta = document.createElement("div");
    meta.className = "muted tiny";
    meta.textContent =
      (post.mode === "direct" ? "Публикация" : "Черновик") +
      " · " +
      (post.privacy_label || post.privacy_level) +
      " · " +
      humanSize(post.video_size || 0);
    main.append(titleEl, meta);
    if (post.fail_reason) {
      const fail = document.createElement("div");
      fail.className = "fail tiny";
      fail.textContent = post.fail_reason;
      main.append(fail);
    }

    const badge = document.createElement("span");
    badge.className = statusClass(post.status);
    badge.textContent = post.status_label || STATUS[post.status] || post.status;
    article.append(main, badge);
    return article;
  }

  function renderPosts(posts) {
    postsBox.replaceChildren();
    if (!posts.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Пока нет загрузок. Первое видео появится здесь.";
      postsBox.append(empty);
      return;
    }
    posts.forEach((post) => postsBox.append(makePostEl(post)));
  }

  async function loadPosts() {
    const response = await fetch("/api/posts", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const data = await response.json();
    renderPosts(data.posts || []);
  }

  async function pollActive() {
    const active = [...postsBox.querySelectorAll(".post")].filter(
      (el) => !FINAL.has(el.dataset.status)
    );
    await Promise.all(
      active.map(async (el) => {
        try {
          const response = await fetch("/api/posts/" + el.dataset.id, {
            headers: { Accept: "application/json" },
          });
          if (!response.ok) return;
          const post = await response.json();
          const badge = el.querySelector(".status");
          if (badge) {
            badge.className = statusClass(post.status);
            badge.textContent = post.status_label || STATUS[post.status] || post.status;
          }
          el.dataset.status = post.status;
        } catch (_) {
          /* keep polling */
        }
      })
    );
    if (active.length) schedulePoll();
  }

  function schedulePoll() {
    if (pollingTimer) clearTimeout(pollingTimer);
    pollingTimer = setTimeout(pollActive, 3000);
  }

  function waitForFinal(postId) {
    return new Promise((resolve) => {
      let attempts = 0;
      const tick = async () => {
        attempts += 1;
        try {
          const response = await fetch("/api/posts/" + postId, {
            headers: { Accept: "application/json" },
          });
          if (response.ok) {
            const post = await response.json();
            setProgress(100, STATUS[post.status] || "Обработка…");
            if (FINAL.has(post.status)) return resolve(post);
          }
        } catch (_) {
          /* transient */
        }
        if (attempts > 80) return resolve(null);
        setTimeout(tick, 2500);
      };
      tick();
    });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    hideError();
    if (!selectedFile) {
      showError("Сначала выберите видео.");
      return;
    }
    const mode = form.querySelector('input[name="mode"]:checked')?.value || "inbox";
    const data = new FormData();
    data.append("file", selectedFile, selectedFile.name);
    data.append("title", title.value);
    data.append("privacy_level", privacy.value);
    data.append("mode", mode);

    submit.disabled = true;
    setProgress(0, "Загружаем на сервер…");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.responseType = "json";

    xhr.upload.onprogress = (progressEvent) => {
      if (!progressEvent.lengthComputable) return;
      const percent = (progressEvent.loaded / progressEvent.total) * 92;
      setProgress(percent, "Загружаем видео…");
    };

    xhr.onerror = () => {
      showError("Сеть недоступна. Попробуйте ещё раз.");
      submit.disabled = false;
    };

    xhr.onload = async () => {
      const payload = xhr.response || {};
      if (xhr.status >= 200 && xhr.status < 300 && payload.post) {
        setProgress(94, "Передаём в TikTok…");
        const post = await waitForFinal(payload.post.id);
        await loadPosts();
        if (post && post.status === "FAILED") {
          showError(post.fail_reason || "TikTok отклонил публикацию.");
        }
        clearFile();
        title.value = "";
        titleCount.textContent = "0";
        setTimeout(() => {
          progress.hidden = true;
          barFill.style.width = "0%";
        }, 2200);
        submit.disabled = true;
        schedulePoll();
      } else {
        showError(payload.error || payload.detail || "Не удалось загрузить видео.");
        submit.disabled = false;
        progress.hidden = true;
      }
    };

    xhr.send(data);
  });

  refreshBtn?.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    await loadPosts();
    refreshBtn.disabled = false;
    schedulePoll();
  });

  $("disconnect")?.addEventListener("click", async () => {
    if (!confirm("Отключить TikTok и удалить сохранённый токен?")) return;
    await fetch("/api/disconnect", { method: "POST" });
    location.href = "/";
  });

  schedulePoll();
})();
