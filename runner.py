"""
runner.py — Headless Chrome + @turbowarp/scaffolding .sb3 executor & screenshotter.

Runs any .sb3 in either:
  - vanilla       (compiler=False, fps=30, hq_pen=False)  [Official Scratch 3.0 interpreter]
  - turbowarp     (compiler=True,  fps=60, hq_pen=False)  [TurboWarp JS compiler, 480x360]
  - turbowarp_hq  (compiler=True,  fps=60, hq_pen=True,  width=960, height=720) [Hi-Res Pen]
"""

import http.server
import json
import socketserver
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent

RUNNER_HTML = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
body { margin: 0; padding: 0; background: #000; overflow: hidden; }
#container { width: 480px; height: 360px; }
</style></head>
<body>
<div id="container"></div>
<script src="/vendor/scaffolding/dist/scaffolding-min.js"></script>
<script>
window._ready = false;
window._scaffolding = null;
window.bootProject = async (sb3Url, opts) => {
  const container = document.getElementById('container');
  container.style.width = (opts.width || 480) + 'px';
  container.style.height = (opts.height || 360) + 'px';
  const scaffolding = new Scaffolding.Scaffolding();
  scaffolding.width = 480;
  scaffolding.height = 360;
  scaffolding.resizeMode = 'stretch';
  scaffolding.editableLists = false;
  scaffolding.usePackagedRuntime = false;
  scaffolding.setup();
  scaffolding.appendTo(container);
  window._scaffolding = scaffolding;
  const vm = scaffolding.vm;

  vm.setCompilerOptions({ enabled: !!opts.compiler, warpTimer: false });
  if (opts.fps) vm.setFramerate(opts.fps);
  if (opts.turbo) vm.setTurboMode(true);
  if (scaffolding.renderer && typeof scaffolding.renderer.setUseHighQualityRender === 'function') {
    scaffolding.renderer.setUseHighQualityRender(!!opts.hqPen);
  }

  const resp = await fetch(sb3Url);
  const buf = await resp.arrayBuffer();
  await scaffolding.loadProject(buf);
  if (opts.stageVars) {
    for (const [k, v] of Object.entries(opts.stageVars)) {
      for (const target of vm.runtime.targets) {
        for (const vid in target.variables) {
          if (target.variables[vid].name === k) {
            target.variables[vid].value = v;
          }
        }
      }
    }
  }
  scaffolding.greenFlag();
  window._ready = true;
};

window.readVars = () => {
  const out = {};
  const vm = window._scaffolding.vm;
  for (const target of vm.runtime.targets) {
    for (const vid in target.variables) {
      const v = target.variables[vid];
      if (v.type === '') out[v.name] = v.value;
    }
  }
  return out;
};

window.readList = (name) => {
  const vm = window._scaffolding.vm;
  for (const target of vm.runtime.targets) {
    for (const vid in target.variables) {
      const v = target.variables[vid];
      if (v.type === 'list' && v.name === name) return v.value;
    }
  }
  return null;
};

window.setVar = (name, val) => {
  const vm = window._scaffolding.vm;
  for (const target of vm.runtime.targets) {
    for (const vid in target.variables) {
      const v = target.variables[vid];
      if (v.type === '' && v.name === name) v.value = val;
    }
  }
};

window.isRunning = () => {
  return window._scaffolding.vm.runtime.threads.length > 0;
};
</script>
</body>
</html>
"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        pass


def start_server():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def run_sb3(
    sb3_path,
    mode="turbowarp",
    wait_var=None,
    wait_value=1,
    timeout_sec=30.0,
    settle_sec=0.25,
    screenshot_path=None,
    stage_vars=None,
    canvas_scale=1,
    fixed_wait_sec=None,
):
    """Run an .sb3 inside real @turbowarp/scaffolding and return variables + screenshot."""
    html_file = BASE_DIR / "_runner.html"
    html_file.write_text(RUNNER_HTML, encoding="utf-8")

    rel_sb3 = Path(sb3_path).resolve().relative_to(BASE_DIR.resolve())
    httpd, port = start_server()

    if mode == "vanilla":
        opts = {"compiler": False, "fps": 30, "hqPen": False, "turbo": False, "width": 480 * canvas_scale, "height": 360 * canvas_scale}
    elif mode == "vanilla_turbo":
        opts = {"compiler": False, "fps": 30, "hqPen": False, "turbo": True, "width": 480 * canvas_scale, "height": 360 * canvas_scale}
    elif mode == "turbowarp":
        opts = {"compiler": True, "fps": 60, "hqPen": False, "turbo": False, "width": 480 * canvas_scale, "height": 360 * canvas_scale}
    elif mode == "turbowarp_hq":
        opts = {"compiler": True, "fps": 60, "hqPen": True, "turbo": False, "width": 480 * max(2, canvas_scale), "height": 360 * max(2, canvas_scale)}
    else:
        raise ValueError(f"Unknown mode: {mode}")

    if stage_vars:
        opts["stageVars"] = stage_vars

    errors = []
    try:
        with sync_playwright() as p:
            import shutil
            chrome_bin = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
            launch_kwargs = {
                "args": [
                    "--use-gl=angle",
                    "--use-angle=swiftshader",
                    "--enable-webgl",
                    "--ignore-gpu-blocklist",
                    "--no-sandbox",
                ]
            }
            if chrome_bin:
                launch_kwargs["executable_path"] = chrome_bin
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(viewport={"width": opts["width"] + 20, "height": opts["height"] + 20})
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)

            page.goto(f"http://127.0.0.1:{port}/_runner.html")
            page.evaluate(
                "([url, opts]) => window.bootProject(url, opts)",
                [f"/{rel_sb3.as_posix()}", opts],
            )

            t0 = time.time()
            if fixed_wait_sec is not None:
                time.sleep(fixed_wait_sec)
            elif wait_var is not None:
                while time.time() - t0 < timeout_sec:
                    vs = page.evaluate("() => window.readVars()")
                    if str(vs.get(wait_var)) == str(wait_value) or (
                        isinstance(wait_value, (int, float))
                        and isinstance(vs.get(wait_var), (int, float))
                        and vs.get(wait_var) >= wait_value
                    ):
                        break
                    time.sleep(0.05)
            else:
                # Wait until threads finish or timeout
                time.sleep(0.1)
                while time.time() - t0 < timeout_sec:
                    if not page.evaluate("() => window.isRunning()"):
                        break
                    time.sleep(0.05)

            if settle_sec > 0:
                time.sleep(settle_sec)

            # Force one render frame before screenshot
            page.evaluate("() => window._scaffolding.renderer.draw()")
            time.sleep(0.05)

            vars_out = page.evaluate("() => window.readVars()")
            if screenshot_path:
                Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
                canvas = page.locator("canvas").first
                canvas.screenshot(path=str(screenshot_path))

            browser.close()
    finally:
        httpd.shutdown()

    return {"vars": vars_out, "errors": errors, "elapsed_wall": time.time() - t0}


if __name__ == "__main__":
    import sys
    sb3 = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "turbowarp"
    shot = sys.argv[3] if len(sys.argv) > 3 else None
    res = run_sb3(sb3, mode=mode, screenshot_path=shot)
    print(json.dumps(res, indent=2))
