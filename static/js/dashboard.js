/* Graphiques du tableau de bord (Chart.js). Les données viennent de #chart-data. */
(function () {
  var source = document.getElementById("chart-data");
  if (!source || typeof Chart === "undefined") return;
  var data = JSON.parse(source.textContent);

  var ink = "#0f1f1a";
  var muted = "#64748b";
  var grid = "rgba(15, 31, 26, 0.06)";
  var brand = "#0b7d62";
  var expense = "#fb7185";

  var compact = new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 });
  var full = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  function fc(value) { return full.format(value) + " FC"; }

  Chart.defaults.font.family = "Manrope, system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = muted;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.plugins.tooltip.backgroundColor = ink;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.titleFont = { weight: "700" };

  var moneyAxis = {
    beginAtZero: true,
    border: { display: false },
    grid: { color: grid },
    ticks: { callback: function (v) { return compact.format(v); }, maxTicksLimit: 6 },
  };
  var categoryAxis = { border: { display: false }, grid: { display: false } };
  function tooltipLabel(ctx) {
    return " " + ctx.dataset.label + " : " + fc(ctx.parsed.y !== undefined ? ctx.parsed.y : ctx.parsed);
  }

  // Revenus vs dépenses sur 12 mois
  var cashflow = document.getElementById("chart-cashflow");
  if (cashflow) {
    new Chart(cashflow, {
      type: "bar",
      data: {
        labels: data.months,
        datasets: [
          { label: "Revenus", data: data.income, backgroundColor: brand, borderRadius: 6, maxBarThickness: 22 },
          { label: "Dépenses", data: data.expense, backgroundColor: expense, borderRadius: 6, maxBarThickness: 22 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: { x: categoryAxis, y: moneyAxis },
        plugins: { tooltip: { callbacks: { label: tooltipLabel } } },
      },
    });
  }

  // Dépenses par catégorie
  var categories = document.getElementById("chart-categories");
  if (categories && data.categories.values.length) {
    new Chart(categories, {
      type: "doughnut",
      data: {
        labels: data.categories.labels,
        datasets: [{
          label: "Dépenses",
          data: data.categories.values,
          backgroundColor: data.categories.colors,
          borderColor: "#fff",
          borderWidth: 3,
          hoverOffset: 6,
        }],
      },
      options: {
        cutout: "72%",
        plugins: { tooltip: { callbacks: { label: function (ctx) { return " " + ctx.label + " : " + fc(ctx.parsed); } } } },
      },
    });
  }

  // Évolution du solde
  var networth = document.getElementById("chart-networth");
  if (networth) {
    var ctx = networth.getContext("2d");
    var gradient = ctx.createLinearGradient(0, 0, 0, 260);
    gradient.addColorStop(0, "rgba(11, 125, 98, 0.25)");
    gradient.addColorStop(1, "rgba(11, 125, 98, 0)");
    new Chart(networth, {
      type: "line",
      data: {
        labels: data.months,
        datasets: [{
          label: "Solde",
          data: data.netWorth,
          borderColor: brand,
          backgroundColor: gradient,
          fill: true,
          tension: 0.35,
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointBackgroundColor: brand,
        }],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: Object.assign({}, categoryAxis, { ticks: { maxTicksLimit: 6 } }),
          y: Object.assign({}, moneyAxis, { beginAtZero: false }),
        },
        plugins: { tooltip: { callbacks: { label: tooltipLabel } } },
      },
    });
  }
})();
