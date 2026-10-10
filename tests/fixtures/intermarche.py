"""Intermarché: product search and store finder API responses (P3)."""

INTERMARCHE_SEARCH = {
    "produits": [
        {
            "itemId": "41754",
            "produitEan13": "3250390018575",
            "idProduit": "3250390018575",
            "libelle": "Farine de blé T45",
            "marque": "Chabrior",
            "prix": 0.89,
            "prixBarre": 1.05,
            "prixKg": 0.89,
            "unitePrixVente": {"value": "€/Kg"},
            "conditionnement": "1 kg",
            "images": ["https://cdn.intermarche.com/farine.jpg"],
            "stock": 25,
            "dispoCataloguePdv": True,
        },
        {
            "itemId": "41755",
            "produitEan13": "3250390018576",
            "libelle": "Farine de sarrasin bio",
            "marque": "Bio Village",
            "prix": 2.35,
            "stock": 0,
        },
    ],
    "searchResultsMetaData": {"resultNbre": 2},
}

INTERMARCHE_STORES = {
    "resultats": [
        {
            "storeCode": "08012",
            "entityLabel": "Montpellier Près d'Arènes",
            "tradeNameLabel": "Intermarché Super",
            "distance": 2450,
            "addresses": [{"address": "1 avenue de Palavas", "postCode": "34070", "townLabel": "Montpellier"}],
        },
        {
            "storeCode": "06814",
            "entityLabel": "Intermarché Hyper Lattes",
            "tradeNameLabel": "Intermarché Hyper",
            "distance": 900,
            "addresses": [{"address": "Route de Mauguio", "postCode": "34970", "townLabel": "Lattes"}],
        },
    ]
}

# --- DataDome (B41) ----------------------------------------------------------------

# 403 of the API when DataDome wants a captcha (t=fe) or refuses the connection (t=bv)
DATADOME_CAPTCHA_JSON = {
    "url": "https://geo.captcha-delivery.com/captcha/?initialCid=AHrlqAAAAAMA1b2&cid=k6~yFh&t=fe"
    "&referer=https%3A%2F%2Fwww.intermarche.com%2F&s=40281&e=3f8a"
}
DATADOME_BLOCK_JSON = {
    "url": "https://geo.captcha-delivery.com/captcha/?initialCid=AHrlqAAAAAMA1b2&cid=k6~yFh&t=bv"
    "&referer=https%3A%2F%2Fwww.intermarche.com%2F&s=40281&e=3f8a"
}

# Page of the site when DataDome shows its captcha, or its block page, in an iframe
DATADOME_CAPTCHA_PAGE = (
    "<!DOCTYPE html><html><head><title>intermarche.com</title></head><body style='margin:0'>"
    "<iframe src='https://geo.captcha-delivery.com/captcha/?initialCid=x&cid=y&t=fe&s=40281' "
    "width='100%' height='500'></iframe></body></html>"
)
DATADOME_BLOCK_PAGE = (
    "<!DOCTYPE html><html><head><title>intermarche.com</title></head><body style='margin:0'>"
    "<iframe src='https://geo.captcha-delivery.com/captcha/?initialCid=x&cid=y&t=bv&s=40281' "
    "width='100%' height='500'></iframe></body></html>"
)
# Text of DataDome's block page (inside the iframe)
DATADOME_BLOCK_FRAME = (
    "<!DOCTYPE html><html lang='fr'><head><title>DataDome</title></head><body>"
    "<h1>Accès temporairement restreint</h1>"
    "<p>Vous avez été bloqué(e). Un robot est sur le même réseau (IP 92.184.x.x) que vous.</p>"
    "</body></html>"
)
DATADOME_CAPTCHA_FRAME = (
    "<!DOCTYPE html><html lang='fr'><head><title>DataDome CAPTCHA</title></head><body>"
    "<p>Faites glisser vers la droite pour compléter le puzzle</p></body></html>"
)

# Home page of the fake site: identifiers in the cookies like the real one
INTERMARCHE_HOME_PAGE = """<!DOCTYPE html><html><head><title>Intermarché</title><script>
document.cookie = 'itm_device_id=' + encodeURIComponent(JSON.stringify({id: 'dev-1'})) + '; path=/';
document.cookie = 'itm_usid=sess-1; path=/';
%s
</script></head><body>Accueil</body></html>"""

# --- Fingerprint probe (lab/probe.js of the DataDome research, ported) -------------
#
# Loaded as the intermarche.com page of the dedicated Chrome. It hooks fetch()
# in the page (main world), runs the checks known to reveal automation and
# writes the report as JSON in <pre id="report"> (readable from any world). A
# cross-site iframe (https://probe-frame.example/) runs the same checks and
# sends them to the page with postMessage.

FINGERPRINT_PROBE_JS = r"""
(() => {
  const R = { role: window.parent === window ? 'main' : 'frame', checks: {}, variants: {}, hooks: [] };
  const safe = (name, fn) => { try { R.checks[name] = fn(); } catch (e) { R.checks[name] = 'ERR ' + e; } };
  const nativeFetch = window.fetch;
  window.fetch = function (...args) { R.hooks.push('fetch'); return nativeFetch.apply(this, args); };

  safe('userAgent', () => navigator.userAgent);
  safe('webdriver', () => navigator.webdriver);
  safe('languages', () => navigator.languages.join(','));
  safe('vendor', () => navigator.vendor);
  safe('outerGreaterThanInner', () => outerHeight > innerHeight);
  const native = (proto, prop) => {
    const d = Object.getOwnPropertyDescriptor(proto, prop);
    return Boolean(d && d.get && /\{\s*\[native code\]\s*\}/.test(Function.prototype.toString.call(d.get)));
  };
  safe('nativeLanguages', () => native(Navigator.prototype, 'languages'));
  safe('nativeUserAgent', () => native(Navigator.prototype, 'userAgent'));
  safe('nativeVendor', () => native(Navigator.prototype, 'vendor'));
  safe('nativeWebdriver', () => native(Navigator.prototype, 'webdriver'));
  safe('iframeSelf', () => {
    const f = document.createElement('iframe'); f.srcdoc = 'x'; document.body.appendChild(f);
    const ok = f.contentWindow.self === f.contentWindow; f.remove(); return ok;
  });
  // Runtime.enable detection (getter read twice, Proxy traps hit 3 times under Playwright)
  const V = { errName: 0, protoProxy: 0 };
  const e1 = new Error('x');
  Object.defineProperty(e1, 'name', { get() { V.errName++; return 'Error'; } });
  console.debug(e1);
  const handler = { get() { V.protoProxy++; return undefined; }, has() { V.protoProxy++; return false; },
    ownKeys() { V.protoProxy++; return []; }, getOwnPropertyDescriptor() { V.protoProxy++; return undefined; },
    getPrototypeOf() { V.protoProxy++; return null; } };
  console.debug(Object.create(new Proxy({}, handler)));
  R.variants = V;

  const done = (async () => {
    try { R.checks.notifications = (await navigator.permissions.query({ name: 'notifications' })).state; }
    catch (e) { R.checks.notifications = 'ERR ' + e; }
    try {
      const blob = new Blob(['postMessage(navigator.languages.join(","))'], { type: 'text/javascript' });
      const worker = new Worker(URL.createObjectURL(blob));
      R.checks.workerLanguages = await new Promise((ok) => { worker.onmessage = (m) => ok(m.data); });
      worker.terminate();
    } catch (e) { R.checks.workerLanguages = 'ERR ' + e; }
  })();

  if (R.role === 'frame') {
    done.then(() => parent.postMessage({ probeFrame: R }, '*'));
    return;
  }
  const out = () => {
    let pre = document.getElementById('report');
    if (!pre) { pre = document.createElement('pre'); pre.id = 'report'; document.body.appendChild(pre); }
    pre.textContent = JSON.stringify(R);
  };
  window.addEventListener('message', (m) => {
    if (m.data && m.data.probeFrame) { R.frame = m.data.probeFrame; out(); }
  });
  done.then(out);
  setInterval(out, 300);
})();
"""

FINGERPRINT_PAGE = (
    "<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'><title>Intermarché</title></head><body>"
    "<h1>Sonde</h1><iframe src='https://probe-frame.example/' width='300' height='80'></iframe>"
    "<script>" + FINGERPRINT_PROBE_JS + "</script></body></html>"
)
FINGERPRINT_FRAME = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>cadre"
    "<script>" + FINGERPRINT_PROBE_JS + "</script></body></html>"
)
