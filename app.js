(() => {
  "use strict";
  const data = window.BVB_DATA;
  const gallery = window.BVB_GALLERY;
  if (!Array.isArray(data) || !data.length || !Array.isArray(gallery)) return;
  const $ = (id) => document.getElementById(id);
  const escape = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const colors = {
    OpenAI: "#7450c5",
    Meta: "#0866ff",
    Anthropic: "#d17b43",
    Google: "#3679b8",
    xAI: "#53687c",
    "Zhipu AI": "#bd5779",
    Alibaba: "#c39020",
    "Moonshot AI": "#278477",
    MiniMax: "#8c65a5",
    ByteDance: "#638749",
  };
  const axisNames = {
    overall: "Overall",
    dualVqa: "Dual VQA",
    latentSim: "Latent Similarity",
    layout: "Layout",
    motion: "Motion",
    costUsd: "Cost per scene",
    runtimeMin: "Runtime per scene",
  };
  const axisColors = {
    overall: "#7450c5",
    dualVqa: "#0072b2",
    latentSim: "#d33760",
  };
  const tasks = [
    "object_counting",
    "object_abs_distance",
    "object_size_estimation",
    "room_size_estimation",
    "object_rel_distance",
    "object_rel_direction",
    "route_planning",
    "obj_appearance_order",
  ];
  const score = (n, digits = 1) =>
    Number.isFinite(n) ? n.toFixed(digits) : "—";
  const effort = (r) =>
    r.effort === "none"
      ? ""
      : `<span class="effort ${escape(r.effort)}">${escape(r.effort)}</span>`;
  const modelLogos = {
    "OpenAI": "openai.svg",
    "Meta": "meta.png",
    "Anthropic": "claude-color.svg",
    "Google": "gemini-color.svg",
    "xAI": "grok.svg",
    "Zhipu AI": "glm.png",
    "Alibaba": "qwen-color.svg",
    "Moonshot AI": "kimi.png",
    "MiniMax": "minimax-color.svg",
    "ByteDance": "seed.png"
};
  const modelLogo = (r) => {
    const icon = modelLogos[r.vendor];
    if (!icon) return "";
    const asset = `assets/model-logos/${icon}`;
    const src = window.BVB_STATIC_ASSETS?.[asset] || asset;
    return `<img class="model-logo" src="${escape(src)}" width="20" height="20" alt="" aria-hidden="true" />`;
  };
  const modelCell = (r) =>
    `<span class="model-identity" title="${escape(r.vendor)}">${modelLogo(r)}<span><strong>${escape(r.name)}</strong>${effort(r)}${
      r.openWeight ? '<span class="open-badge">open-weight</span>' : ""
    }</span></span>`;

  const harnessCell = (r) =>
    `<td class="harness-cell"><span class="harness-badge">${escape(r.harness)}</span></td>`;

  // The same exact manuscript values drive the charts, rankings, and task table.
  let sortKey = "overall";
  let ascending = false;
  function renderLeaderboard() {
    const search = $("model-search")
      .value.trim()
      .toLowerCase()
      .replace(/[-\s]+/g, " ");
    const availability = $("model-type").value;
    const reasoning = $("effort-filter").value;
    const ranked = [...data].sort(
      (a, b) =>
        (ascending ? a[sortKey] - b[sortKey] : b[sortKey] - a[sortKey]) ||
        a.rank - b.rank,
    );
    const ranking = new Map(ranked.map((r, i) => [r.run, i + 1]));
    const shown = ranked.filter((r) => {
      const haystack = `${r.name} ${r.vendor} ${r.effort} ${r.harness}`
        .toLowerCase()
        .replace(/[-\s]+/g, " ");
      return (
        (!search || haystack.includes(search)) &&
        (availability === "all" ||
          (availability === "open") === r.openWeight) &&
        (reasoning === "all" || reasoning === r.effort)
      );
    });
    $("leaderboard-body").innerHTML = shown
      .map((r) => {
        const rank = ranking.get(r.run);
        return `<tr><td><span class="rank-pill ${
          rank <= 3 ? "top" : ""
        }">${rank}</span></td><td class="model-cell">${modelCell(
          r,
        )}</td>${harnessCell(r)}<td class="score-cell"><span class="score-inner" style="--score:${
          r.overall
        }%"><span>${score(
          r.overall,
          2,
        )}</span></span></td><td class="score-cell dv-score">${score(
          r.dualVqa,
        )}</td><td class="score-cell ls-score">${score(
          r.latentSim,
        )}</td><td>${score(r.layout)}</td><td>${score(
          r.motion,
        )}</td><td>${score(r.costUsd, 3)}</td><td>${score(
          r.runtimeMin,
          2,
        )}</td></tr>`;
      })
      .join("");
    $("task-body").innerHTML = shown
      .map(
        (r) =>
          `<tr><td class="model-cell">${modelCell(r)}</td>${harnessCell(r)}${tasks
            .map(
              (k) =>
                `<td style="background:rgba(0,114,178,${(
                  (r.tasks[k] / 100) *
                  0.13
                ).toFixed(3)})">${score(r.tasks[k])}</td>`,
            )
            .join("")}</tr>`,
      )
      .join("");
    $("result-count").textContent = `${shown.length} of ${
      data.length
    } configurations · ${axisNames[sortKey]} ${ascending ? "↑" : "↓"}`;
    $("empty-state").hidden = shown.length > 0;
    document
      .querySelectorAll("[data-sort]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.sort === sortKey)),
      );
    document.querySelectorAll("th[data-column]").forEach((th) => {
      th.removeAttribute("aria-sort");
      th.querySelector("span").textContent = "↕";
      if (th.dataset.column === sortKey) {
        th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
        th.querySelector("span").textContent = ascending ? "↑" : "↓";
      }
    });
  }
  document.querySelectorAll("[data-sort]").forEach((b) =>
    b.addEventListener("click", () => {
      sortKey = b.dataset.sort;
      ascending = false;
      renderLeaderboard();
    }),
  );
  document.querySelectorAll("[data-column-sort]").forEach((b) =>
    b.addEventListener("click", () => {
      const key = b.dataset.columnSort;
      ascending =
        sortKey === key ? !ascending : ["costUsd", "runtimeMin"].includes(key);
      sortKey = key;
      renderLeaderboard();
    }),
  );
  $("model-search").addEventListener("input", renderLeaderboard);
  $("model-type").addEventListener("change", renderLeaderboard);
  $("effort-filter").addEventListener("change", renderLeaderboard);
  $("reset-filters").addEventListener("click", () => {
    $("model-search").value = "";
    $("model-type").value = "all";
    $("effort-filter").value = "all";
    renderLeaderboard();
    $("model-search").focus();
  });
  renderLeaderboard();

  // Native SVG keeps the data figure sharp without external charting dependencies.
  let chartAxis = "overall";
  let selectedRun = data[0].run;
  function showPoint(run) {
    const r = data.find((row) => row.run === run);
    if (!r) return;
    selectedRun = run;
    $("point-detail").innerHTML =
      `<span class="small-label">Selected configuration</span><h4>${escape(
        r.name,
      )} ${effort(r)}</h4><dl><div><dt>Overall</dt><dd>${score(
        r.overall,
        2,
      )}</dd></div><div><dt>Dual VQA</dt><dd>${score(
        r.dualVqa,
      )}</dd></div><div><dt>Latent Similarity</dt><dd>${score(
        r.latentSim,
      )}</dd></div><div><dt>Cost / scene</dt><dd>${score(
        r.costUsd,
        3,
      )}</dd></div></dl>`;
    document
      .querySelectorAll(".plot-point")
      .forEach((p) =>
        p.setAttribute("aria-pressed", String(p.dataset.run === run)),
      );
  }
  function renderCostChart() {
    const W = 740,
      H = 432,
      L = 57,
      R = 21,
      T = 30,
      B = 62;
    const lo = 0.02,
      hi = 3;
    const x = (v) =>
      L +
      ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) *
        (W - L - R);
    const yMin = { overall: 40, dualVqa: 35, latentSim: 45 }[chartAxis];
    const yMax = chartAxis === "dualVqa" ? 70 : 100;
    const yTicks = {
      overall: [40, 50, 60, 70, 80, 90, 100],
      dualVqa: [35, 40, 45, 50, 55, 60, 65, 70],
      latentSim: [45, 50, 60, 70, 80, 90, 100],
    }[chartAxis];
    const y = (v) => T + ((yMax - v) / (yMax - yMin)) * (H - T - B);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="group" aria-labelledby="cost-title cost-description"><title id="cost-title">${axisNames[chartAxis]} versus mean cost per scene</title><desc id="cost-description">All ${data.length} configurations. Logarithmic cost axis from 2 cents to 3 dollars. Score axis from ${yMin} to ${yMax}. Each point can be selected with a click, Enter, or Space; details appear beside the chart.</desc>`;
    for (const tick of yTicks)
      svg += `<line x1="${L}" y1="${y(tick)}" x2="${W - R}" y2="${y(
        tick,
      )}" stroke="#e7ebf1"/><text x="${L - 12}" y="${
        y(tick) + 5
      }" text-anchor="end" fill="#697585" font-size="14">${tick}</text>`;
    for (const tick of [0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 3])
      svg += `<line x1="${x(tick)}" y1="${H - B}" x2="${x(tick)}" y2="${
        H - B + 5
      }" stroke="#c7cfdb"/><text x="${x(tick)}" y="${
        H - B + 25
      }" text-anchor="middle" fill="#697585" font-size="13">${
        tick < 1 ? tick.toFixed(2) : tick
      }</text>`;
    svg += `<text x="${L}" y="16" fill="${
      axisColors[chartAxis]
    }" font-size="14" font-weight="650">${
      axisNames[chartAxis]
    } ↑</text><text x="${(L + W - R) / 2}" y="${
      H - 7
    }" fill="#697585" font-size="13" text-anchor="middle">Mean cost per scene (USD, log scale) →</text>`;
    const byCost = [...data].sort(
      (a, b) => a.costUsd - b.costUsd || b[chartAxis] - a[chartAxis],
    );
    let best = -Infinity;
    const frontier = [];
    for (const r of byCost)
      if (r[chartAxis] > best) {
        frontier.push(r);
        best = r[chartAxis];
      }
    let path = `M${x(frontier[0].costUsd)},${y(frontier[0][chartAxis])}`;
    for (const r of frontier.slice(1))
      path += `H${x(r.costUsd)}V${y(r[chartAxis])}`;
    path += `H${W - R}`;
    svg += `<path d="${path}" fill="none" stroke="${axisColors[chartAxis]}" stroke-opacity=".5" stroke-width="1.5" stroke-dasharray="5 5"/>`;
    const landmarkRuns = [
      data[0].run,
      data[1].run,
      data.find((r) => r.family === "GLM-5.3-Flash" && r.effort === "xhigh").run,
    ];
    for (const r of [...data].reverse()) {
      const label = `${r.name}, ${r.effort} effort. ${
        axisNames[chartAxis]
      } ${score(r[chartAxis], 2)}. ${score(r.costUsd, 3)} per scene.`;
      svg += `<circle class="plot-point" data-run="${escape(r.run)}" cx="${x(
        r.costUsd,
      ).toFixed(2)}" cy="${y(r[chartAxis]).toFixed(2)}" r="${
        landmarkRuns.includes(r.run) ? 6.5 : 5
      }" fill="${colors[r.vendor]}" fill-opacity="${
        landmarkRuns.includes(r.run) ? 1 : 0.72
      }" stroke="white" stroke-width="1.2" tabindex="0" role="button" aria-label="${escape(
        label,
      )}" aria-pressed="${r.run === selectedRun}"><title>${escape(
        label,
      )}</title></circle>`;
    }
    const placements = [
      [-10, -18, "end", "GPT-6 Astra · high"],
      [-10, 24, "end", "Claude Opus 5.5 · xhigh"],
      [10, -16, "start", "GLM 5.3 Flash"],
    ];
    landmarkRuns.forEach((run, i) => {
      const r = data.find((d) => d.run === run);
      const [dx, dy, anchor, name] = placements[i];
      svg += `<text x="${x(r.costUsd) + dx}" y="${
        y(r[chartAxis]) + dy
      }" text-anchor="${anchor}" fill="#434f63" font-size="13" font-weight="600" paint-order="stroke" stroke="white" stroke-width="4" stroke-linejoin="round" pointer-events="none">${name}</text>`;
    });
    $("cost-chart").innerHTML = svg + "</svg>";
    document.querySelectorAll(".plot-point").forEach((p) => {
      p.addEventListener("click", () => showPoint(p.dataset.run));
      p.addEventListener("focus", () => showPoint(p.dataset.run));
      p.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          showPoint(p.dataset.run);
        }
      });
    });
    document
      .querySelectorAll("[data-chart-axis]")
      .forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(b.dataset.chartAxis === chartAxis),
        ),
      );
    showPoint(selectedRun);
  }
  $("chart-legend").innerHTML = Object.entries(colors)
    .map(
      ([name, color]) =>
        `<span><i class="dot" style="background:${color}" aria-hidden="true"></i>${name}</span>`,
    )
    .join("");
  document.querySelectorAll("[data-chart-axis]").forEach((b) =>
    b.addEventListener("click", () => {
      chartAxis = b.dataset.chartAxis;
      renderCostChart();
    }),
  );
  renderCostChart();

  function renderReasoningChart() {
    const order = ["none", "low", "medium", "high", "xhigh"];
    const rows = order
      .map((e) =>
        data.find((r) => r.family === "GPT-5.6-Sol" && r.effort === e),
      )
      .filter(Boolean);
    const W = 465,
      H = 220,
      L = 36,
      R = 25,
      T = 24,
      B = 40;
    const x = (i) => L + (i * (W - L - R)) / (rows.length - 1),
      y = (v) => T + ((100 - v) / 100) * (H - T - B);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="effort-title effort-description"><title id="effort-title">GPT-5.6 Sol: reasoning effort and score</title><desc id="effort-description">${escape(
      rows
        .map(
          (r) =>
            `${r.effort}: Dual VQA ${score(
              r.dualVqa,
            )}, Latent Similarity ${score(r.latentSim)}.`,
        )
        .join(" "),
    )}</desc>`;
    for (const tick of [0, 25, 50, 75, 100])
      svg += `<line x1="${L}" y1="${y(tick)}" x2="${W - R}" y2="${y(
        tick,
      )}" stroke="#e8ecf2"/><text x="${L - 8}" y="${
        y(tick) + 4
      }" text-anchor="end" font-size="12" fill="#778292">${tick}</text>`;
    ["dualVqa", "latentSim"].forEach((k) => {
      svg += `<polyline points="${rows
        .map((r, i) => `${x(i)},${y(r[k])}`)
        .join(" ")}" fill="none" stroke="${
        axisColors[k]
      }" stroke-width="2.5"/>`;
      rows.forEach((r, i) => {
        svg += `<circle cx="${x(i)}" cy="${y(r[k])}" r="4.5" fill="${
          axisColors[k]
        }" stroke="white" stroke-width="1.4"/><text x="${x(i)}" y="${
          y(r[k]) + (k === "dualVqa" ? 21 : -11)
        }" text-anchor="middle" font-size="12" fill="${
          axisColors[k]
        }" font-weight="600">${score(r[k])}</text>`;
      });
    });
    rows.forEach((r, i) => {
      svg += `<text x="${x(i)}" y="${
        H - 12
      }" text-anchor="middle" font-size="12" fill="#687487">${r.effort}</text>`;
    });
    $("reasoning-chart").innerHTML = svg + "</svg>";
  }
  renderReasoningChart();

  // One clock controls both videos, including seek, model changes, and looping.
  const source = $("source-video"),
    render = $("render-video"),
    videos = [source, render];
  let currentScene = gallery[0],
    currentModel = "astra",
    fraction = 0,
    playing = false,
    raf = 0,
    version = 0,
    operation = 0;
  const pendingLoads = new WeakMap();
  videos.forEach((v) => {
    v.controls = false;
    v.loop = true;
    v.muted = true;
  });
  $("playback-toolbar").hidden = false;
  function setButton() {
    $("play-comparison").innerHTML = playing
      ? '<span aria-hidden="true">Ⅱ</span> Pause together'
      : '<span aria-hidden="true">▶</span> Play together';
  }
  function updateTimeline(value) {
    fraction = Math.max(0, Math.min(1, value));
    $("comparison-time").value = String(Math.round(fraction * 1000));
    $("time-output").textContent = `${Math.round(fraction * 100)}%`;
  }
  function pause() {
    operation++;
    playing = false;
    videos.forEach((v) => v.pause());
    cancelAnimationFrame(raf);
    $("play-comparison").disabled = false;
    $("playback-toolbar").setAttribute("aria-busy", "false");
    setButton();
  }
  function frame() {
    if (!playing) return;
    if (!source.seeking && !render.seeking && source.duration > 0 && render.duration > 0) {
      const f = source.currentTime / source.duration;
      if (Math.abs(render.currentTime - f * render.duration) > 0.14)
        render.currentTime = Math.min(
          f * render.duration,
          render.duration - 0.02,
        );
      updateTimeline(f);
    }
    raf = requestAnimationFrame(frame);
  }
  function updateGalleryInfo() {
    const m = currentScene.models[currentModel];
    $("source-label").textContent =
      `${currentScene.dataset} · ${currentScene.id}`;
    $("render-label").textContent = `${m.name} · ${m.effort}`;
    source.setAttribute("aria-label", `Source video: ${currentScene.title}`);
    render.setAttribute(
      "aria-label",
      `${m.name} reconstruction: ${currentScene.title}`,
    );
    $("example-scores").innerHTML = `<span class="dv-text">DV <b>${score(
      m.dualVqa,
    )}${
      m.dualVqa === null ? "" : "%"
    }</b></span><span class="ls-text">LS <b>${score(m.latentSim)}</b></span>`;
    $("media-note").textContent =
      `Matched relative video times. Each full clip is shown over a 30-second preview; scores are for this scene.${
        m.dualVqa === null
          ? " DV is undefined here: the judge answered no source questions correctly."
          : " Scenes are drawn from the paper."
      }`;
    document
      .querySelectorAll("[data-scene]")
      .forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(b.dataset.scene === currentScene.id),
        ),
      );
  }
  function changeExample() {
    version++;
    pause();
    updateTimeline(0);
    $("play-comparison").disabled = false;
    $("media-error").hidden = true;
    videos.forEach((v, i) => {
      const stem = `assets/media/${currentScene.id}-${
        i === 0 ? "source" : currentModel
      }`;
      v.poster = `${stem}.jpg`;
      v.src = `${stem}.mp4`;
      v.preload = "none";
      v.load();
    });
    updateGalleryInfo();
  }
  function ready(video, token) {
    if (token !== version) return Promise.reject(new Error("changed"));
    if (video.readyState >= 1 && Number.isFinite(video.duration) && video.duration > 0)
      return Promise.resolve();
    const pending = pendingLoads.get(video);
    if (pending?.token === token) return pending.promise;
    const promise = new Promise((resolve, reject) => {
      const done = () => {
        cleanup();
        token === version ? resolve() : reject(new Error("changed"));
      };
      const failed = () => {
        cleanup();
        reject(new Error("media"));
      };
      const cleanup = () => {
        clearTimeout(timeout);
        video.removeEventListener("loadedmetadata", done);
        video.removeEventListener("error", failed);
        if (pendingLoads.get(video)?.token === token) pendingLoads.delete(video);
      };
      const timeout = setTimeout(failed, 15000);
      video.addEventListener("loadedmetadata", done, { once: true });
      video.addEventListener("error", failed, { once: true });
      video.preload = "auto";
      video.load();
    });
    pendingLoads.set(video, { token, promise });
    return promise;
  }
  function seekVideo(video, position, token, request) {
    const time = Math.max(0, Math.min(position * video.duration, video.duration - 0.03));
    return new Promise((resolve, reject) => {
      const done = () => {
        if (token === version && request === operation &&
            (video.seeking || video.readyState < 2 || Math.abs(video.currentTime - time) > 0.1)) return;
        cleanup();
        resolve();
      };
      const failed = () => {
        cleanup();
        reject(new Error("media"));
      };
      const cleanup = () => {
        clearTimeout(timeout);
        video.removeEventListener("seeked", done);
        video.removeEventListener("loadeddata", done);
        video.removeEventListener("error", failed);
      };
      const timeout = setTimeout(failed, 15000);
      video.addEventListener("seeked", done);
      video.addEventListener("loadeddata", done);
      video.addEventListener("error", failed, { once: true });
      try {
        video.currentTime = time;
        done();
      } catch (e) {
        cleanup();
        reject(e);
      }
    });
  }
  async function synchronize(position, shouldPlay) {
    const token = version, request = ++operation;
    const current = () => token === version && request === operation;
    playing = shouldPlay;
    videos.forEach((v) => v.pause());
    cancelAnimationFrame(raf);
    updateTimeline(position);
    setButton();
    $("play-comparison").disabled = true;
    $("playback-toolbar").setAttribute("aria-busy", "true");
    try {
      await Promise.all(videos.map((v) => ready(v, token)));
      if (!current()) return;
      await Promise.all(videos.map((v) => seekVideo(v, position, token, request)));
      if (!current()) return;
      if (playing) await Promise.all(videos.map((v) => v.play()));
      if (!current()) return;
      $("media-error").hidden = true;
    } catch (e) {
      if (current()) {
        pause();
        $("media-error").textContent =
          "Synchronized playback is unavailable. You can use the individual video controls below.";
        $("media-error").hidden = false;
        videos.forEach((v) => (v.controls = true));
      }
    } finally {
      if (current()) {
        $("play-comparison").disabled = false;
        $("playback-toolbar").setAttribute("aria-busy", "false");
        setButton();
        if (playing) raf = requestAnimationFrame(frame);
      }
    }
  }
  $("play-comparison").addEventListener("click", () => {
    if (playing) pause();
    else synchronize(fraction, true);
  });
  $("comparison-time").addEventListener("input", () => {
    synchronize(Number($("comparison-time").value) / 1000, playing);
  });
  document.querySelectorAll("[data-scene]").forEach((b) =>
    b.addEventListener("click", () => {
      currentScene = gallery.find((s) => s.id === b.dataset.scene);
      changeExample();
    }),
  );
  $("example-model").addEventListener("change", () => {
    currentModel = $("example-model").value;
    changeExample();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pause();
  });
  if ("IntersectionObserver" in window)
    new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) pause();
      },
      { threshold: 0 },
    ).observe($("examples"));
  updateTimeline(0);
  updateGalleryInfo();

  $("copy-citation").addEventListener("click", async () => {
    const text = $("citation-text").textContent;
    try {
      if (!navigator.clipboard || !window.isSecureContext)
        throw new Error("clipboard");
      await navigator.clipboard.writeText(text);
      $("copy-citation").textContent = "Copied";
      $("copy-status").textContent = "BibTeX copied to clipboard.";
      setTimeout(() => {
        $("copy-citation").textContent = "Copy BibTeX";
      }, 2000);
    } catch (e) {
      const range = document.createRange();
      range.selectNodeContents($("citation-text"));
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      $("copy-citation").textContent = "Select & copy";
      $("copy-status").textContent =
        "Citation selected. Use your device’s copy command.";
    }
  });
})();
