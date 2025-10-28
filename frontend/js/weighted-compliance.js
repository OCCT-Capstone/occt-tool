// frontend/js/weighted-compliance.js
(function () {
  const canvas = document.getElementById("weightedComplianceChart");
  const percentEl = document.getElementById("wcPercent");
  if (!canvas || !percentEl) return;

  const api = (window.occt && window.occt.api) ? window.occt.api : (p => '/api/sample' + p);

  function render(data) {
    const COLORS = {
      pass: "#22c55e",     // green
      high: "#ef4444",     // red
      medium: "#f97316",   // orange
      low: "#fbbf24",      // amber
      critical: "#a855f7"  // purple (optional)
    };

    const score = Number(data?.score ?? 0);
    percentEl.textContent = isFinite(score) ? String(score) : "0";

    const pts = data?.points || {};
    const series = [
      pts.pass || 0,
      pts.fail_high || 0,
      pts.fail_medium || 0,
      pts.fail_low || 0
      // If you want critical in the ring too, add: pts.fail_critical || 0
    ];

    const ctx = canvas.getContext("2d");
    // eslint-disable-next-line no-undef
    new Chart(ctx, {
      type: "doughnut",
      data: {
        labels: ["Pass", "High", "Medium", "Low"],
        datasets: [{
          data: series,
          backgroundColor: [COLORS.pass, COLORS.high, COLORS.medium, COLORS.low],
          borderWidth: 0,
          hoverOffset: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "68%",
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${ctx.parsed} pts`
            }
          }
        },
        layout: { padding: 6 }
      }
    });
  }

  fetch(api("/weighted-compliance"))
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(render)
    .catch(() => {
      percentEl.textContent = "0";
    });
})();
