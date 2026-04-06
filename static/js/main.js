// Prism - Main JavaScript

// HTMX configuration
document.body.addEventListener('htmx:configRequest', function(event) {
    // Add CSRF token to all HTMX requests
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value
        || document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrfToken) {
        event.detail.headers['X-CSRFToken'] = csrfToken;
    }
});

// Handle search input focus and keyboard navigation
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.querySelector('.search-input');
    const searchResults = document.querySelector('.search-results');

    if (searchInput && searchResults) {
        let focusIndex = -1;

        // Hide results when clicking outside
        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                searchResults.innerHTML = '';
                focusIndex = -1;
            }
        });

        // Show results on focus if there's content
        searchInput.addEventListener('focus', function() {
            if (this.value.length >= 2) {
                htmx.trigger(this, 'keyup');
            }
        });

        // Keyboard navigation for search results
        searchInput.addEventListener('keydown', function(e) {
            const items = searchResults.querySelectorAll('.search-result-item');
            if (!items.length) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                focusIndex = Math.min(focusIndex + 1, items.length - 1);
                updateFocus(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                focusIndex = Math.max(focusIndex - 1, -1);
                updateFocus(items);
            } else if (e.key === 'Enter' && focusIndex >= 0) {
                e.preventDefault();
                items[focusIndex].click();
            } else if (e.key === 'Escape') {
                searchResults.innerHTML = '';
                focusIndex = -1;
            }
        });

        // Reset focus index when new results load
        document.body.addEventListener('htmx:afterSwap', function(e) {
            if (e.detail.target === searchResults) {
                focusIndex = -1;
            }
        });

        function updateFocus(items) {
            items.forEach(function(item, i) {
                if (i === focusIndex) {
                    item.classList.add('focused');
                    item.scrollIntoView({ block: 'nearest' });
                } else {
                    item.classList.remove('focused');
                }
            });
        }
    }

    // Hamburger menu toggle
    const navToggle = document.querySelector('.navbar-toggle');
    const navMenu = document.querySelector('.navbar-nav');
    if (navToggle && navMenu) {
        navToggle.addEventListener('click', function() {
            const isOpen = navMenu.classList.toggle('open');
            navToggle.setAttribute('aria-expanded', isOpen);
        });
    }
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth' });
        }
    });
});
