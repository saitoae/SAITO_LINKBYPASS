# utils/stealth.py
"""
Playwright stealth: canvas/WebGL/Audio fingerprint spoof,
navigator mask, Chrome runtime injection, permission override.
"""
from fake_useragent import UserAgent

ua = UserAgent()

# Injected into every Playwright page before any navigation
STEALTH_JS = """
// ── webdriver ──────────────────────────────────────────
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// ── plugins (non-zero length) ──────────────────────────
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const arr = [
      { name:'Chrome PDF Plugin',   filename:'internal-pdf-viewer', description:'' },
      { name:'Chrome PDF Viewer',   filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai', description:'' },
      { name:'Native Client',       filename:'internal-nacl-plugin', description:'' },
    ];
    arr.__proto__ = PluginArray.prototype;
    return arr;
  }
});

// ── languages ──────────────────────────────────────────
Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });

// ── platform ───────────────────────────────────────────
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

// ── vendor ─────────────────────────────────────────────
Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });

// ── hardwareConcurrency ────────────────────────────────
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

// ── deviceMemory ───────────────────────────────────────
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// ── Chrome runtime ─────────────────────────────────────
window.chrome = {
  runtime: {
    PlatformOs: { MAC:'mac', WIN:'win', ANDROID:'android', CROS:'cros', LINUX:'linux', OPENBSD:'openbsd' },
    PlatformArch: { ARM:'arm', X86_32:'x86-32', X86_64:'x86-64' },
    PlatformNaclArch: { ARM:'arm', X86_32:'x86-32', X86_64:'x86-64' },
    RequestUpdateCheckStatus: { THROTTLED:'throttled', NO_UPDATE:'no_update', UPDATE_AVAILABLE:'update_available' },
    OnInstalledReason: { INSTALL:'install', UPDATE:'update', CHROME_UPDATE:'chrome_update', SHARED_MODULE_UPDATE:'shared_module_update' },
    OnRestartRequiredReason: { APP_UPDATE:'app_update', OS_UPDATE:'os_update', PERIODIC:'periodic' },
  },
  loadTimes: function(){},
  csi: function(){},
  app: {},
};

// ── Canvas fingerprint noise ───────────────────────────
const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
  const ctx = this.getContext('2d');
  if (ctx) {
    const imgData = ctx.getImageData(0, 0, this.width, this.height);
    for (let i = 0; i < imgData.data.length; i += 128) {
      imgData.data[i] ^= (Math.random() * 2) | 0;
    }
    ctx.putImageData(imgData, 0, 0);
  }
  return origToDataURL.apply(this, arguments);
};

// ── WebGL vendor/renderer spoof ────────────────────────
const getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(param) {
  if (param === 37445) return 'Intel Inc.';
  if (param === 37446) return 'Intel Iris OpenGL Engine';
  return getParam.call(this, param);
};

// ── Permissions API ────────────────────────────────────
const origQuery = navigator.permissions && navigator.permissions.query;
if (origQuery) {
  navigator.permissions.query = (params) =>
    params.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : origQuery.call(navigator.permissions, params);
}

// ── AudioContext fingerprint noise ─────────────────────
const origCreateAnalyser = AudioContext.prototype.createAnalyser;
AudioContext.prototype.createAnalyser = function() {
  const analyser = origCreateAnalyser.call(this);
  const origGetFloatFrequency = analyser.getFloatFrequencyData.bind(analyser);
  analyser.getFloatFrequencyData = function(array) {
    origGetFloatFrequency(array);
    for (let i = 0; i < array.length; i += 100) {
      array[i] += (Math.random() - 0.5) * 0.0001;
    }
  };
  return analyser;
};

// ── Screen dimensions ──────────────────────────────────
Object.defineProperty(screen, 'width',       { get: () => 1920 });
Object.defineProperty(screen, 'height',      { get: () => 1080 });
Object.defineProperty(screen, 'availWidth',  { get: () => 1920 });
Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
Object.defineProperty(screen, 'colorDepth',  { get: () => 24  });

console.log('[stealth] fingerprint masks active');
"""


def stealth_headers(referer: str = "https://www.google.com") -> dict:
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


async def new_stealth_context(playwright, headless: bool = True):
    """Spawn a Playwright browser context with full stealth applied."""
    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-extensions",
            "--window-size=1920,1080",
            "--start-maximized",
            "--lang=en-US",
        ],
    )
    ctx = await browser.new_context(
        user_agent=ua.random,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
        java_script_enabled=True,
        ignore_https_errors=True,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
        },
    )
    await ctx.add_init_script(STEALTH_JS)
    return browser, ctx