// Chart.js bar chart (CDN). Returns the chart instance, or null when Chart.js did not load.
export function createBarChart(canvas, { labels, values, label, unit = 'cm' }) {
  if (!window.Chart) return null;
  const css = getComputedStyle(document.documentElement);
  const amber = css.getPropertyValue('--amber').trim() || '#ffb020';
  const text = css.getPropertyValue('--text-2').trim() || '#b9c4da';
  const grid = 'rgba(160, 180, 220, 0.10)';
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  window.Chart.defaults.color = text;
  window.Chart.defaults.font.family = css.getPropertyValue('--font-body').trim() || 'Inter, sans-serif';

  return new window.Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        backgroundColor: 'rgba(255, 176, 32, 0.55)',
        borderColor: amber,
        borderWidth: 1,
        borderRadius: 6,
        maxBarThickness: 46,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: reduce ? false : { duration: 650 },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => `${c.parsed.y} ${unit}` } },
      },
      scales: {
        x: { grid: { color: grid }, ticks: { color: text } },
        y: {
          beginAtZero: true,
          grid: { color: grid },
          ticks: { color: text },
          title: { display: true, text: unit, color: text },
        },
      },
    },
  });
}
