// Run before the first render (synchronous script of <head>): applies the
// text size and the theme saved on this device, so that the page does not
// change once shown. No module syntax here.
(function () {
    var root = document.documentElement;
    try {
        var scale = Number(localStorage.getItem("prixmalin.textScale"));
        if ([0.9, 1, 1.125, 1.25, 1.4, 1.6].indexOf(scale) >= 0) {
            root.style.setProperty("--ui-scale", String(scale));
        }
        var theme = localStorage.getItem("prixmalin.theme");
        if (theme === "light" || theme === "dark") {
            root.setAttribute("data-theme", theme);
        }
    } catch (e) {
        // Storage unavailable: default size and theme
    }
})();
