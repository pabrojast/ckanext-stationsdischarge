/**
 * Interactive Multi-Key Telemetry Dashboard for Hydrometric Stations
 *
 * Requires: Chart.js 4.x, chartjs-adapter-date-fns, chartjs-plugin-zoom, Hammer.js
 * Expects a global DASH_CONFIG object set by the template:
 *   { telemetryUrl, telemetryKeys: [{telemetry_key, label, unit, variable_type}], i18n }
 */
(function () {
  'use strict';

  var CFG = window.DASH_CONFIG || {};
  var TELEMETRY_URL = CFG.telemetryUrl || '';
  var CONFIGURED_KEYS = CFG.telemetryKeys || [];
  var I18N = CFG.i18n || {};

  function t(key, fallback) { return I18N[key] || fallback || key; }

  var COLORS = [
    '#0b6efd', '#dc3545', '#198754', '#fd7e14', '#6f42c1',
    '#0dcaf0', '#e91e63', '#795548', '#607d8b', '#ff9800',
  ];

  var mainChart = null;
  var currentData = {};
  var activeHours = 24;
  var chartType = 'line';
  var autoRefreshCountdown = null;
  var autoRefreshSeconds = 0;

  var PRESETS = {
    1:    { limit: 500,  agg: null,  interval: null },
    6:    { limit: 1000, agg: null,  interval: null },
    24:   { limit: 2000, agg: null,  interval: null },
    168:  { limit: 5000, agg: null,  interval: null },
    720:  { limit: 744,  agg: 'AVG', interval: 3600000 },
    2160: { limit: 720,  agg: 'AVG', interval: 10800000 },
    4380: { limit: 180,  agg: 'AVG', interval: 86400000 },
    8760: { limit: 366,  agg: 'AVG', interval: 86400000 },
  };

  var AGG_LABELS = {
    3600000:  t('hourly_avg', 'hourly avg'),
    10800000: t('3h_avg', '3-hour avg'),
    86400000: t('daily_avg', 'daily avg'),
  };

  var $ = function (id) { return document.getElementById(id); };

  function toLocalISO(d) {
    var off = d.getTimezoneOffset();
    return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
  }

  function toUTC(ts) {
    var d = new Date(ts);
    return d.getUTCFullYear() + '-' +
      p2(d.getUTCMonth() + 1) + '-' + p2(d.getUTCDate()) + ' ' +
      p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()) + ':' + p2(d.getUTCSeconds());
  }

  function p2(n) { return String(n).padStart(2, '0'); }

  function fmtNum(v, dec) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return parseFloat(v).toFixed(dec);
  }

  function hexToRGBA(hex, alpha) {
    hex = hex.replace('#', '');
    if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    var r = parseInt(hex.substring(0, 2), 16);
    var g = parseInt(hex.substring(2, 4), 16);
    var b = parseInt(hex.substring(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  function getSelectedKeys() {
    var checks = document.querySelectorAll('.dash-key-check:checked');
    if (checks.length === 0) {
      return CONFIGURED_KEYS.map(function (k) {
        return { key: k.telemetry_key, label: k.label || k.telemetry_key, unit: k.unit || '' };
      });
    }
    var keys = [];
    checks.forEach(function (cb) {
      keys.push({
        key: cb.value,
        label: cb.getAttribute('data-label') || cb.value,
        unit: cb.getAttribute('data-unit') || '',
      });
    });
    return keys;
  }

  function getKeyColor(idx) {
    return COLORS[idx % COLORS.length];
  }

  function getKeyMeta(keyName) {
    for (var i = 0; i < CONFIGURED_KEYS.length; i++) {
      if (CONFIGURED_KEYS[i].telemetry_key === keyName) return CONFIGURED_KEYS[i];
    }
    return { telemetry_key: keyName, label: keyName, unit: '' };
  }

  /* ── Time range ──────────────────────────────────── */
  function setPreset(hours) {
    activeHours = hours;
    document.querySelectorAll('.dash-presets .btn').forEach(function (b) { b.classList.remove('active'); });
    var target = document.querySelector('[data-hours="' + hours + '"]');
    if (target) target.classList.add('active');

    var now = new Date();
    var start = new Date(now.getTime() - hours * 3600 * 1000);
    $('dashStart').value = toLocalISO(start);
    $('dashEnd').value = toLocalISO(now);
    fetchData();
  }

  function initTimeControls() {
    document.querySelectorAll('.dash-presets .btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setPreset(parseInt(this.getAttribute('data-hours')));
      });
    });

    $('dashApply').addEventListener('click', function () {
      document.querySelectorAll('.dash-presets .btn').forEach(function (b) { b.classList.remove('active'); });
      activeHours = 0;
      fetchData();
    });
  }

  /* ── Key selector ────────────────────────────────── */
  function initKeySelector() {
    document.querySelectorAll('.dash-key-check').forEach(function (cb) {
      cb.addEventListener('change', function () {
        if (Object.keys(currentData).length) {
          renderMainChart();
          renderTable();
          buildTableHeader();
        }
      });
    });
  }

  /* ── Data fetching ───────────────────────────────── */
  function fetchData() {
    var startVal = $('dashStart').value;
    var endVal = $('dashEnd').value;
    if (!startVal || !endVal) return;

    var startTs = new Date(startVal).getTime();
    var endTs = new Date(endVal).getTime();

    var preset = PRESETS[activeHours];
    var limit = (preset && preset.limit) || 2000;
    var url = TELEMETRY_URL + '?start_ts=' + startTs + '&end_ts=' + endTs + '&limit=' + limit;

    if (preset && preset.agg) {
      url += '&agg=' + preset.agg + '&interval=' + preset.interval;
    }

    var aggBadge = $('dashAggBadge');
    if (preset && preset.agg && AGG_LABELS[preset.interval]) {
      aggBadge.textContent = '⚡ ' + t('showing', 'Showing') + ' ' + AGG_LABELS[preset.interval];
      aggBadge.style.display = 'inline-block';
    } else {
      aggBadge.style.display = 'none';
    }

    showLoading(true);
    hideError();
    hideNoData();

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        showLoading(false);
        if (data.error) {
          showError(typeof data.error === 'string' ? data.error : JSON.stringify(data.error));
          return;
        }
        processData(data);
      })
      .catch(function (err) {
        showLoading(false);
        showError('Error: ' + err.message);
      });
  }

  function showLoading(show) {
    var el = $('dashLoading');
    if (el) el.style.display = show ? 'block' : 'none';
  }

  function showError(msg) {
    var el = $('dashError');
    if (el) { el.style.display = 'block'; el.textContent = msg; }
  }

  function hideError() {
    var el = $('dashError');
    if (el) el.style.display = 'none';
  }

  function hideNoData() {
    var el = $('dashNoData');
    if (el) el.style.display = 'none';
  }

  /* ── Data processing ─────────────────────────────── */
  function processData(data) {
    // data.telemetry is { keyName: [ {ts, value}, ... ], ... }
    var telemetry = data.telemetry || data;
    currentData = {};
    var totalPoints = 0;
    var latestTs = 0;

    for (var keyName in telemetry) {
      if (!telemetry.hasOwnProperty(keyName)) continue;
      var raw = telemetry[keyName];
      if (!Array.isArray(raw)) continue;

      var points = raw.map(function (p) {
        return { ts: p.ts, value: parseFloat(p.value) };
      }).sort(function (a, b) { return a.ts - b.ts; });

      currentData[keyName] = points;
      totalPoints += points.length;
      if (points.length && points[points.length - 1].ts > latestTs) {
        latestTs = points[points.length - 1].ts;
      }
    }

    if (totalPoints === 0) {
      $('dashNoData').style.display = 'block';
      updateSummary(0, null);
      buildTableHeader();
      renderTable();
      if (mainChart) { mainChart.destroy(); mainChart = null; }
      return;
    }

    updateSummary(totalPoints, latestTs);
    buildTableHeader();
    renderMainChart();
    renderTable();
  }

  /* ── Summary cards ───────────────────────────────── */
  function updateSummary(count, latestTs) {
    animateValue('dashSummCount', count ? String(count) : '—');
    animateValue('dashSummTime', latestTs ? toUTC(latestTs) : '—');
  }

  function animateValue(id, newVal) {
    var el = $(id);
    if (!el) return;
    el.classList.add('updating');
    el.textContent = newVal;
    setTimeout(function () { el.classList.remove('updating'); }, 600);
  }

  /* ── Main chart (multi-series) ───────────────────── */
  function renderMainChart() {
    var selectedKeys = getSelectedKeys();
    if (mainChart) mainChart.destroy();

    var ctx = $('dashMainCanvas').getContext('2d');
    var isBar = (chartType === 'bar');
    var type = isBar ? 'bar' : 'line';
    var isArea = (chartType === 'area');

    var datasets = [];
    var scales = {
      x: {
        type: 'time',
        time: { tooltipFormat: 'yyyy-MM-dd HH:mm' },
        title: { display: true, text: t('time_utc', 'Time (UTC)'), font: { size: 12 } },
      }
    };

    selectedKeys.forEach(function (keyInfo, idx) {
      var points = currentData[keyInfo.key] || [];
      var color = getKeyColor(idx);
      var axisId = 'y' + idx;

      var labelText = keyInfo.label;
      if (keyInfo.unit) labelText += ' (' + keyInfo.unit + ')';

      datasets.push({
        label: labelText,
        data: points.map(function (p) { return { x: new Date(p.ts), y: p.value }; }),
        borderColor: color,
        backgroundColor: isArea || (!isBar) ? hexToRGBA(color, 0.1) : hexToRGBA(color, 0.6),
        fill: isArea,
        tension: isBar ? 0 : 0.3,
        pointRadius: 0,
        borderWidth: 2,
        yAxisID: axisId,
      });

      scales[axisId] = {
        type: 'linear',
        position: idx === 0 ? 'left' : 'right',
        title: { display: true, text: labelText, font: { size: 12 }, color: color },
        grid: { drawOnChartArea: idx === 0 },
        ticks: { color: color },
      };
    });

    var resetBtn = $('dashResetZoom');

    mainChart = new Chart(ctx, {
      type: type,
      data: { datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          tooltip: {
            callbacks: {
              title: function (items) {
                return items.length ? toUTC(items[0].parsed.x) : '';
              },
            },
          },
          legend: { position: 'top', labels: { usePointStyle: true, padding: 16 } },
          zoom: {
            pan: {
              enabled: true, mode: 'x',
              onPanComplete: function () { if (resetBtn) resetBtn.style.display = 'block'; }
            },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              mode: 'x',
              onZoomComplete: function () { if (resetBtn) resetBtn.style.display = 'block'; },
            },
          },
        },
        scales: scales,
        animation: { duration: 400 },
      },
    });

    if (resetBtn) {
      resetBtn.style.display = 'none';
      resetBtn.onclick = function () {
        mainChart.resetZoom();
        resetBtn.style.display = 'none';
      };
    }
  }

  /* ── Data table ──────────────────────────────────── */
  function buildTableHeader() {
    var thead = $('dashTableHead');
    if (!thead) return;

    var selectedKeys = getSelectedKeys();
    var html = '<tr><th>' + t('time_utc', 'Timestamp (UTC)') + '</th>';
    selectedKeys.forEach(function (keyInfo) {
      var h = keyInfo.label;
      if (keyInfo.unit) h += ' (' + keyInfo.unit + ')';
      html += '<th class="num">' + h + '</th>';
    });
    html += '</tr>';
    thead.innerHTML = html;
  }

  function renderTable() {
    var tbody = $('dashTableBody');
    if (!tbody) return;

    var selectedKeys = getSelectedKeys();
    var colCount = 1 + selectedKeys.length;

    // Merge all timestamps
    var tsSet = {};
    selectedKeys.forEach(function (keyInfo) {
      var points = currentData[keyInfo.key] || [];
      points.forEach(function (p) { tsSet[p.ts] = true; });
    });

    var timestamps = Object.keys(tsSet).map(Number).sort(function (a, b) { return b - a; });

    if (timestamps.length === 0) {
      tbody.innerHTML = '<tr><td colspan="' + colCount + '" style="text-align:center;color:#888;padding:20px;">' +
        t('no_data', 'No data') + '</td></tr>';
      updateTableCount(0);
      return;
    }

    // Build lookup maps for quick access
    var lookups = {};
    selectedKeys.forEach(function (keyInfo) {
      var map = {};
      (currentData[keyInfo.key] || []).forEach(function (p) { map[p.ts] = p.value; });
      lookups[keyInfo.key] = map;
    });

    var html = '';
    var limit = Math.min(timestamps.length, 1000);
    for (var i = 0; i < limit; i++) {
      var ts = timestamps[i];
      html += '<tr><td>' + toUTC(ts) + '</td>';
      selectedKeys.forEach(function (keyInfo) {
        var val = lookups[keyInfo.key][ts];
        html += '<td class="num">' + fmtNum(val, 3) + '</td>';
      });
      html += '</tr>';
    }
    tbody.innerHTML = html;
    updateTableCount(limit);
  }

  function updateTableCount(n) {
    var el = $('dashTableCount');
    if (el) el.textContent = n + ' ' + t('records', 'records');
  }

  /* ── Table search ────────────────────────────────── */
  function initTableSearch() {
    var input = $('dashTableSearch');
    if (!input) return;
    input.addEventListener('input', function () {
      var q = this.value.toLowerCase();
      var rows = document.querySelectorAll('#dashTableBody tr');
      var visible = 0;
      rows.forEach(function (row) {
        var text = row.textContent.toLowerCase();
        var show = text.indexOf(q) !== -1;
        row.style.display = show ? '' : 'none';
        if (show) visible++;
      });
      updateTableCount(visible);
    });
  }

  /* ── Chart type switching ────────────────────────── */
  function initChartTypes() {
    document.querySelectorAll('.dash-chart-types .type-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('.dash-chart-types .type-btn').forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');
        chartType = this.getAttribute('data-type');
        if (Object.keys(currentData).length) renderMainChart();
      });
    });
  }

  /* ── Fullscreen ──────────────────────────────────── */
  function initFullscreen() {
    var btn = $('dashFullscreen');
    var wrap = $('dashMainWrap');
    if (!btn || !wrap) return;

    btn.addEventListener('click', function () {
      if (wrap.requestFullscreen) wrap.requestFullscreen();
      else if (wrap.webkitRequestFullscreen) wrap.webkitRequestFullscreen();
    });

    document.addEventListener('fullscreenchange', function () {
      if (mainChart) setTimeout(function () { mainChart.resize(); }, 100);
    });
  }

  /* ── Auto-refresh ────────────────────────────────── */
  function initAutoRefresh() {
    var toggle = $('dashAutoRefresh');
    var intervalSel = $('dashAutoInterval');
    var pulse = $('dashPulse');
    var countdownEl = $('dashCountdown');
    if (!toggle) return;

    toggle.addEventListener('change', function () {
      if (this.checked) startAutoRefresh();
      else stopAutoRefresh();
    });

    if (intervalSel) {
      intervalSel.addEventListener('change', function () {
        if (toggle.checked) { stopAutoRefresh(); startAutoRefresh(); }
      });
    }

    function startAutoRefresh() {
      var interval = parseInt(intervalSel ? intervalSel.value : 60);
      autoRefreshSeconds = interval;
      if (pulse) pulse.classList.add('active');
      if (countdownEl) countdownEl.style.display = 'inline';
      updateCountdown();

      autoRefreshCountdown = setInterval(function () {
        autoRefreshSeconds--;
        if (autoRefreshSeconds <= 0) {
          autoRefreshSeconds = parseInt(intervalSel ? intervalSel.value : 60);
          if (activeHours > 0) setPreset(activeHours);
          else fetchData();
        }
        updateCountdown();
      }, 1000);
    }

    function stopAutoRefresh() {
      if (autoRefreshCountdown) clearInterval(autoRefreshCountdown);
      autoRefreshCountdown = null;
      if (pulse) pulse.classList.remove('active');
      if (countdownEl) countdownEl.style.display = 'none';
    }

    function updateCountdown() {
      if (countdownEl) countdownEl.textContent = autoRefreshSeconds + 's';
    }
  }

  /* ── Init ────────────────────────────────────────── */
  function init() {
    initTimeControls();
    initKeySelector();
    initChartTypes();
    initFullscreen();
    initAutoRefresh();
    initTableSearch();
    setPreset(24);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
