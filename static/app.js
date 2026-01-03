const form = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const reportEl = document.getElementById("report");
const copyBtn = document.getElementById("copyBtn");
const submitButton = form.querySelector("button[type='submit']");
const fileTitle = document.getElementById("fileTitle");
const heatmapEl = document.getElementById("heatmapChart");
const periodEl = document.getElementById("periodChart");
const amountEl = document.getElementById("amountChart");
const merchantPicker = document.getElementById("merchantPicker");
const merchantList = document.getElementById("merchantList");

let latestReport = "";
let currentRunId = null;
const defaultFileTitle = fileTitle ? fileTitle.textContent : "";

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderMarkdown(md) {
  const lines = md.split(/\r?\n/);
  let html = "";
  let inList = false;

  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trimEnd();
    if (!line) {
      closeList();
      return;
    }

    if (line.startsWith("# ")) {
      closeList();
      html += `<h1>${escapeHtml(line.slice(2))}</h1>`;
      return;
    }

    if (line.startsWith("## ")) {
      closeList();
      html += `<h2>${escapeHtml(line.slice(3))}</h2>`;
      return;
    }

    if (line.startsWith("- ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      let content = escapeHtml(line.slice(2));
      content = content.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      html += `<li>${content}</li>`;
      return;
    }

    closeList();
    let text = escapeHtml(line);
    text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html += `<p>${text}</p>`;
  });

  closeList();
  return html;
}

function setStatus(message, type = "") {
  statusEl.textContent = message;
  statusEl.dataset.type = type;
}

function renderCharts(charts) {
  if (!charts) {
    return;
  }
  if (!window.echarts) {
    setStatus("图表库加载失败，请检查网络。", "error");
    return;
  }

  const existingHeatmap = echarts.getInstanceByDom(heatmapEl);
  if (existingHeatmap) {
    existingHeatmap.dispose();
  }
  const existingPeriod = echarts.getInstanceByDom(periodEl);
  if (existingPeriod) {
    existingPeriod.dispose();
  }
  const existingAmount = echarts.getInstanceByDom(amountEl);
  if (existingAmount) {
    existingAmount.dispose();
  }

  const heatmap = echarts.init(heatmapEl);
  const period = echarts.init(periodEl);
  const amount = echarts.init(amountEl);

  const heatmapData = [];
  charts.heatmap.matrix.forEach((row, yIndex) => {
    row.forEach((value, xIndex) => {
      heatmapData.push([xIndex, yIndex, value]);
    });
  });

  heatmap.setOption({
    title: {
      text: "星期-小时热力图",
      left: "center",
      top: 0,
    },
    tooltip: {
      position: "top",
    },
    grid: {
      left: 60,
      right: 16,
      bottom: 40,
      top: 30,
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: charts.heatmap.hours.map((h) => `${h}:00`),
      splitArea: { show: true },
    },
    yAxis: {
      type: "category",
      data: charts.heatmap.weekdays,
      splitArea: { show: true },
    },
    visualMap: {
      min: 0,
      max: Math.max(...heatmapData.map((d) => d[2]), 1),
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
    },
    series: [
      {
        name: "洗澡次数",
        type: "heatmap",
        data: heatmapData,
        emphasis: {
          itemStyle: {
            shadowBlur: 8,
            shadowColor: "rgba(0, 0, 0, 0.3)",
          },
        },
      },
    ],
  });

  period.setOption({
    title: {
      text: "洗澡时段分布",
      left: "center",
      top: 0,
    },
    tooltip: {
      trigger: "axis",
    },
    grid: {
      left: 40,
      right: 20,
      top: 40,
      bottom: 40,
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: charts.period.labels,
    },
    yAxis: {
      type: "value",
    },
    series: [
      {
        type: "bar",
        data: charts.period.values,
        itemStyle: { color: "#4C72B0" },
      },
    ],
  });

  const edges = charts.amount_distribution.edges;
  const counts = charts.amount_distribution.counts;
  const amountLabels = edges.slice(0, -1).map((edge, idx) => {
    const next = edges[idx + 1];
    return `${edge.toFixed(2)}-${next.toFixed(2)}`;
  });

  amount.setOption({
    title: {
      text: "洗澡开支分布",
      left: "center",
      top: 0,
    },
    tooltip: {
      trigger: "axis",
    },
    grid: {
      left: 40,
      right: 20,
      top: 40,
      bottom: 60,
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: amountLabels,
      axisLabel: {
        rotate: 30,
      },
    },
    yAxis: {
      type: "value",
    },
    series: [
      {
        type: "bar",
        data: counts,
        itemStyle: { color: "#C44E52" },
      },
    ],
  });

  window.addEventListener("resize", () => {
    heatmap.resize();
    period.resize();
    amount.resize();
  });

  requestAnimationFrame(() => {
    heatmap.resize();
    period.resize();
    amount.resize();
  });
}

function resetMerchantSelection() {
  currentRunId = null;
  merchantList.innerHTML = "";
  merchantPicker.classList.add("hidden");
}

function updateFileTitle(name) {
  if (!fileTitle) {
    return;
  }
  fileTitle.textContent = name ? `上传成功：${name}` : defaultFileTitle;
}

function renderMerchantSelection(merchants, defaults) {
  merchantList.innerHTML = "";
  const defaultSet = new Set(defaults || []);

  merchants.forEach((name) => {
    const item = document.createElement("label");
    item.className = "merchant-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "merchant";
    checkbox.value = name;
    checkbox.checked = defaultSet.has(name);
    const text = document.createElement("span");
    text.textContent = name;
    item.appendChild(checkbox);
    item.appendChild(text);
    merchantList.appendChild(item);
  });

  merchantPicker.classList.remove("hidden");
}

function getSelectedMerchants() {
  return Array.from(document.querySelectorAll("input[name='merchant']:checked")).map(
    (input) => input.value
  );
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) {
    setStatus("请先选择 Excel 文件。", "error");
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "处理中...";

  try {
    if (!currentRunId) {
      const formData = new FormData();
      formData.append("file", file);
      setStatus("上传成功，正在识别宿舍名单...", "loading");

      const response = await fetch("/prepare", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || "解析失败，请检查文件格式。");
      }

      const data = await response.json();
      currentRunId = data.run_id;
      renderMerchantSelection(data.merchants || [], data.defaults || []);
      setStatus("请选择宿舍后再次点击生成报告。", "success");
      return;
    }

    const selected = getSelectedMerchants();
    if (!selected.length) {
      setStatus("请至少选择一个宿舍名称。", "error");
      return;
    }

    setStatus("正在生成报告，请稍候...", "loading");
    const response = await fetch("/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        run_id: currentRunId,
        merchants: selected,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "分析失败，请检查文件格式。");
    }

    const data = await response.json();
    latestReport = data.report_md;
    reportEl.innerHTML = renderMarkdown(data.report_md);
    resultsEl.classList.remove("hidden");
    renderCharts(data.charts || null);

    setStatus("报告生成完成。", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "生成报告";
  }
});

copyBtn.addEventListener("click", async () => {
  if (!latestReport) {
    setStatus("暂无可复制的报告。", "error");
    return;
  }

  try {
    await navigator.clipboard.writeText(latestReport);
    setStatus("Markdown 已复制到剪贴板。", "success");
  } catch (error) {
    setStatus("复制失败，请手动复制报告内容。", "error");
  }
});

const dropZone = document.querySelector(".file-drop");

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
  });
});

dropZone.addEventListener("drop", (event) => {
  if (event.dataTransfer.files.length) {
    fileInput.files = event.dataTransfer.files;
    resetMerchantSelection();
    resultsEl.classList.add("hidden");
    updateFileTitle(event.dataTransfer.files[0].name);
    setStatus(`已选择文件：${event.dataTransfer.files[0].name}`, "success");
  }
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) {
    resetMerchantSelection();
    resultsEl.classList.add("hidden");
    updateFileTitle(fileInput.files[0].name);
    setStatus(`已选择文件：${fileInput.files[0].name}`, "success");
  }
});
