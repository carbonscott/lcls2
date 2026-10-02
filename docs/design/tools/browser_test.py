#!/usr/bin/env python3
"""Browser test of the design model viewer (Playwright, Chromium).

Full run (default):
  * Drill test: depth-first from the overview, click every node's box at its
    level, check that the detail title and body[data-focus] show the node,
    recurse into its children, then click "Zoom out" and check that the
    focus is back at the parent (or __root__).
  * Tour test: click "Tour", check each step's title and focused node, click
    "Next" (not after the last step), then "Exit tour".
  * Counts console errors and warnings, page errors, and failed or HTTP-error
    (>= 400) requests to the viewer's own origin.
  Prints:  nodes_visited=V/N tour_steps=S/T console_errors=C
  Exit 0 iff N > 0, T > 0, V == N, S == T and C == 0.

Check one node (for editing tests):
  --check-node ID --expect-title TEXT --expect-prose SUBSTRING
  opens #/node/ID and also reaches the node by clicking down from the
  overview; checks the detail title and that the rendered prose contains
  SUBSTRING (visible text, whitespace-normalized).
  Prints:  check_node id=ID title_ok=<bool> prose_ok=<bool> console_errors=C
  Add --full to run the full test in the same invocation.

Usage:
  python docs/design/tools/browser_test.py --url http://127.0.0.1:8000/
      [--headed] [--screenshot-dir DIR] [--full]
      [--check-node ID --expect-title TEXT --expect-prose SUBSTRING]

Needs the playwright package and a Chromium browser
(python -m playwright install chromium).
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

ROOT = "__root__"
READY_TIMEOUT_MS = 30000
STEP_TIMEOUT_MS = 5000
MAX_PRINTED_PROBLEMS = 15
MAX_DRILL_FAILURES = 8  # stop the drill test early when the viewer is clearly broken


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


class Session:
    """One browser page plus the problems seen on it."""

    def __init__(self, browser, url, screenshot_dir):
        self.url = url
        self.origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
        self.page = browser.new_page(viewport={"width": 1280, "height": 800})
        self.page.set_default_timeout(STEP_TIMEOUT_MS)
        self.console_problems = []
        self.failures = []
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.page.on("console", self._on_console)
        self.page.on("pageerror", lambda exc: self.console_problems.append(f"pageerror: {exc}"))
        self.page.on("requestfailed", self._on_request_failed)
        self.page.on("response", self._on_response)

    def _same_origin(self, url):
        return url.startswith(self.origin + "/") or url == self.origin

    def _on_console(self, msg):
        if msg.type in ("error", "warning"):
            self.console_problems.append(f"console {msg.type}: {msg.text}")

    def _on_request_failed(self, request):
        if self._same_origin(request.url):
            self.console_problems.append(f"request failed: {request.url} ({request.failure})")

    def _on_response(self, response):
        if self._same_origin(response.url) and response.status >= 400:
            self.console_problems.append(f"HTTP {response.status}: {response.url}")

    def fail(self, text):
        self.failures.append(text)

    def open(self, fragment=""):
        """Load the viewer afresh at the given #fragment and wait until it is ready.

        Returns False (and records a failure) if the viewer never becomes ready.
        """
        target = self.url.split("#", 1)[0] + fragment
        try:
            self.page.goto("about:blank")  # so that a hash-only change is a full load
            self.page.goto(target)
            self.page.wait_for_selector("body[data-ready='true']", timeout=READY_TIMEOUT_MS)
            return True
        except PlaywrightError as exc:
            self.fail(f"open {fragment or '(no fragment)'}: the viewer did not become ready: "
                      f"{str(exc).splitlines()[0]}")
            return False

    def focus(self):
        return self.page.evaluate("() => document.body.dataset.focus")

    def wait_focus(self, node_id):
        """Wait until body[data-focus] and #detail-title show node_id."""
        try:
            self.page.wait_for_function(
                """(id) => document.body.dataset.focus === id &&
                       !!document.querySelector('#detail-title') &&
                       document.querySelector('#detail-title').dataset.nodeId === id""",
                arg=node_id, timeout=STEP_TIMEOUT_MS)
            return True
        except PlaywrightError:
            return False

    def click_box(self, node_id):
        self.page.locator(f'#map .node-box[data-node-id="{node_id}"]').click()

    def recover_to(self, node_id):
        fragment = "#/" if node_id == ROOT else f"#/node/{node_id}"
        self.page.evaluate("(h) => { location.hash = h; }", fragment)
        self.wait_focus(node_id)

    def screenshot(self, name):
        if self.screenshot_dir:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(self.screenshot_dir / name))


def load_model(url):
    model_url = urllib.parse.urljoin(url.split("#", 1)[0], "daq-model.json")
    with urllib.request.urlopen(model_url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def children_map(model):
    ids = [n["id"] for n in model.get("nodes", []) if isinstance(n, dict) and "id" in n]
    known = set(ids)
    children = {ROOT: []}
    for n in model.get("nodes", []):
        if not isinstance(n, dict) or "id" not in n:
            continue
        parent = n.get("parent")
        parent = parent if parent in known else ROOT
        children.setdefault(parent, []).append(n["id"])
    return children, ids


# ---------------------------------------------------------------------------
# Full test
# ---------------------------------------------------------------------------

def drill_test(s, model):
    children, ids = children_map(model)
    visited = set()

    def visit(node_id, parent_id):
        if len(s.failures) >= MAX_DRILL_FAILURES:
            return
        try:
            s.click_box(node_id)
        except PlaywrightError as exc:
            s.fail(f"drill: cannot click the box of {node_id} at the level of {parent_id}: {str(exc).splitlines()[0]}")
            s.recover_to(parent_id)
            return
        if s.wait_focus(node_id):
            if node_id not in visited:
                visited.add(node_id)
        else:
            s.fail(f"drill: after clicking {node_id}, focus is {s.focus()!r}")
            s.recover_to(node_id)
        for child in children.get(node_id, []):
            visit(child, node_id)
        try:
            s.page.locator("#zoom-out").click()
        except PlaywrightError as exc:
            s.fail(f"drill: cannot click zoom-out at {node_id}: {str(exc).splitlines()[0]}")
        if not s.wait_focus(parent_id):
            s.fail(f"drill: zoom out from {node_id} should focus {parent_id}, focus is {s.focus()!r}")
            s.recover_to(parent_id)

    if not s.open("#/"):
        return 0, len(ids)
    if not s.wait_focus(ROOT):
        s.fail(f"drill: the overview does not have focus {ROOT}")
    s.screenshot("root.png")
    for top in children.get(ROOT, []):
        visit(top, ROOT)
    if len(s.failures) >= MAX_DRILL_FAILURES:
        s.fail(f"drill: stopped after {MAX_DRILL_FAILURES} failures")
    return len(visited), len(ids)


def tour_test(s, model):
    steps = model.get("tour", {}).get("steps", [])
    passed = 0
    if not s.open("#/"):
        return 0, len(steps)
    try:
        s.page.locator("#tour-start").click()
    except PlaywrightError as exc:
        s.fail(f"tour: cannot click tour-start: {str(exc).splitlines()[0]}")
        return 0, len(steps)
    for k, step in enumerate(steps, 1):
        title = s.page.locator(f'#tour-step-title[data-step-index="{k}"]')
        try:
            title.wait_for(state="visible")
            shown = normalize(title.inner_text())
        except PlaywrightError:
            s.fail(f"tour: step {k} title did not appear")
            shown = None
        ok = shown == normalize(step["title"])
        if shown is not None and not ok:
            s.fail(f"tour: step {k} title is {shown!r}, expected {step['title']!r}")
        if not s.wait_focus(step["node"]):
            s.fail(f"tour: step {k} focus is {s.focus()!r}, expected {step['node']!r}")
            ok = False
        if s.page.locator(f'#map .node-box.is-highlighted[data-node-id="{step["node"]}"]').count() != 1:
            s.fail(f"tour: step {k} does not highlight the box of {step['node']}")
            ok = False
        if ok:
            passed += 1
        if k == 1:
            s.screenshot("tour-step-1.png")
        if k < len(steps):
            try:
                s.page.locator("#tour-next").click()
            except PlaywrightError as exc:
                s.fail(f"tour: cannot click tour-next at step {k}: {str(exc).splitlines()[0]}")
                break
    try:
        s.page.locator("#tour-exit").click()
        s.page.wait_for_function("() => document.body.dataset.mode === 'browse'")
    except PlaywrightError:
        s.fail("tour: tour-exit did not return to browsing")
        passed = min(passed, len(steps) - 1)
    return passed, len(steps)


# ---------------------------------------------------------------------------
# Check one node
# ---------------------------------------------------------------------------

def check_node(s, model, node_id, expect_title, expect_prose):
    nodes = {n["id"]: n for n in model.get("nodes", []) if isinstance(n, dict) and "id" in n}
    title_ok = prose_ok = True

    def check_here(how):
        nonlocal title_ok, prose_ok
        if not s.wait_focus(node_id):
            s.fail(f"check-node ({how}): focus is {s.focus()!r}, expected {node_id!r}")
            title_ok = prose_ok = False
            return
        shown_title = normalize(s.page.locator("#detail-title").inner_text())
        if shown_title != normalize(expect_title):
            s.fail(f"check-node ({how}): title is {shown_title!r}, expected {expect_title!r}")
            title_ok = False
        shown_prose = normalize(s.page.locator("#detail-prose").inner_text())
        if normalize(expect_prose) not in shown_prose:
            s.fail(f"check-node ({how}): prose does not contain {expect_prose!r}")
            prose_ok = False

    # 1. deep link
    if not s.open(f"#/node/{node_id}"):
        return False, False
    check_here("deep link")
    # 2. clicking down from the overview
    path = []
    current = node_id
    while current in nodes and current not in path:
        path.insert(0, current)
        current = nodes[current].get("parent")
    if node_id not in nodes:
        s.fail(f"check-node: {node_id!r} is not a node of the model")
        return False, False
    if not s.open("#/"):
        return False, False
    for step_id in path:
        try:
            s.click_box(step_id)
        except PlaywrightError as exc:
            s.fail(f"check-node (drill): cannot click {step_id}: {str(exc).splitlines()[0]}")
            return False, prose_ok
        s.wait_focus(step_id)
    check_here("drill")
    return title_ok, prose_ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Browser test of the design model viewer.")
    parser.add_argument("--url", required=True, help="viewer URL, e.g. http://127.0.0.1:8000/")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--screenshot-dir", default=None)
    parser.add_argument("--check-node", default=None, metavar="ID")
    parser.add_argument("--expect-title", default=None)
    parser.add_argument("--expect-prose", default=None)
    parser.add_argument("--full", action="store_true", help="with --check-node: also run the full test")
    args = parser.parse_args(argv)
    if args.check_node and (args.expect_title is None or args.expect_prose is None):
        parser.error("--check-node needs --expect-title and --expect-prose")

    url = args.url if "#" in args.url or args.url.endswith("/") or args.url.endswith(".html") else args.url + "/"
    try:
        model = load_model(url)
    except Exception as exc:  # noqa: BLE001 - report any load problem
        print(f"ERROR: cannot fetch daq-model.json next to {url}: {exc}")
        print("nodes_visited=0/0 tour_steps=0/0 console_errors=0")
        return 1

    exit_code = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        try:
            if args.check_node:
                s = Session(browser, url, args.screenshot_dir)
                title_ok, prose_ok = check_node(s, model, args.check_node, args.expect_title, args.expect_prose)
                errors = len(s.console_problems)
                for line in (s.failures + s.console_problems)[:MAX_PRINTED_PROBLEMS]:
                    print(f"PROBLEM: {line}")
                print(f"check_node id={args.check_node} title_ok={str(title_ok).lower()} "
                      f"prose_ok={str(prose_ok).lower()} console_errors={errors}")
                if not (title_ok and prose_ok and errors == 0):
                    exit_code = 1
                s.page.close()
            if not args.check_node or args.full:
                s = Session(browser, url, args.screenshot_dir)
                visited, total = drill_test(s, model)
                passed, steps = tour_test(s, model)
                errors = len(s.console_problems)
                for line in (s.failures + s.console_problems)[:MAX_PRINTED_PROBLEMS]:
                    print(f"PROBLEM: {line}")
                print(f"nodes_visited={visited}/{total} tour_steps={passed}/{steps} console_errors={errors}")
                if not (total > 0 and steps > 0 and visited == total and passed == steps and errors == 0):
                    exit_code = 1
                s.page.close()
        finally:
            browser.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
