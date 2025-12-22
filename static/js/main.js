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

// Handle search input focus
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.querySelector('.search-input');
    const searchResults = document.querySelector('.search-results');

    if (searchInput && searchResults) {
        // Hide results when clicking outside
        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
                searchResults.innerHTML = '';
            }
        });

        // Show results on focus if there's content
        searchInput.addEventListener('focus', function() {
            if (this.value.length >= 2) {
                htmx.trigger(this, 'keyup');
            }
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
