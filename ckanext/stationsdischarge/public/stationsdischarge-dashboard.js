/**
 * Interactive Dashboard for Hydrometric Stations
 *
 * Requires: Chart.js 4.x, chartjs-adapter-date-fns, chartjs-plugin-zoom, Hammer.js
 * Expects a global DASH_CONFIG object set by the template.
 */
(function () {
  'use strict';

  /* ── Config from template ─────────────────────────── */
  var CFG = window.DASH_CONFIG || {};
  var DISCHARGE_URL = CFG.dischargeUrl || '';
  var CSV_URL = CFG.csvUrl || '';
  var UNIT_H = CFG.unitLevel || 'm';
  var UNIT_Q = CFG.unitFlow || 'm³/s';
  var CURVE_TYPE = CFG.curveType || '';
  var CURVE_PARAMS = CFG.curveParams || null;
  var I18N = CFG.i18n || {};

  function t(key, fallback) { return I18N[key] || fallback || key; }

  /* ── State ─────────────────────────────────────────── */
  var mainChart = null;
  var hqChart = null;
  var currentPoints = [];
  var activeHours = 24;
  var chartType = 'line';
  var autoRefreshTimer = null;
  var autoRefreshCountdown = null;
  var autoRefreshSeconds = 0;

  var chartOpts = {
    lineWidth: 2,
    tension: 0.3,
    showFill: true,
    showPoints: false,
    colorH: '#0b6efd',
    colorQ: '#dc3545',
  };

  /* ── Aggregation presets ───────────────────────────── */
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

  /* ── DOM refs ──────────────────────────────────────── */
  var $ = function (id) { return document.getElementById(id); };

  /* ── Utility ───────────────────────────────────────── */
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

  /* ── Statistics ────────────────────────────────────── */
  function calcStats(arr) {
    if (!arr.length) return { min: null, max: null, avg: null, std: null };
    var nums = arr.filter(function (v) { return v !== null && v !== undefined && !isNaN(v); });
    if (!nums.length) return { min: null, max: null, avg: null, std: null };
    var min = Math.min.apply(null, nums);
    var max = Math.max.apply(null, nums);
    var sum = nums.reduce(function (a, b) { return a + b; }, 0);
    var avg = sum / nums.length;
    var variance = nums.reduce(function (a, b) { return a + Math.pow(b - avg, 2); }, 0) / nums.length;
    return { min: min, max: max, avg: avg, std: Math.sqrt(variance) };
  }

  /* ── Rating curve computation (client-side for H-Q chart) ── */
  function computeQ(h, type, params) {
    if (h === null || h === undefined || !type || !params) return null;
    h = parseFloat(h);
    if (isNaN(h)) return null;

    if (type === 'power') {
      var a = params.a || 0, b = params.b || 0, h0 = params.h0 || 0;
      var hEff = h - h0;
      if (hEff <= 0) return 0;
      return a * Math.pow(hEff, b);
    }

    if (type === 'linear_segments') {
      var segs = params.segments || [];
      for (var i = 0; i < segs.length; i++) {
        var s = segs[i];
        if (h >= (s.h_min || 0) && h <= (s.h_max || Infinity)) {
          return (s.slope || 0) * h + (s.intercept || 0);
        }
      }
      if (segs.length) {
        var last = segs[segs.length - 1];
        return (last.slope || 0) * h + (last.intercept || 0);
      }
      return null;
    }

    if (type === 'table_interpolation') {
      var tbl = params.table || [];
      if (tbl.length < 2) return null;
      if (h <= tbl[0].h) return tbl[0].q;
      if (h >= tbl[tbl.length - 1].h) return tbl[tbl.length - 1].q;
      for (var j = 0; j < tbl.length - 1; j++) {
        if (h >= tbl[j].h && h <= tbl[j + 1].h) {
          var frac = (h - tbl[j].h) / (tbl[j + 1].h - tbl[j].h);
          return tbl[j].q + frac * (tbl[j + 1].q - tbl[j].q);
        }
      }
      return null;
    }

    if (type === 'piecewise_power') {
      var hCalc = h;
      if (params.transform_offset !== undefined || params.transform_divisor !== undefined) {
        hCalc = (params.transform_offset || 0) - h / (params.transform_divisor || 1);
      }
      if (hCalc <= 0) return 0;
      var pwSegs = params.segments || [];
      for (var k = 0; k < pwSegs.length; k++) {
        var seg = pwSegs[k];
        if (seg.h_max !== undefined && hCalc <= seg.h_max) {
          return (seg.a || 0) * Math.pow(hCalc, seg.b || 0);
        }
        if (seg.h_max === undefined) {
          return (seg.a || 0) * Math.pow(hCalc, seg.b || 0);
        }
      }
      if (pwSegs.length) {
        var ls = pwSegs[pwSegs.length - 1];
        return (ls.a || 0) * Math.pow(hCalc, ls.b || 0);
      }
      return null;
    }

    return null;
  }

  /* ── Time range presets ────────────────────────────── */
  function setPreset(hours) {
    activeHours = hours;
    var btns = document.querySelectorAll('.dash-presets .btn');
    btns.forEach(function (b) { b.classList.remove('active'); });
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

  /* ── Data fetching ─────────────────────────────────── */
  function fetchData() {
    var startVal = $('dashStart').value;
    var endVal = $('dashEnd').value;
    if (!startVal || !endVal) return;

    var startTs = new Date(startVal).getTime();
    var endTs = new Date(endVal).getTime();

    var preset = PRESETS[activeHours];
    var limit = (preset && preset.limit) || 2000;
    var url = DISCHARGE_URL + '?start_ts=' + startTs + '&end_ts=' + endTs + '&limit=' + limit;
    var csvParams = '?start_ts=' + startTs + '&end_ts=' + endTs + '&limit=10000';

    if (preset && preset.agg) {
      url += '&agg=' + preset.agg + '&interval=' + preset.interval;
      csvParams += '&agg=' + preset.agg + '&interval=' + preset.interval;
    }

    var csvLink = $('dashCsvLink');
    if (csvLink) csvLink.href = CSV_URL + csvParams;

    // Aggregation badge
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

  /* ── Data processing ───────────────────────────────── */
  function processData(data) {
    var discharge = data.discharge || {};
    var points = [];
    for (var key in discharge) {
      points = points.concat(discharge[key]);
    }
    points.sort(function (a, b) { return (a.ts || 0) - (b.ts || 0); });

    currentPoints = points;

    if (points.length === 0) {
      $('dashNoData').style.display = 'block';
      updateStats([], []);
      updateSummary(null, null, 0, null);
      renderTable([]);
      if (mainChart) { mainChart.destroy(); mainChart = null; }
      return;
    }

    var last = points[points.length - 1];
    var hArr = points.map(function (p) { return p.h; });
    var qArr = points.map(function (p) { return p.q; });

    updateSummary(last.h, last.q, points.length, last.ts);
    updateStats(hArr, qArr);
    renderMainChart(points);
    renderHQChart(points);
    renderTable(points);
  }

  /* ── Summary cards ─────────────────────────────────── */
  function updateSummary(h, q, count, ts) {
    animateValue('dashSummH', fmtNum(h, 2));
    animateValue('dashSummQ', fmtNum(q, 4));
    animateValue('dashSummCount', count !== null ? String(count) : '—');
    animateValue('dashSummTime', ts ? toUTC(ts) : '—');
  }

  function animateValue(id, newVal) {
    var el = $(id);
    if (!el) return;
    el.classList.add('updating');
    el.textContent = newVal;
    setTimeout(function () { el.classList.remove('updating'); }, 600);
  }

  /* ── Statistics panel ──────────────────────────────── */
  function updateStats(hArr, qArr) {
    var hStats = calcStats(hArr);
    var qStats = calcStats(qArr);

    setStatVal('statHMin', hStats.min, 2);
    setStatVal('statHMax', hStats.max, 2);
    setStatVal('statHAvg', hStats.avg, 2);
    setStatVal('statHStd', hStats.std, 3);

    setStatVal('statQMin', qStats.min, 4);
    setStatVal('statQMax', qStats.max, 4);
    setStatVal('statQAvg', qStats.avg, 4);
    setStatVal('statQStd', qStats.std, 4);
  }

  function setStatVal(id, val, dec) {
    var el = $(id);
    if (!el) return;
    el.textContent = fmtNum(val, dec);
  }

  /* ── Main chart ────────────────────────────────────── */
  function renderMainChart(points) {
    var labels = points.map(function (p) { return new Date(p.ts); });
    var hData = points.map(function (p) { return p.h; });
    var qData = points.map(function (p) { return p.q; });

    if (mainChart) mainChart.destroy();

    var ctx = $('dashMainCanvas').getContext('2d');
    var isBar = (chartType === 'bar');
    var isScatter = (chartType === 'scatter');
    var type = isBar ? 'bar' : (isScatter ? 'scatter' : 'line');

    var datasets = [
      {
        label: t('water_level', 'Water Level') + ' (' + UNIT_H + ')',
        data: isScatter
          ? labels.map(function (l, i) { return { x: l, y: hData[i] }; })
          : hData,
        borderColor: chartOpts.colorH,
        backgroundColor: chartOpts.showFill
          ? hexToRGBA(chartOpts.colorH, 0.1)
          : 'transparent',
        fill: !isScatter && !isBar && chartOpts.showFill,
        tension: isScatter || isBar ? 0 : chartOpts.tension,
        pointRadius: isScatter ? 3 : (chartOpts.showPoints ? 2 : 0),
        borderWidth: chartOpts.lineWidth,
        yAxisID: 'yH',
        order: 2,
      },
      {
        label: t('discharge', 'Discharge') + ' (' + UNIT_Q + ')',
        data: isScatter
          ? labels.map(function (l, i) { return { x: l, y: qData[i] }; })
          : qData,
        borderColor: chartOpts.colorQ,
        backgroundColor: isBar
          ? hexToRGBA(chartOpts.colorQ, 0.6)
          : (chartOpts.showFill ? hexToRGBA(chartOpts.colorQ, 0.08) : 'transparent'),
        fill: !isScatter && !isBar ? false : undefined,
        tension: isScatter || isBar ? 0 : chartOpts.tension,
        pointRadius: isScatter ? 3 : (chartOpts.showPoints ? 2 : 0),
        borderWidth: chartOpts.lineWidth,
        borderDash: isBar || isScatter ? [] : [5, 3],
        yAxisID: 'yQ',
        order: 1,
      }
    ];

    var resetBtn = $('dashResetZoom');

    mainChart = new Chart(ctx, {
      type: type,
      data: {
        labels: isScatter ? undefined : labels,
        datasets: datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          tooltip: {
            callbacks: {
              title: function (items) {
                var val = items[0].parsed.x;
                return toUTC(val);
              },
            },
          },
          legend: { position: 'top', labels: { usePointStyle: true, padding: 16 } },
          zoom: {
            pan: { enabled: true, mode: 'x', onPanComplete: function() { if (resetBtn) resetBtn.style.display = 'block'; } },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              mode: 'x',
              onZoomComplete: function() { if (resetBtn) resetBtn.style.display = 'block'; },
            },
          },
        },
        scales: {
          x: {
            type: isScatter ? 'time' : 'time',
            time: { tooltipFormat: 'yyyy-MM-dd HH:mm' },
            title: { display: true, text: t('time_utc', 'Time (UTC)'), font: { size: 12 } },
          },
          yH: {
            type: 'linear',
            position: 'left',
            title: { display: true, text: t('water_level', 'Water Level') + ' (' + UNIT_H + ')', font: { size: 12 } },
            grid: { drawOnChartArea: true },
          },
          yQ: {
            type: 'linear',
            position: 'right',
            title: { display: true, text: t('discharge', 'Discharge') + ' (' + UNIT_Q + ')', font: { size: 12 } },
            grid: { drawOnChartArea: false },
          },
        },
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

  /* ── H-Q Rating curve chart ────────────────────────── */
  function renderHQChart(points) {
    if (!CURVE_TYPE || !CURVE_PARAMS) {
      var container = $('dashHQSection');
      if (container) container.style.display = 'none';
      return;
    }

    var container2 = $('dashHQSection');
    if (container2) container2.style.display = 'block';

    if (hqChart) hqChart.destroy();

    // Observed points
    var observed = points
      .filter(function (p) { return p.h !== null && p.q !== null; })
      .map(function (p) { return { x: p.h, y: p.q }; });

    // Theoretical curve
    var hMin = Infinity, hMax = -Infinity;
    points.forEach(function (p) {
      if (p.h !== null && p.h !== undefined) {
        if (p.h < hMin) hMin = p.h;
        if (p.h > hMax) hMax = p.h;
      }
    });

    if (hMin === Infinity) { hMin = 0; hMax = 5; }
    var range = hMax - hMin;
    hMin = Math.max(0, hMin - range * 0.1);
    hMax = hMax + range * 0.1;

    var theoretical = [];
    var steps = 100;
    for (var i = 0; i <= steps; i++) {
      var h = hMin + (hMax - hMin) * i / steps;
      var q = computeQ(h, CURVE_TYPE, CURVE_PARAMS);
      if (q !== null && !isNaN(q) && q >= 0) {
        theoretical.push({ x: h, y: q });
      }
    }

    var ctx = $('dashHQCanvas').getContext('2d');
    hqChart = new Chart(ctx, {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: t('theoretical_curve', 'Theoretical Curve'),
            data: theoretical,
            borderColor: '#ff9800',
            backgroundColor: 'rgba(255,152,0,0.1)',
            showLine: true,
            borderWidth: 2.5,
            pointRadius: 0,
            fill: true,
            order: 2,
          },
          {
            label: t('observed_points', 'Observed Points'),
            data: observed,
            borderColor: '#0b6efd',
            backgroundColor: 'rgba(11,110,253,0.5)',
            pointRadius: 3,
            pointHoverRadius: 5,
            showLine: false,
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { usePointStyle: true, padding: 16 } },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return 'H=' + fmtNum(ctx.parsed.x, 2) + ' ' + UNIT_H +
                       ', Q=' + fmtNum(ctx.parsed.y, 4) + ' ' + UNIT_Q;
              },
            },
          },
          zoom: {
            pan: { enabled: true, mode: 'xy' },
            zoom: {
              wheel: { enabled: true },
              pinch: { enabled: true },
              mode: 'xy',
            },
          },
        },
        scales: {
          x: {
            type: 'linear',
            title: { display: true, text: t('water_level', 'Water Level') + ' (' + UNIT_H + ')', font: { size: 12 } },
          },
          y: {
            type: 'linear',
            title: { display: true, text: t('discharge', 'Discharge') + ' (' + UNIT_Q + ')', font: { size: 12 } },
            beginAtZero: true,
          },
        },
        animation: { duration: 400 },
      },
    });
  }

  /* ── Data table ────────────────────────────────────── */
  function renderTable(points) {
    var tbody = $('dashTableBody');
    if (!tbody) return;

    if (points.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:#888;padding:20px;">' + t('no_data', 'No data') + '</td></tr>';
      updateTableCount(0);
      return;
    }

    var sorted = points.slice().reverse();
    var html = '';
    for (var i = 0; i < sorted.length; i++) {
      var p = sorted[i];
      html += '<tr>' +
        '<td>' + (p.ts ? toUTC(p.ts) : '—') + '</td>' +
        '<td class="num">' + fmtNum(p.h, 2) + '</td>' +
        '<td class="num">' + fmtNum(p.q, 4) + '</td>' +
        '</tr>';
    }
    tbody.innerHTML = html;
    updateTableCount(sorted.length);
  }

  function updateTableCount(n) {
    var el = $('dashTableCount');
    if (el) el.textContent = n + ' ' + t('records', 'records');
  }

  /* ── Table search ──────────────────────────────────── */
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

  /* ── Chart type switching ──────────────────────────── */
  function initChartTypes() {
    document.querySelectorAll('.dash-chart-types .type-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('.dash-chart-types .type-btn').forEach(function (b) { b.classList.remove('active'); });
        this.classList.add('active');
        chartType = this.getAttribute('data-type');
        if (currentPoints.length) renderMainChart(currentPoints);
      });
    });
  }

  /* ── Chart options panel ───────────────────────────── */
  function initChartOptions() {
    var toggleBtn = $('dashOptToggle');
    var panel = $('dashOptPanel');
    if (!toggleBtn || !panel) return;

    toggleBtn.addEventListener('click', function () {
      panel.classList.toggle('open');
      this.classList.toggle('active');
    });

    // Line width
    var lwSlider = $('optLineWidth');
    var lwVal = $('optLineWidthVal');
    if (lwSlider) {
      lwSlider.addEventListener('input', function () {
        chartOpts.lineWidth = parseInt(this.value);
        if (lwVal) lwVal.textContent = this.value + 'px';
        refreshChartStyle();
      });
    }

    // Tension
    var tensionSel = $('optTension');
    if (tensionSel) {
      tensionSel.addEventListener('change', function () {
        chartOpts.tension = parseFloat(this.value);
        refreshChartStyle();
      });
    }

    // Fill toggle
    var fillToggle = $('optFill');
    if (fillToggle) {
      fillToggle.addEventListener('change', function () {
        chartOpts.showFill = this.checked;
        refreshChartStyle();
      });
    }

    // Points toggle
    var pointsToggle = $('optPoints');
    if (pointsToggle) {
      pointsToggle.addEventListener('change', function () {
        chartOpts.showPoints = this.checked;
        refreshChartStyle();
      });
    }

    // Color presets
    document.querySelectorAll('.dash-color-swatch[data-target="h"]').forEach(function (el) {
      el.addEventListener('click', function () {
        document.querySelectorAll('.dash-color-swatch[data-target="h"]').forEach(function (s) { s.classList.remove('active'); });
        this.classList.add('active');
        chartOpts.colorH = this.getAttribute('data-color');
        refreshChartStyle();
      });
    });

    document.querySelectorAll('.dash-color-swatch[data-target="q"]').forEach(function (el) {
      el.addEventListener('click', function () {
        document.querySelectorAll('.dash-color-swatch[data-target="q"]').forEach(function (s) { s.classList.remove('active'); });
        this.classList.add('active');
        chartOpts.colorQ = this.getAttribute('data-color');
        refreshChartStyle();
      });
    });
  }

  function refreshChartStyle() {
    if (currentPoints.length) renderMainChart(currentPoints);
  }

  /* ── Fullscreen ────────────────────────────────────── */
  function initFullscreen() {
    var btn = $('dashFullscreen');
    var wrap = $('dashMainWrap');
    if (!btn || !wrap) return;

    btn.addEventListener('click', function () {
      if (wrap.requestFullscreen) wrap.requestFullscreen();
      else if (wrap.webkitRequestFullscreen) wrap.webkitRequestFullscreen();
    });

    document.addEventListener('fullscreenchange', function () {
      if (mainChart) {
        setTimeout(function () { mainChart.resize(); }, 100);
      }
    });
  }

  /* ── Auto-refresh ──────────────────────────────────── */
  function initAutoRefresh() {
    var toggle = $('dashAutoRefresh');
    var intervalSel = $('dashAutoInterval');
    var pulse = $('dashPulse');
    var countdownEl = $('dashCountdown');
    if (!toggle) return;

    toggle.addEventListener('change', function () {
      if (this.checked) {
        startAutoRefresh();
      } else {
        stopAutoRefresh();
      }
    });

    if (intervalSel) {
      intervalSel.addEventListener('change', function () {
        if (toggle.checked) {
          stopAutoRefresh();
          startAutoRefresh();
        }
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
          // Re-apply the active preset to refresh the end time
          if (activeHours > 0) {
            setPreset(activeHours);
          } else {
            fetchData();
          }
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

  /* ── Color utility ─────────────────────────────────── */
  function hexToRGBA(hex, alpha) {
    hex = hex.replace('#', '');
    if (hex.length === 3) {
      hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    }
    var r = parseInt(hex.substring(0, 2), 16);
    var g = parseInt(hex.substring(2, 4), 16);
    var b = parseInt(hex.substring(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
  }

  /* ── Init ──────────────────────────────────────────── */
  function init() {
    initTimeControls();
    initChartTypes();
    initChartOptions();
    initFullscreen();
    initAutoRefresh();
    initTableSearch();

    // Load default 24h
    setPreset(24);
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
