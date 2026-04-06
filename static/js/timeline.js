(function () {
    'use strict';

    var ZOOM_LEVELS = [1, 1.5, 2, 3, 5];
    var SEARCH_DEBOUNCE_MS = 150;

    // State
    var items = window.timelineData || [];
    var currentZoomIdx = 0;
    var searchTimer = null;
    var renderedRows = [];   // {el, dotEl, item}
    var lastQuery = '';

    // DOM refs
    var viewport, canvas;
    var searchInput, zoomInBtn, zoomOutBtn, zoomLabel, noMatchEl;

    document.addEventListener('DOMContentLoaded', init);

    function init() {
        if (!items.length) return;

        viewport = document.getElementById('tl-viewport');
        canvas = document.getElementById('tl-canvas');
        searchInput = document.getElementById('tl-search');
        zoomInBtn = document.getElementById('tl-zoom-in');
        zoomOutBtn = document.getElementById('tl-zoom-out');
        zoomLabel = document.getElementById('tl-zoom-label');

        if (!viewport || !canvas) return;

        // No-match indicator
        noMatchEl = document.createElement('span');
        noMatchEl.className = 'tl-no-match';
        noMatchEl.textContent = 'No match';
        noMatchEl.style.display = 'none';
        searchInput.parentNode.insertBefore(noMatchEl, searchInput.nextSibling);

        // Sort by time
        items.sort(function (a, b) { return a.offset_pct - b.offset_pct; });

        // Render rows
        renderTimeline();

        // Search
        searchInput.addEventListener('input', function () {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(function () {
                onSearch(searchInput.value);
            }, SEARCH_DEBOUNCE_MS);
        });

        // Zoom
        zoomInBtn.addEventListener('click', function () { setZoom(currentZoomIdx + 1); });
        zoomOutBtn.addEventListener('click', function () { setZoom(currentZoomIdx - 1); });
        updateZoomButtons();
    }

    // === RENDER ===
    function renderTimeline() {
        canvas.innerHTML = '';
        renderedRows = [];

        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var isFirst = item.delta_minutes === 0;
            var timeStr = formatTime(item.published_at);

            // Row container
            var row = document.createElement('div');
            row.className = 'tl-row';
            row.title = item.source_name + ' \u2014 ' + timeStr +
                (item.delta_minutes > 0 ? ' (+' + item.delta_minutes + 'm)' : ' (First)') +
                (item.article_count > 1 ? ' \u2014 ' + item.article_count + ' articles' : '');

            // Source name
            var nameEl = document.createElement('div');
            nameEl.className = 'tl-row-name';
            nameEl.textContent = item.source_name;
            row.appendChild(nameEl);

            // Track with dot
            var track = document.createElement('div');
            track.className = 'tl-row-track';

            var dot = document.createElement('div');
            dot.className = 'tl-row-dot' + (isFirst ? ' tl-dot-first' : '');
            dot.style.left = item.offset_pct + '%';
            track.appendChild(dot);

            row.appendChild(track);

            // Meta: time + badges
            var meta = document.createElement('div');
            meta.className = 'tl-row-meta';

            var timeEl = document.createElement('span');
            timeEl.textContent = timeStr;
            meta.appendChild(timeEl);

            if (isFirst) {
                var firstTag = document.createElement('span');
                firstTag.className = 'tl-first-tag';
                firstTag.textContent = 'First';
                meta.appendChild(firstTag);
            }

            if (item.article_count > 1) {
                var badge = document.createElement('span');
                badge.className = 'tl-badge';
                badge.textContent = '\u00d7' + item.article_count;
                meta.appendChild(badge);
            }

            row.appendChild(meta);
            canvas.appendChild(row);

            renderedRows.push({ el: row, dotEl: dot, item: item });
        }

        // Re-apply search
        if (lastQuery) {
            applySearchHighlight(lastQuery);
        }
    }

    function formatTime(isoStr) {
        var d = new Date(isoStr);
        var h = d.getUTCHours().toString().padStart(2, '0');
        var m = d.getUTCMinutes().toString().padStart(2, '0');
        return h + ':' + m;
    }

    // === ZOOM ===
    function setZoom(newIdx) {
        newIdx = Math.max(0, Math.min(ZOOM_LEVELS.length - 1, newIdx));
        if (newIdx === currentZoomIdx) return;

        var vpWidth = viewport.offsetWidth;
        var oldCenter = viewport.scrollLeft + vpWidth / 2;
        var oldCanvasW = canvas.offsetWidth;
        var centerFrac = oldCanvasW > 0 ? oldCenter / oldCanvasW : 0.5;

        currentZoomIdx = newIdx;
        canvas.style.width = (ZOOM_LEVELS[newIdx] * 100) + '%';

        // Restore scroll centered on same point
        var newCanvasW = canvas.offsetWidth;
        viewport.scrollLeft = centerFrac * newCanvasW - vpWidth / 2;

        updateZoomButtons();
    }

    function updateZoomButtons() {
        zoomLabel.textContent = ZOOM_LEVELS[currentZoomIdx] + 'x';
        zoomOutBtn.disabled = currentZoomIdx === 0;
        zoomInBtn.disabled = currentZoomIdx === ZOOM_LEVELS.length - 1;
    }

    // === SEARCH ===
    function onSearch(rawQuery) {
        var query = rawQuery.trim().toLowerCase();
        lastQuery = query;
        applySearchHighlight(query);
    }

    function applySearchHighlight(query) {
        if (!query) {
            for (var i = 0; i < renderedRows.length; i++) {
                renderedRows[i].el.classList.remove('tl-dimmed', 'tl-highlight');
            }
            noMatchEl.style.display = 'none';
            return;
        }

        var hasMatch = false;
        var firstMatchEl = null;

        for (var i = 0; i < renderedRows.length; i++) {
            var rr = renderedRows[i];
            var name = rr.item.source_name.toLowerCase();
            if (name.indexOf(query) !== -1) {
                rr.el.classList.remove('tl-dimmed');
                rr.el.classList.add('tl-highlight');
                hasMatch = true;
                if (!firstMatchEl) firstMatchEl = rr.el;
            } else {
                rr.el.classList.remove('tl-highlight');
                rr.el.classList.add('tl-dimmed');
            }
        }

        noMatchEl.style.display = hasMatch ? 'none' : 'inline';

        if (firstMatchEl) {
            firstMatchEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

})();
