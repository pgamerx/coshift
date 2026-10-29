#!/usr/bin/env python3
"""Try the Baton page with made-up data, no setup needed:  python3 scripts/demo.py
Fills a throwaway board in a temp folder and serves it at http://127.0.0.1:7788 (Ctrl-C to stop)."""
import json, os, sys, tempfile, time

home = tempfile.mkdtemp(prefix="baton-demo.")
os.environ.update(BATON_HOME=home, BATON_USAGE_APP="", CLAUDE_SWITCH_BIN="/nonexistent",
                  CLAUDE_SWITCH_LIVE=os.path.join(home, "none"), CLAUDE_SWITCH_HOME=os.path.join(home, "none"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "board"))
import board  # noqa: E402

now = time.time()
m = lambda minutes: now - minutes * 60  # noqa: E731


def task(i, title, detail, status, owner="", notes=(), session=""):
    return {"id": i, "title": title, "detail": detail, "status": status, "owner": owner, "created_by": "ATLAS",
            "updated": m(3 + i), "session": session,
            "notes": [{"t": m(mins), "by": by, "text": text} for mins, by, text in notes]}


demo = {
    "next_id": 9,
    "usage": {
        "ATLAS": {"five_hour_pct": 62, "weekly_pct": 41, "five_hour_resets": "1h 48m", "weekly_resets": "4d 2h", "at": m(1)},
        "FORGE": {"five_hour_pct": 18, "weekly_pct": 87, "five_hour_resets": "4h 10m", "weekly_resets": "1d 9h", "at": m(1)},
    },
    "sessions": {
        "a1": {"account": "ATLAS", "cwd": "cloud: acme-shop", "last": m(1), "tool": "add_note", "context_pct": 64},
        "f1": {"account": "FORGE", "cwd": "cloud: acme-shop", "last": m(2), "tool": "claim_task", "context_pct": 31},
    },
    "tasks": [
        task(1, "Checkout: add address validation", "Files: src/checkout/*. Done = invalid postcodes rejected, tests green.",
             "claimed", "ATLAS", [(25, "ATLAS", "Schema done; wiring the form next. Branch: feat/checkout-validation"),
                                  (4, "ATLAS", "Form wired, 2 tests left to fix")], "a1"),
        task(2, "Orders list: pagination", "src/orders/List.tsx + API ?page=. Done = 50 per page, URL keeps the page.",
             "claimed", "FORGE", [(6, "FORGE", "API paging done, starting the UI")], "f1"),
        task(3, "Emails: order-shipped template", "templates/shipped.mjml. Done = renders in the preview tool.", "open"),
        task(4, "Fix flaky cart test", "tests/cart.spec.ts fails 1 in 10 runs on CI.", "open"),
        task(5, "Product page: image zoom", "Use the existing Lightbox component. Mobile pinch to zoom.", "open"),
        task(6, "Search: debounce input", "Done = one request per 300 ms of typing.", "done", "FORGE",
             [(90, "FORGE", "done: debounced with useDebounce, added a test")]),
        task(7, "Set up staging deploy", "", "done", "ATLAS", [(140, "ATLAS", "done: preview deploys per branch")]),
        task(8, "Old promo banner", "", "cancelled"),
    ],
    "guidance": [
        {"id": 1, "t": m(300), "to": "all", "text": "Use pnpm, not npm. Run the tests before marking a task done.",
         "active": True, "read_by": ["ATLAS", "FORGE"]},
        {"id": 2, "t": m(200), "to": "FORGE", "text": "Weekly limit is high: keep tasks small, no database migrations.",
         "active": True, "read_by": ["FORGE"]},
    ],
    "messages": [{"t": m(12), "to": "ATLAS", "text": "After checkout, look at the orders bug Priya reported.",
                  "read_by": ["ATLAS"]}],
    "contexts": {"ATLAS": [{"t": m(180), "session": "a0", "text":
        "GOAL: ship checkout v2 this week.\nDONE: payment step, staging deploys.\nSTATE: on feat/checkout-validation, "
        "3 commits ahead of main.\nNEXT: finish address validation (#1), then the orders bug.\nGOTCHAS: the postcode API "
        "rate-limits at 10/s in staging."}]},
}
with open(os.path.join(home, "board.json"), "w") as f:
    json.dump(demo, f)

port = int(sys.argv[1]) if len(sys.argv) > 1 else 7788
print(f"Demo board at http://127.0.0.1:{port}  (data in {home}; Ctrl-C to stop)")
board.web(port)
