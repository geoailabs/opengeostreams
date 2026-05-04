const http = require("http");
const fs = require("fs");
const path = require("path");
const { buildDashboardData } = require("./build-dashboard-data");

const port = 4173;
const root = __dirname;
const datasetsDir = path.join(root, "Datasets");
const dashboardDataFile = path.join(root, "dashboard-data.js");

let lastBuildStamp = "";
let buildInProgress = false;
let pendingBuild = false;

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
};

async function handleWeatherHistory(req, res) {
  try {
    const requestUrl = new URL(req.url, `http://${req.headers.host || "127.0.0.1"}`);
    const latitude = requestUrl.searchParams.get("latitude");
    const longitude = requestUrl.searchParams.get("longitude");
    const startDate = requestUrl.searchParams.get("start_date");
    const endDate = requestUrl.searchParams.get("end_date");

    if (!latitude || !longitude || !startDate || !endDate) {
      res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: "Missing latitude, longitude, start_date, or end_date." }));
      return;
    }

    const upstreamUrl = new URL("https://archive-api.open-meteo.com/v1/archive");
    upstreamUrl.searchParams.set("latitude", latitude);
    upstreamUrl.searchParams.set("longitude", longitude);
    upstreamUrl.searchParams.set("start_date", startDate);
    upstreamUrl.searchParams.set("end_date", endDate);
    upstreamUrl.searchParams.set("daily", "precipitation_sum,weather_code");
    upstreamUrl.searchParams.set("timezone", "auto");

    const upstreamResponse = await fetch(upstreamUrl, {
      headers: {
        "User-Agent": "N-choe-dashboard/1.0",
      },
    });

    const contentType = upstreamResponse.headers.get("content-type") || "application/json; charset=utf-8";
    const payload = await upstreamResponse.text();

    res.writeHead(upstreamResponse.status, {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    });
    res.end(payload);
  } catch (error) {
    res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({
      error: "Weather proxy request failed.",
      detail: error && error.message ? error.message : String(error),
    }));
  }
}

function collectDatasetState() {
  if (!fs.existsSync(datasetsDir)) {
    return "";
  }

  const files = fs
    .readdirSync(datasetsDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".csv"))
    .map((entry) => {
      const filePath = path.join(datasetsDir, entry.name);
      const stats = fs.statSync(filePath);
      return `${entry.name}:${stats.size}:${stats.mtimeMs}`;
    })
    .sort();

  return files.join("|");
}

function runBuild(reason) {
  if (buildInProgress) {
    pendingBuild = true;
    return false;
  }

  buildInProgress = true;
  console.log(`Refreshing dashboard data (${reason})...`);
  try {
    const result = buildDashboardData(root);
    console.log(`Created dashboard-data.js from ${result.fileCount} dataset file(s) with ${result.recordCount} records.`);
  } catch (error) {
    buildInProgress = false;
    console.error("Dashboard data refresh failed.");
    console.error(error && error.stack ? error.stack : String(error));
    return false;
  }

  buildInProgress = false;

  lastBuildStamp = collectDatasetState();

  if (pendingBuild) {
    pendingBuild = false;
    runBuild("queued dataset change");
  }

  return true;
}

function ensureDashboardData(reason) {
  const currentStamp = collectDatasetState();
  const needsBuild = !fs.existsSync(dashboardDataFile) || currentStamp !== lastBuildStamp;

  if (needsBuild) {
    runBuild(reason);
  }
}

function watchDatasets() {
  if (!fs.existsSync(datasetsDir)) {
    console.warn("Datasets folder not found. Auto-refresh watcher is disabled.");
    return;
  }

  fs.watch(datasetsDir, { persistent: true }, (_eventType, fileName) => {
    if (fileName && !fileName.toLowerCase().endsWith(".csv")) {
      return;
    }

    pendingBuild = true;
    setTimeout(() => {
      if (!pendingBuild) {
        return;
      }

      pendingBuild = false;
      ensureDashboardData(`dataset change${fileName ? `: ${fileName}` : ""}`);
    }, 250);
  });
}

const server = http.createServer(async (req, res) => {
  ensureDashboardData(`request for ${req.url || "/"}`);

  if ((req.url || "").startsWith("/weather-history")) {
    await handleWeatherHistory(req, res);
    return;
  }

  const urlPath = req.url === "/" ? "/index.html" : req.url;
  const filePath = path.join(root, decodeURIComponent(urlPath.split("?")[0]));

  if (!filePath.startsWith(root)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(err.code === "ENOENT" ? 404 : 500, {
        "Content-Type": "text/plain; charset=utf-8",
      });
      res.end(err.code === "ENOENT" ? "Not found" : "Server error");
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      "Content-Type": mimeTypes[ext] || "application/octet-stream",
      "Cache-Control": "no-store",
    });
    res.end(content);
  });
});

ensureDashboardData("server startup");
watchDatasets();

server.listen(port, "127.0.0.1", () => {
  console.log(`N-choe dashboard running at http://127.0.0.1:${port}`);
  console.log("Dataset auto-refresh is enabled. New CSVs in Datasets will rebuild dashboard-data.js automatically.");
});
