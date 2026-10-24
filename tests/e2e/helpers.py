"""Helpers for the E2E tests."""

JS_EVAL = """async ([url, name, args]) => {
    const module = await import(url);
    return await module[name](...args);
}"""


def js_eval(page, module_url: str, fn: str, *args):
    """Call the exported function ``fn`` of the ES module ``module_url`` in the page.

    The page must already show PrixMalin: the module is the very instance the app
    uses. Arguments and result must be JSON values.
    Example: ``js_eval(page, "/static/js/core/fmt.js", "euros", 1.5) == "1,50 €"``.
    """
    return page.evaluate(JS_EVAL, [module_url, fn, list(args)])
