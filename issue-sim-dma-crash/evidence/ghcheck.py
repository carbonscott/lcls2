#!/usr/bin/env python3
"""ghcheck.py <owner/repo> <head sha> <issue numbers, comma-separated> <grep regex> <search words>...

Read-only GitHub API check (unauthenticated): for each search phrase, the matching issues and PRs of the repo
(open and closed); for each listed issue/PR, its state, dates, title and the body/comment lines that match the regex.
Prints a provenance header first. Writes nothing to GitHub.
"""
import datetime, json, re, socket, sys, urllib.parse, urllib.request

repo, head, nums, rx = sys.argv[1:5]
words = sys.argv[5:]
print("# host: %s" % socket.gethostname())
print("# date: %s" % datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
print("# commit: %s %s (default-branch head checked against)" % (repo, head))
print("# cmd: ghcheck.py %s" % " ".join(repr(a) if " " in a else a for a in sys.argv[1:]))


def get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "sim-issues-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


for w in words:
    q = "repo:%s %s" % (repo, w)
    d = get("https://api.github.com/search/issues?per_page=20&q=" + urllib.parse.quote(q))
    print("\n== search %r: %d hit(s)" % (q, d.get("total_count", -1)))
    for i in d.get("items", []):
        print("  #%-4d %-6s %-5s %s  %s" % (i["number"], i["state"], "PR" if "pull_request" in i else "issue",
                                          i["created_at"][:10], i["title"][:110]))
for n in [x for x in nums.split(",") if x]:
    i = get("https://api.github.com/repos/%s/issues/%s" % (repo, n))
    print("\n== #%s %s %s, opened %s, closed %s: %s" % (n, "PR" if "pull_request" in i else "issue", i["state"],
                                                        i["created_at"], i.get("closed_at"), i["title"]))
    print("   %s" % i["html_url"])
    texts = [("body", i.get("body") or "")]
    for c in get("https://api.github.com/repos/%s/issues/%s/comments?per_page=100" % (repo, n)):
        texts.append(("comment %s" % c["created_at"], c.get("body") or ""))
    for where, t in texts:
        hits = [l.rstrip() for l in t.splitlines() if re.search(rx, l) and not re.search(r"@\w", l)]  # no shell prompts (user names)
        if hits:
            print("  [%s]" % where)
            for l in hits[:14]:
                print("    " + l[:200])
