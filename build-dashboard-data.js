const fs = require("fs");
const path = require("path");

function fixText(value) {
  if (value == null) {
    return "";
  }

  return String(value)
    .trim()
    .replace(/\u00c2/g, "")
    .replace(/\u2013/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

function getMonthIndex(month) {
  const monthLookup = new Map([
    ["Jan", 1], ["January", 1],
    ["Feb", 2], ["February", 2],
    ["Mar", 3], ["March", 3],
    ["Apr", 4], ["April", 4],
    ["May", 5],
    ["Jun", 6], ["June", 6],
    ["Jul", 7], ["July", 7],
    ["Aug", 8], ["August", 8],
    ["Sep", 9], ["Sept", 9], ["September", 9],
    ["Oct", 10], ["October", 10],
    ["Nov", 11], ["November", 11],
    ["Dec", 12], ["December", 12],
  ]);

  return monthLookup.get(fixText(month)) || 0;
}

function convertToNumber(rawValue) {
  const clean = fixText(rawValue).replace(/,/g, "");
  if (!clean) {
    return null;
  }

  const exponentMatch = clean.match(/^([0-9]+(?:\.[0-9]+)?)x10\^([0-9]+)$/);
  if (exponentMatch) {
    return Number(exponentMatch[1]) * (10 ** Number(exponentMatch[2]));
  }

  const parsed = Number(clean);
  return Number.isFinite(parsed) ? parsed : null;
}

function convertToCoordinate(value) {
  const clean = fixText(value).replace(/,/g, "");
  if (!clean) {
    return null;
  }

  const parsed = Number(clean);
  return Number.isFinite(parsed) ? Number(parsed.toFixed(6)) : null;
}

function getDisplayLocation(rawLocation, fileName) {
  const known = {
    "cpcb_2020_station2047.csv": "CPCB Station Code 2047",
    "combined_cpcb_3BRD_2018_2020.csv": "3BRD",
    "combined_cpcb_Diggian_2018_2020.csv": "Diggian",
  };

  const location = fixText(rawLocation);
  if (location) {
    return location.replace(/parK/g, "Park");
  }

  if (known[fileName]) {
    return known[fileName];
  }

  return fixText(path.basename(fileName, path.extname(fileName)).replace(/[_-]+/g, " "));
}

function getLocationGroup(displayLocation) {
  const clean = fixText(displayLocation).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

  if (/^n choe leisure valley park chd$/.test(clean)) return "N-CHOE (Leisure Valley Park, Chandigarh)";
  if (/^attawa choa leisure valley garden mohali$/.test(clean)) return "Attawa Choa (Leisure Valley Garden, Mohali)";
  if (/^attawa choa sec 67 mohali$/.test(clean)) return "Attawa Choa Sec. 67 (Mohali)";
  if (/^3brd$/.test(clean)) return "3BRD";
  if (/^diggian$/.test(clean)) return "Diggian";
  if (/station code 2047/.test(clean)) return "CPCB Station Code 2047";
  if (/(^| )ncc01( |$)|sector 36/.test(clean)) return "NCC01 - Sector 36";
  if (/(^| )ncc02( |$)|exit of chandigarh sector 53/.test(clean)) return "NCC02 - Exit of Chandigarh Sector 53";
  if (/(^| )ncm03( |$)|^sector 83$/.test(clean)) return "NCM03 - Sector 83";
  if (/(^| )ncm04( |$)|45mld stp chilla village/.test(clean)) return "NCM04 - 45MLD STP Chilla Village";
  if (/(^| )ncp05( |$)|river ghaggar d s of n choe/.test(clean)) return "NCP05 - River Ghaggar D/S of N-choe";
  if (/(^| )ncp06( |$)|before confluence with ghaggar/.test(clean)) return "NCP06 - N-choe before confluence with Ghaggar";
  if (/(^| )ncp07( |$)|river ghaggar u s n choe/.test(clean)) return "NCP07 - River Ghaggar U/S N-choe";
  return displayLocation;
}

function normalizeCoordinates(locationGroup, latitude, longitude) {
  if (locationGroup === "NCP06 - N-choe before confluence with Ghaggar" && latitude === 30.031831) {
    return {
      latitude: 30.315357,
      longitude: 76.628347,
      inferred: false,
      originalLatitude: latitude,
      originalLongitude: longitude,
    };
  }

  if (locationGroup === "NCP07 - River Ghaggar U/S N-choe" && latitude === 30.031831) {
    return {
      latitude: 30.305502,
      longitude: 76.635388,
      inferred: false,
      originalLatitude: latitude,
      originalLongitude: longitude,
    };
  }

  if (locationGroup === "NCP05 - River Ghaggar D/S of N-choe" && latitude === 30.315357) {
    return {
      latitude: 30.305502,
      longitude: 76.62738,
      inferred: false,
      originalLatitude: latitude,
      originalLongitude: longitude,
    };
  }

  return {
    latitude,
    longitude,
    inferred: false,
    originalLatitude: latitude,
    originalLongitude: longitude,
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"') {
      if (inQuotes && next === '"') {
        field += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === "," && !inQuotes) {
      row.push(field);
      field = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") {
        i += 1;
      }
      row.push(field);
      field = "";
      rows.push(row);
      row = [];
      continue;
    }

    field += char;
  }

  if (field.length || row.length) {
    row.push(field);
    rows.push(row);
  }

  if (!rows.length) {
    return [];
  }

  const headers = rows[0].map((header) => fixText(header));
  return rows
    .slice(1)
    .filter((values) => values.some((value) => fixText(value)))
    .map((values) => {
      const record = {};
      headers.forEach((header, index) => {
        record[header] = values[index] ?? "";
      });
      return record;
    });
}

function buildDashboardData(rootDir = __dirname) {
  const datasetDir = path.join(rootDir, "Datasets");
  if (!fs.existsSync(datasetDir)) {
    throw new Error(`Datasets folder not found at ${datasetDir}`);
  }

  const csvFiles = fs
    .readdirSync(datasetDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".csv"))
    .map((entry) => entry.name)
    .sort((a, b) => a.localeCompare(b));

  const records = [];
  const locations = new Map();

  for (const fileName of csvFiles) {
    const fullPath = path.join(datasetDir, fileName);
    const rows = parseCsv(fs.readFileSync(fullPath, "utf8"));

    for (const row of rows) {
      let year = Number.parseInt(fixText(row.Year), 10);
      if (!Number.isFinite(year)) {
        const match = fileName.match(/20\d{2}/);
        year = match ? Number(match[0]) : 0;
      }

      const month = fixText(row.Month);
      const monthIndex = getMonthIndex(month);
      const displayLocation = getDisplayLocation(row.Location, fileName);
      const locationGroup = getLocationGroup(displayLocation);
      const parameter = fixText(row.Parameter);
      const unit = fixText(row.Unit);
      const source = fixText(row["Data Source"]);
      const rawValue = fixText(row.Value);
      const numericValue = convertToNumber(rawValue);
      const parsedLatitude = convertToCoordinate(row.Latitude);
      const parsedLongitude = convertToCoordinate(row.Longitude);
      const normalizedCoordinates = normalizeCoordinates(locationGroup, parsedLatitude, parsedLongitude);
      const latitude = normalizedCoordinates.latitude;
      const longitude = normalizedCoordinates.longitude;
      const coordinateInferred = normalizedCoordinates.inferred;
      const hasCoordinates = latitude != null && longitude != null;
      const dateLabel = monthIndex > 0 && year > 0 ? `${month} ${year}` : year > 0 ? String(year) : "Unknown date";

      records.push({
        fileName,
        location: displayLocation,
        locationGroup,
        parameter,
        unit,
        month,
        monthIndex,
        year,
        dateLabel,
        sortKey: year * 100 + monthIndex,
        rawValue,
        numericValue,
        source,
        latitude,
        longitude,
        originalLatitude: normalizedCoordinates.originalLatitude,
        originalLongitude: normalizedCoordinates.originalLongitude,
        coordinateInferred,
        hasCoordinates,
      });

      if (!locations.has(locationGroup)) {
        locations.set(locationGroup, {
          id: locationGroup.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
          name: locationGroup,
          latitude,
          longitude,
          originalLatitude: normalizedCoordinates.originalLatitude,
          originalLongitude: normalizedCoordinates.originalLongitude,
          coordinateInferred,
          hasCoordinates,
          sources: [fileName],
        });
      } else {
        const existing = locations.get(locationGroup);
        if (!existing.hasCoordinates && hasCoordinates) {
          existing.latitude = latitude;
          existing.longitude = longitude;
          existing.hasCoordinates = true;
        }
        if (!existing.coordinateInferred && coordinateInferred) {
          existing.coordinateInferred = true;
          existing.originalLatitude = normalizedCoordinates.originalLatitude;
          existing.originalLongitude = normalizedCoordinates.originalLongitude;
        }
        if (!existing.sources.includes(fileName)) {
          existing.sources.push(fileName);
        }
      }
    }
  }

  records.sort((a, b) =>
    a.locationGroup.localeCompare(b.locationGroup) ||
    a.parameter.localeCompare(b.parameter) ||
    a.sortKey - b.sortKey ||
    a.fileName.localeCompare(b.fileName)
  );

  const locationList = Array.from(locations.values()).sort((a, b) => a.name.localeCompare(b.name));

  const data = {
    generatedAt: new Date().toISOString().slice(0, 19),
    summary: {
      recordCount: records.length,
      mappedLocationCount: locationList.filter((location) => location.hasCoordinates).length,
      unmappedLocationCount: locationList.filter((location) => !location.hasCoordinates).length,
    },
    locations: locationList,
    records,
  };

  const outputPath = path.join(rootDir, "dashboard-data.js");
  fs.writeFileSync(outputPath, `window.NCHOE_DASHBOARD_DATA = ${JSON.stringify(data, null, 4)};`, "utf8");

  return {
    fileCount: csvFiles.length,
    recordCount: records.length,
    outputPath,
  };
}

if (require.main === module) {
  const result = buildDashboardData();
  console.log(`Created dashboard-data.js from ${result.fileCount} dataset file(s) with ${result.recordCount} records.`);
}

module.exports = {
  buildDashboardData,
};
