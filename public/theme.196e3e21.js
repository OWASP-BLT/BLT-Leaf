// Shared theme utilities for BLT-Leaf
// - sets Tailwind config for dark mode
// - applies the saved or preferred theme early to avoid FOUC
// - provides `toggleTheme()` and wires up theme icons/toggles on DOMContentLoaded

window.tailwind = window.tailwind || {};
window.tailwind.config = window.tailwind.config || {};
window.tailwind.config.darkMode = 'class';

(function applyInitialTheme() {
    try {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark') {
            document.documentElement.classList.add('dark');
        } else if (savedTheme === 'light') {
            document.documentElement.classList.remove('dark');
        } else {
            // No explicit saved theme: respect the OS/browser preference.
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
        }
    } catch (e) {
        // Storage unavailable — leave any theme class already set in the <head> as-is.
    }
})();

function updateThemeIcons() {
    const icons = document.querySelectorAll('[data-theme-icon]');
    icons.forEach(icon => {
        const isTextXs = icon.classList.contains('text-xs');
        const base = document.documentElement.classList.contains('dark') ? 'fas fa-sun' : 'fas fa-moon';
        icon.className = base + (isTextXs ? ' text-xs' : '');
    });
}

function toggleTheme() {
    const isDark = document.documentElement.classList.contains('dark');
    if (isDark) {
        document.documentElement.classList.remove('dark');
        try { localStorage.setItem('theme', 'light'); } catch (e) {}
    } else {
        document.documentElement.classList.add('dark');
        try { localStorage.setItem('theme', 'dark'); } catch (e) {}
    }
    updateThemeIcons();
}

document.addEventListener('DOMContentLoaded', function () {
    updateThemeIcons();
    document.querySelectorAll('[data-theme-toggle]')
        .forEach(btn => btn.addEventListener('click', toggleTheme));
});

// Export for other scripts
window.toggleTheme = toggleTheme;
