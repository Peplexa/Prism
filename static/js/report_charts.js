/**
 * Chart.js charts for the Media Comparison Report.
 *
 * Expects omissionData, toneData, framingData globals set by the template.
 */

document.addEventListener('DOMContentLoaded', function () {

    // Dark theme defaults
    Chart.defaults.color = '#a3a3a3';
    Chart.defaults.borderColor = '#333';

    // 1. Coverage Completeness (horizontal bar)
    if (typeof omissionData !== 'undefined' && omissionData.length > 0) {
        new Chart(document.getElementById('omission-chart'), {
            type: 'bar',
            data: {
                labels: omissionData.map(function (d) { return d.source_name; }),
                datasets: [{
                    label: 'Weighted Coverage %',
                    data: omissionData.map(function (d) { return d.weighted_coverage_pct || d.coverage_pct; }),
                    backgroundColor: omissionData.map(function (d) {
                        var pct = d.weighted_coverage_pct || d.coverage_pct;
                        if (pct >= 70) return '#22c55e';
                        if (pct >= 40) return '#eab308';
                        return '#ef4444';
                    }),
                    borderRadius: 4,
                }],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                var d = omissionData[ctx.dataIndex];
                                var raw = d.coverage_pct;
                                return ctx.raw + '% weighted coverage (' + raw + '% raw)';
                            }
                        }
                    }
                },
                scales: {
                    x: { max: 100, title: { display: true, text: 'Coverage %' } },
                },
            },
        });
    }

    // 2. Tone / Subjectivity (horizontal bar)
    if (typeof toneData !== 'undefined' && toneData.length > 0) {
        new Chart(document.getElementById('tone-chart'), {
            type: 'bar',
            data: {
                labels: toneData.map(function (d) { return d.source_name; }),
                datasets: [{
                    label: 'Subjectivity %',
                    data: toneData.map(function (d) { return d.subjectivity_pct; }),
                    backgroundColor: '#6366f1',
                    borderRadius: 4,
                }],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                return ctx.raw + '% subjective sentences';
                            }
                        }
                    }
                },
                scales: {
                    x: { max: 100, title: { display: true, text: 'Subjectivity %' } },
                },
            },
        });
    }

    // 3. Framing (stacked horizontal bar)
    if (typeof framingData !== 'undefined' && framingData.length > 0) {
        new Chart(document.getElementById('framing-chart'), {
            type: 'bar',
            data: {
                labels: framingData.map(function (d) { return d.source_name; }),
                datasets: [
                    {
                        label: 'Left',
                        data: framingData.map(function (d) { return d.left_pct; }),
                        backgroundColor: '#3b82f6',
                    },
                    {
                        label: 'Center',
                        data: framingData.map(function (d) { return d.center_pct; }),
                        backgroundColor: '#8b5cf6',
                    },
                    {
                        label: 'Right',
                        data: framingData.map(function (d) { return d.right_pct; }),
                        backgroundColor: '#ef4444',
                    },
                ],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom' },
                },
                scales: {
                    x: { stacked: true, max: 100, title: { display: true, text: '%' } },
                    y: { stacked: true },
                },
            },
        });
    }

    // ============================================
    // Summary Table Sorting
    // ============================================
    (function () {
        var table = document.getElementById('source-summary-table');
        if (!table) return;

        var headers = table.querySelectorAll('th.sortable');
        var tbody = table.querySelector('tbody');

        headers.forEach(function (th) {
            th.addEventListener('click', function () {
                var currentDir = th.classList.contains('sort-asc') ? 'asc' : 'desc';
                var newDir = currentDir === 'desc' ? 'asc' : 'desc';

                // Reset all headers
                headers.forEach(function (h) {
                    h.classList.remove('sort-active', 'sort-asc', 'sort-desc');
                });
                th.classList.add('sort-active', 'sort-' + newDir);

                var rows = Array.from(tbody.querySelectorAll('tr'));
                var colIndex = Array.from(th.parentNode.children).indexOf(th);

                rows.sort(function (a, b) {
                    var aVal = a.children[colIndex].dataset.value || a.children[colIndex].textContent.trim();
                    var bVal = b.children[colIndex].dataset.value || b.children[colIndex].textContent.trim();

                    var aNum = parseFloat(aVal);
                    var bNum = parseFloat(bVal);
                    if (!isNaN(aNum) && !isNaN(bNum)) {
                        return newDir === 'asc' ? aNum - bNum : bNum - aNum;
                    }
                    if (newDir === 'asc') {
                        return aVal.localeCompare(bVal);
                    }
                    return bVal.localeCompare(aVal);
                });

                rows.forEach(function (row) {
                    tbody.appendChild(row);
                });
            });
        });
    })();

});
