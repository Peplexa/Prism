/**
 * Preferred Source Mode for the Media Comparison Report.
 *
 * Highlights a user-selected source across all report sections:
 *  - Summary table row
 *  - Source coverage chips
 *  - Source article rows
 *  - Matrix column (headers + cells)
 *  - Chart.js bar charts (dims non-selected)
 *  - Timeline rows
 *
 * Persists via server (authenticated) or localStorage (anonymous).
 *
 * Expects globals: sourceSummaryData, userPreferredSource, isAuthenticated
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'prism_preferred_source';
    var sourceData = window.sourceSummaryData || [];
    if (!sourceData.length) return;

    var picker, select, clearBtn, card;

    document.addEventListener('DOMContentLoaded', init);

    function init() {
        picker = document.getElementById('preferred-source-picker');
        select = document.getElementById('preferred-source-select');
        clearBtn = document.getElementById('preferred-source-clear');
        card = document.getElementById('preferred-source-card');
        if (!picker || !select) return;

        // Populate dropdown
        sourceData.forEach(function (src) {
            var opt = document.createElement('option');
            opt.value = src.source_name;
            opt.textContent = src.source_name;
            select.appendChild(opt);
        });
        picker.style.display = '';

        // Restore preference: server value takes priority, then localStorage
        var saved = window.userPreferredSource || localStorage.getItem(STORAGE_KEY) || '';
        if (saved && sourceData.some(function (s) { return s.source_name === saved; })) {
            select.value = saved;
            applyPreference(saved);
        }

        // Events
        select.addEventListener('change', function () {
            var val = select.value;
            if (val) {
                savePreference(val);
                applyPreference(val);
            } else {
                clearPreference();
            }
        });

        clearBtn.addEventListener('click', function () {
            clearPreference();
        });

        // Re-apply chart highlights when collapsible charts section is opened
        var origToggleSection = window.toggleSection;
        if (origToggleSection) {
            window.toggleSection = function (id) {
                origToggleSection(id);
                if (id === 'detail-charts' && select.value) {
                    setTimeout(function () { highlightCharts(select.value); }, 150);
                }
            };
        }
    }

    // --- Persistence ---

    function savePreference(sourceName) {
        localStorage.setItem(STORAGE_KEY, sourceName);
        if (window.isAuthenticated) {
            var csrfToken = document.querySelector('meta[name="csrf-token"]');
            if (csrfToken) {
                var fd = new FormData();
                fd.append('source_name', sourceName);
                fetch('/preference/source/', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken.content },
                    body: fd,
                });
            }
        }
    }

    function clearPreference() {
        localStorage.removeItem(STORAGE_KEY);
        if (window.isAuthenticated) {
            var csrfToken = document.querySelector('meta[name="csrf-token"]');
            if (csrfToken) {
                var fd = new FormData();
                fd.append('source_name', '');
                fetch('/preference/source/', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken.content },
                    body: fd,
                });
            }
        }
        select.value = '';
        clearBtn.style.display = 'none';
        card.style.display = 'none';
        card.innerHTML = '';
        removeAllHighlights();
    }

    // --- Apply / Remove ---

    function applyPreference(sourceName) {
        clearBtn.style.display = 'inline-block';
        removeAllHighlights();
        highlightElements(sourceName);
        highlightMatrixColumn(sourceName);
        buildSummaryCard(sourceName);
        highlightCharts(sourceName);
        highlightContradictions(sourceName);
    }

    function removeAllHighlights() {
        document.querySelectorAll('.pref-highlight, .pref-highlight-chip, .pref-highlight-article, .pref-highlight-tl, .pref-col-highlight').forEach(function (el) {
            el.classList.remove('pref-highlight', 'pref-highlight-chip', 'pref-highlight-article', 'pref-highlight-tl', 'pref-col-highlight');
        });
        resetCharts();
        clearContradictionHighlights();
    }

    // --- Element Highlighting ---

    function highlightElements(sourceName) {
        // Summary table rows
        document.querySelectorAll('#source-summary-table tbody tr[data-source-name]').forEach(function (tr) {
            if (tr.getAttribute('data-source-name') === sourceName) {
                tr.classList.add('pref-highlight');
            }
        });

        // Source coverage chips
        document.querySelectorAll('.source-chip[data-source-name]').forEach(function (el) {
            if (el.getAttribute('data-source-name') === sourceName) {
                el.classList.add('pref-highlight-chip');
            }
        });

        // Source article rows
        document.querySelectorAll('.source-article-row[data-source-name]').forEach(function (el) {
            if (el.getAttribute('data-source-name') === sourceName) {
                el.classList.add('pref-highlight-article');
            }
        });

        // Timeline rows
        document.querySelectorAll('.tl-row[data-source-name]').forEach(function (el) {
            if (el.getAttribute('data-source-name') === sourceName) {
                el.classList.add('pref-highlight-tl');
            }
        });
    }

    function highlightMatrixColumn(sourceName) {
        document.querySelectorAll('th.matrix-source-header[data-source-name]').forEach(function (th) {
            if (th.getAttribute('data-source-name') === sourceName) {
                th.classList.add('pref-col-highlight');
            }
        });
        document.querySelectorAll('td.matrix-cell[data-source-name]').forEach(function (td) {
            if (td.getAttribute('data-source-name') === sourceName) {
                td.classList.add('pref-col-highlight');
            }
        });
    }

    // --- Summary Card ---

    function buildSummaryCard(sourceName) {
        var src = sourceData.find(function (s) { return s.source_name === sourceName; });
        if (!src || !card) return;

        var avgCoverage = avg(sourceData, 'weighted_coverage_pct');
        var avgSubjectivity = avg(sourceData, 'subjectivity_pct');

        var html = '<h3>' + escHtml(src.source_name) + ' vs. Average</h3>';
        html += '<div class="pref-stats">';

        // Coverage
        if (src.weighted_coverage_pct !== null) {
            var covDelta = src.weighted_coverage_pct - avgCoverage;
            html += statBlock('Coverage', src.weighted_coverage_pct + '%', covDelta, '%', true);
        }

        // Subjectivity
        if (src.subjectivity_pct !== null) {
            var subDelta = src.subjectivity_pct - avgSubjectivity;
            html += statBlock('Subjectivity', src.subjectivity_pct + '%', subDelta, '%', false);
        }

        // Leaning
        if (src.dominant_leaning) {
            html += '<div class="pref-stat">';
            html += '<div class="pref-stat-value"><span class="leaning-badge leaning-' + src.dominant_leaning + '">' + capitalize(src.dominant_leaning) + '</span></div>';
            html += '<div class="pref-stat-label">Leaning</div>';
            html += '</div>';
        }

        // Tone label
        if (src.tone_label) {
            html += '<div class="pref-stat">';
            html += '<div class="pref-stat-value" style="font-size: 0.95rem;">' + escHtml(src.tone_label) + '</div>';
            html += '<div class="pref-stat-label">Tone</div>';
            html += '</div>';
        }

        // Disputed claims
        if (window.contradictionsData && window.contradictionsData.length) {
            var conflicts = window.contradictionsData.filter(function (c) {
                return c.nugget_a_supporters.indexOf(sourceName) !== -1 ||
                       c.nugget_b_supporters.indexOf(sourceName) !== -1;
            });
            if (conflicts.length > 0) {
                html += '<div class="pref-stat">';
                html += '<div class="pref-stat-value" style="color: #f59e0b;">' + conflicts.length + '</div>';
                html += '<div class="pref-stat-label">Disputed Claims</div>';
                html += '</div>';
            }
        }

        html += '</div>';
        card.innerHTML = html;
        card.style.display = '';
    }

    function statBlock(label, value, delta, unit, higherIsBetter) {
        var sign = delta > 0 ? '+' : '';
        var cls = 'pref-delta-neutral';
        if (Math.abs(delta) >= 1) {
            cls = (higherIsBetter ? delta > 0 : delta < 0) ? 'pref-delta-positive' : 'pref-delta-negative';
        }
        return '<div class="pref-stat">' +
            '<div class="pref-stat-value">' + value + '</div>' +
            '<div class="pref-stat-label">' + label + '</div>' +
            '<div class="pref-stat-delta ' + cls + '">' + sign + Math.round(delta) + unit + ' vs avg</div>' +
            '</div>';
    }

    // --- Chart.js Highlighting ---

    function highlightCharts(sourceName) {
        highlightBarChart('omission-chart', window.omissionData, sourceName, function (d) {
            var pct = d.weighted_coverage_pct || d.coverage_pct;
            if (pct >= 70) return '#22c55e';
            if (pct >= 40) return '#eab308';
            return '#ef4444';
        });
        highlightBarChart('tone-chart', window.toneData, sourceName, function () {
            return '#6366f1';
        });
        highlightFramingChart(sourceName);
    }

    function resetCharts() {
        resetBarChart('omission-chart', window.omissionData, function (d) {
            var pct = d.weighted_coverage_pct || d.coverage_pct;
            if (pct >= 70) return '#22c55e';
            if (pct >= 40) return '#eab308';
            return '#ef4444';
        });
        resetBarChart('tone-chart', window.toneData, function () {
            return '#6366f1';
        });
        resetFramingChart();
    }

    function highlightBarChart(canvasId, data, sourceName, colorFn) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || !data || typeof Chart === 'undefined') return;
        var chart = Chart.getChart(canvas);
        if (!chart) return;

        var colors = [];
        var borders = [];
        for (var i = 0; i < data.length; i++) {
            var baseColor = colorFn(data[i]);
            if (data[i].source_name === sourceName) {
                colors.push(baseColor);
                borders.push('#fff');
            } else {
                colors.push(addAlpha(baseColor, 0.25));
                borders.push('transparent');
            }
        }
        chart.data.datasets[0].backgroundColor = colors;
        chart.data.datasets[0].borderColor = borders;
        chart.data.datasets[0].borderWidth = borders.map(function (b) { return b === 'transparent' ? 0 : 2; });
        chart.update('none');
    }

    function resetBarChart(canvasId, data, colorFn) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || !data || typeof Chart === 'undefined') return;
        var chart = Chart.getChart(canvas);
        if (!chart) return;

        chart.data.datasets[0].backgroundColor = data.map(colorFn);
        chart.data.datasets[0].borderColor = undefined;
        chart.data.datasets[0].borderWidth = undefined;
        chart.update('none');
    }

    function highlightFramingChart(sourceName) {
        var canvas = document.getElementById('framing-chart');
        if (!canvas || !window.framingData || typeof Chart === 'undefined') return;
        var chart = Chart.getChart(canvas);
        if (!chart) return;

        var origColors = ['#3b82f6', '#8b5cf6', '#ef4444'];
        chart.data.datasets.forEach(function (ds, dsIdx) {
            var newColors = [];
            for (var i = 0; i < window.framingData.length; i++) {
                if (window.framingData[i].source_name === sourceName) {
                    newColors.push(origColors[dsIdx]);
                } else {
                    newColors.push(addAlpha(origColors[dsIdx], 0.2));
                }
            }
            ds.backgroundColor = newColors;
        });
        chart.update('none');
    }

    function resetFramingChart() {
        var canvas = document.getElementById('framing-chart');
        if (!canvas || !window.framingData || typeof Chart === 'undefined') return;
        var chart = Chart.getChart(canvas);
        if (!chart) return;

        var origColors = ['#3b82f6', '#8b5cf6', '#ef4444'];
        chart.data.datasets.forEach(function (ds, dsIdx) {
            ds.backgroundColor = origColors[dsIdx];
        });
        chart.update('none');
    }

    // --- Contradiction Callouts ---

    function highlightContradictions(sourceName) {
        var cards = document.querySelectorAll('.contradiction-card');
        if (!cards.length || !window.contradictionsData) return;

        window.contradictionsData.forEach(function (c, idx) {
            var card = cards[idx];
            if (!card) return;
            var callout = card.querySelector('.contradiction-pref-callout');
            if (!callout) return;

            var onSideA = c.nugget_a_supporters.indexOf(sourceName) !== -1;
            var onSideB = c.nugget_b_supporters.indexOf(sourceName) !== -1;
            var consensusSide = c.consensus_side;

            if (!onSideA && !onSideB) {
                callout.style.display = 'none';
                return;
            }

            var msg = '';
            if (onSideA && consensusSide === 'b') {
                // Source is on the non-consensus side (a is minority here)
                msg = '<strong>' + escHtml(sourceName) + '</strong> reports: &ldquo;' +
                    escHtml(c.nugget_a_text) + '&rdquo; &mdash; but ' +
                    c.nugget_b_supporters.length + ' other source' +
                    (c.nugget_b_supporters.length !== 1 ? 's' : '') +
                    ' report the consensus version.';
            } else if (onSideB && consensusSide === 'a') {
                // Source is on the non-consensus side (b is minority)
                msg = '<strong>' + escHtml(sourceName) + '</strong> reports: &ldquo;' +
                    escHtml(c.nugget_b_text) + '&rdquo; &mdash; but ' +
                    c.nugget_a_supporters.length + ' other source' +
                    (c.nugget_a_supporters.length !== 1 ? 's' : '') +
                    ' report the consensus version.';
            } else if (onSideA) {
                msg = '<strong>' + escHtml(sourceName) + '</strong> ' +
                    (consensusSide === 'a' ? 'agrees with the consensus' : 'reports') +
                    ': &ldquo;' + escHtml(c.nugget_a_text) + '&rdquo;';
            } else {
                msg = '<strong>' + escHtml(sourceName) + '</strong> ' +
                    (consensusSide === 'b' ? 'agrees with the consensus' : 'reports') +
                    ': &ldquo;' + escHtml(c.nugget_b_text) + '&rdquo;';
            }

            callout.innerHTML = msg;
            callout.style.display = '';
        });
    }

    function clearContradictionHighlights() {
        document.querySelectorAll('.contradiction-pref-callout').forEach(function (el) {
            el.style.display = 'none';
            el.innerHTML = '';
        });
    }

    // --- Utilities ---

    function addAlpha(hexColor, alpha) {
        if (hexColor.charAt(0) !== '#') return hexColor;
        var r = parseInt(hexColor.slice(1, 3), 16);
        var g = parseInt(hexColor.slice(3, 5), 16);
        var b = parseInt(hexColor.slice(5, 7), 16);
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    }

    function avg(data, field) {
        var vals = data.filter(function (d) { return d[field] !== null && d[field] !== undefined; })
                       .map(function (d) { return d[field]; });
        if (!vals.length) return 0;
        return vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
    }

    function escHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function capitalize(str) {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

})();
