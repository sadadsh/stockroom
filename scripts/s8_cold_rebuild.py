#!/usr/bin/env python3
"""S8 cold-rebuild metrics harness.

Drives the REAL running app (a live uvicorn server + the real camoufox render tier)
to cold-rebuild the enrichment of every corpus part THROUGH the app's HTTP surface —
the exact `POST /api/enrich/from-url` + SSE-job path the Add-A-Part look-up uses — and
measures the rebuilt depth against the committed corpus record.

Why from-url and not type-an-MPN: the corpus is Mouser-sourced (each record carries its
exact Mouser product URL in provenance.source_url), and the bare-MPN path is LCSC-first
and never scrapes a Mouser product page, so re-scraping each part's own Mouser URL is the
faithful cold reproduction of how the corpus was built.

Honest metric. A live re-scrape of a months-old corpus MUST differ on VOLATILE data
(stock, price, lead time drift daily), so those are compared for PRESENCE/shape only. The
parametric spec table + compliance/procurement fields are STABLE, so those are compared for
coverage (match-or-beat) AND correctness (a value that CONTRADICTS the corpus = a real
defect). Corpus junk (a duplicated-label spec key) is normalized away on BOTH sides so the
rebuild is never penalized for being cleaner than the corpus.

Not a script that bypasses the server: it boots a genuine uvicorn on loopback with the real
per-launch token and the real camoufox fetcher, and every enrich goes over HTTP through the
JobRunner read lane + SSE, i.e. the running app.

Usage:
    .venv/bin/python scripts/s8_cold_rebuild.py --all
    .venv/bin/python scripts/s8_cold_rebuild.py --sample 5
    .venv/bin/python scripts/s8_cold_rebuild.py --parts bq24074rgtt 2n7002
    .venv/bin/python scripts/s8_cold_rebuild.py --all --out scripts/out/run1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "app" / "backend"
sys.path.insert(0, str(BACKEND))

DEFAULT_CORPUS = Path("/mnt/c/Users/Sadad Haidari/stockroom-winverify/libraries/Main/parts")

# ---------------------------------------------------------------------------
# comparison normalization (imported from the backend so keys/values are
# canonicalized EXACTLY as a committed record would be)
# ---------------------------------------------------------------------------
from stockroom.model.spec_hygiene import normalize_spec_key, normalize_spec_value  # noqa: E402

# Volatile fields legitimately drift between the corpus scrape and a live re-scrape; compared
# for presence/shape, never exact value. (stock, price live in `purchase`, not `specs`, so the
# spec table stays stable; these keys guard any that leak into specs.)
_VOLATILE_KEYS = {
    "stock", "in stock", "availability", "price", "unit price", "factory lead-time",
    "factory lead time", "lead time", "lead-time",
    # a transient region-restriction UI notice ("Mouser does not presently sell this product
    # in your region."), not a parametric spec — the old pipeline captured it as a spec; a
    # clean rebuild that omits it is correct, so it is not a depth miss.
    "shipping restrictions",
}

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _norm_key(k: str) -> str:
    return normalize_spec_key(str(k)).strip().lower()


def _norm_val(v) -> str:
    v = normalize_spec_value(v)
    s = str(v).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _numeric(s: str):
    m = _NUM.search(s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def values_compatible(cv: str, rv: str) -> bool:
    """True when the rebuild value does NOT contradict the corpus value. Conservative:
    equal / numeric-equal / one-contains-the-other all pass (a superset like
    'China (Mainland)' vs 'China' is not a contradiction); only a genuinely different
    token/number with no containment is a contradiction (flagged for review)."""
    a, b = _norm_val(cv), _norm_val(rv)
    if a == b:
        return True
    if not a or not b:
        return True  # one side blank -> a coverage question, not a wrong value
    if a in b or b in a:
        return True
    na, nb = _numeric(a), _numeric(b)
    if na is not None and nb is not None and abs(na - nb) < 1e-9:
        return True
    # token-set equality ("smd/smt" vs "smt/smd")
    ta = set(re.split(r"[\s/,]+", a)) - {""}
    tb = set(re.split(r"[\s/,]+", b)) - {""}
    if ta and ta == tb:
        return True
    return False


# ---------------------------------------------------------------------------
# canonical field extraction from a corpus RECORD and a rebuild DTO
# ---------------------------------------------------------------------------
def corpus_fields(rec: dict) -> dict[str, str]:
    """The corpus record's STABLE, comparable fields keyed by normalized-lower spec key.
    The old pipeline dumped everything (package, lifecycle, tariff, country, manufacturer)
    into `specs`, so specs is nearly the whole comparable surface; identity is folded in."""
    out: dict[str, str] = {}
    for k, v in (rec.get("specs") or {}).items():
        nk = _norm_key(k)
        if not nk or nk in _VOLATILE_KEYS:
            continue
        out[nk] = str(normalize_spec_value(v))
    # identity that the corpus also stores structurally
    for field, key in (("mpn", "mpn"), ("manufacturer", "manufacturer"),
                       ("description", "description")):
        val = rec.get(field)
        if val:
            out.setdefault(key, str(val))
    return out


def rebuild_fields(dto: dict) -> dict[str, str]:
    """The rebuild DTO's STABLE fields, keyed the same way, with the first-class procurement
    fields mapped into their record spec-keys so they're credited toward corpus coverage
    (Package/Lifecycle/US Tariff %/Country of Origin land as spec rows on a committed record)."""
    out: dict[str, str] = {}
    for k, s in (dto.get("specs") or {}).items():
        if k == "product_url" or s is None:
            continue
        nk = _norm_key(k)
        if not nk or nk in _VOLATILE_KEYS:
            continue
        out[nk] = str(normalize_spec_value(s.get("value")))

    def sv(name):
        s = dto.get(name)
        return None if s is None else s.get("value")

    for name, key in (("package", "package"), ("lifecycle", "lifecycle"),
                      ("manufacturer", "manufacturer"), ("description", "description"),
                      ("mpn", "mpn")):
        val = sv(name)
        if val not in (None, ""):
            out.setdefault(key, str(normalize_spec_value(val)))
    # tariff_rate + country_of_origin are the first-class fields the DTO currently drops /
    # only-sometimes-surfaces; if a future fix exposes them, credit them here too.
    for name, key in (("tariff_rate", "us tariff %"), ("country_of_origin", "country of origin")):
        val = sv(name)
        if val not in (None, ""):
            out.setdefault(key, str(normalize_spec_value(val)))
    return out


def compare(rec: dict, dto: dict) -> dict:
    cf = corpus_fields(rec)
    rf = rebuild_fields(dto)
    # Fields compared for COVERAGE only, never correctness, because a mismatch there is not a
    # wrong parametric VALUE: `description` is free-text with divergent sources (corpus terse
    # hand/symbol text vs the Mouser page title); `lifecycle` is a manufacturing STATUS that
    # legitimately drifts between the months-old corpus snapshot and a live scrape (Active <->
    # New Product), so the live value is honest, not wrong.
    coverage_only = {"description", "lifecycle"}
    covered, missed, wrong = [], [], []
    for k, cv in cf.items():
        if k in rf:
            if k in coverage_only or values_compatible(cv, rf[k]):
                covered.append(k)
            else:
                wrong.append({"key": k, "corpus": cv, "rebuild": rf[k]})
        else:
            missed.append({"key": k, "corpus": cv})
    extra = sorted(set(rf) - set(cf))

    # non-spec depth: datasheet / pricing / stock presence (volatile values, presence matters)
    def has(name):
        return dto.get(name) not in (None, "", [], {})

    corpus_purchase = (rec.get("purchase") or [{}])[0]
    depth = {
        "datasheet_url": {"corpus": bool((rec.get("datasheet") or {}).get("source_url")
                                          or (rec.get("provenance") or {}).get("source_url")),
                          "rebuild": has("datasheet_url")},
        "price_breaks": {"corpus": len(corpus_purchase.get("price_breaks") or []),
                         "rebuild": len(dto.get("price_breaks") or [])},
        "stock": {"corpus": corpus_purchase.get("stock"),
                  "rebuild": (dto.get("stock") or {}).get("value") if dto.get("stock") else None},
        "package": {"corpus": (rec.get("specs") or {}).get("Package"),
                    "rebuild": (dto.get("package") or {}).get("value") if dto.get("package") else None},
    }
    return {
        "corpus_field_count": len(cf),
        "covered": len(covered),
        "missed": missed,
        "wrong": wrong,
        "extra": extra,
        "extra_count": len(extra),
        "coverage_pct": round(100.0 * len(covered) / len(cf), 1) if cf else 100.0,
        "depth": depth,
    }


# ---------------------------------------------------------------------------
# the real running server
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _build_scratch_library(root: Path):
    from stockroom.store.profile import ProfileStore
    from stockroom.vcs.repo import GitRepo

    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    store = ProfileStore(root, repo)
    profile = store.create("Main")
    profile.library.parts_dir.mkdir(parents=True, exist_ok=True)
    repo.commit("scratch library for the S8 harness", [root])


class LiveServer:
    def __init__(self, scratch_root: Path, token: str = "s8harnesstoken"):
        self.scratch_root = scratch_root
        self.token = token
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self._server = None
        self._thread = None
        self._fetcher = None

    def start(self):
        # isolate machine config so nothing touches the owner's real ~/.config/stockroom
        cfgdir = self.scratch_root / "sr-config"
        os.environ["STOCKROOM_CONFIG_DIR"] = str(cfgdir)
        os.environ["XDG_CONFIG_HOME"] = str(self.scratch_root / "xdg")
        os.environ["APPDATA"] = str(self.scratch_root / "appdata")

        lib_root = self.scratch_root / "libraries"
        _build_scratch_library(lib_root)

        from stockroom.api.context import build_context
        from stockroom.api.app import create_app
        from stockroom.enrich.scrape_adapter import default_rendered_dom_fetcher
        from stockroom.store.machine_config import MachineConfig

        config = MachineConfig(active_profile="Main")
        ctx = build_context(lib_root, kicad_dir=self.scratch_root / "kicad",
                            config=config, token=self.token)
        self._fetcher = default_rendered_dom_fetcher(Path(ctx.enrich_cache_dir) / "rendered")
        ctx.rendered_dom_fetcher = self._fetcher
        app = create_app(ctx)

        import uvicorn

        cfg = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        for _ in range(200):
            if getattr(self._server, "started", False):
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("server did not start")
        return self

    def stop(self):
        if self._fetcher is not None:
            try:
                self._fetcher.close()
            except Exception:
                pass
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)


# ---------------------------------------------------------------------------
# drive one enrich over real HTTP + SSE (exactly what the UI look-up does)
# ---------------------------------------------------------------------------
def enrich_from_url(base: str, token: str, url: str, timeout: float = 120.0) -> dict:
    import httpx

    headers = {"X-Stockroom-Token": token}
    t0 = time.time()
    with httpx.Client(base_url=base, headers=headers, timeout=timeout) as c:
        r = c.post("/api/enrich/from-url", json={"url": url})
        r.raise_for_status()
        job_id = r.json()["job_id"]
        stages: list[dict] = []
        result = None
        error = None
        event = None
        with c.stream("GET", f"/api/jobs/{job_id}/events") as stream:
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(payload) if payload else {}
                    except json.JSONDecodeError:
                        data = {}
                    if event == "progress":
                        stages.append({"t": round(time.time() - t0, 2), **data})
                    elif event == "result":
                        result = data.get("result")
                    elif event == "error":
                        error = data
                    elif event == "done":
                        break
    return {"result": result, "stages": stages, "error": error,
            "elapsed": round(time.time() - t0, 2)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def load_corpus(corpus_dir: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(corpus_dir.glob("*.json")):
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="first N corpus parts")
    ap.add_argument("--parts", nargs="*", default=[], help="specific part ids")
    ap.add_argument("--out", type=Path, default=REPO / "scripts" / "out" / "latest")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between parts (stealth pacing)")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    if not corpus:
        print(f"no corpus parts under {args.corpus}", file=sys.stderr)
        return 2

    if args.parts:
        ids = [p for p in args.parts if p in corpus]
        missing = [p for p in args.parts if p not in corpus]
        if missing:
            print(f"WARN unknown part ids: {missing}", file=sys.stderr)
    elif args.sample:
        ids = list(corpus)[: args.sample]
    else:
        ids = list(corpus)

    args.out.mkdir(parents=True, exist_ok=True)
    scratch = Path(os.environ.get("SCRATCH", "/tmp")) / f"s8-harness-{os.getpid()}"

    print(f"S8 cold rebuild: {len(ids)} parts -> {args.out}")
    server = LiveServer(scratch).start()
    print(f"server up on {server.base} (real camoufox render tier, cold cache)")

    results = []
    try:
        for i, pid in enumerate(ids, 1):
            rec = corpus[pid]
            url = (rec.get("provenance") or {}).get("source_url") or ""
            if not url:
                print(f"[{i}/{len(ids)}] {pid}: SKIP (no provenance url)")
                continue
            run = enrich_from_url(server.base, server.token, url, timeout=args.timeout)
            dto = run["result"]
            row = {"id": pid, "mpn": rec.get("mpn"), "url": url,
                   "elapsed": run["elapsed"], "error": run["error"],
                   "stages": run["stages"]}
            if dto is None:
                row["blocked"] = True
                row["cmp"] = None
                print(f"[{i}/{len(ids)}] {pid}: BLOCKED/empty in {run['elapsed']}s "
                      f"err={run['error']}")
            else:
                cmp = compare(rec, dto)
                row["blocked"] = False
                row["cmp"] = cmp
                row["dto_specs"] = {k: (v or {}).get("value") for k, v in (dto.get("specs") or {}).items()}
                flag = "  WRONG!" if cmp["wrong"] else ""
                print(f"[{i}/{len(ids)}] {pid}: cover {cmp['covered']}/{cmp['corpus_field_count']} "
                      f"({cmp['coverage_pct']}%) missed={len(cmp['missed'])} wrong={len(cmp['wrong'])} "
                      f"extra={cmp['extra_count']} pb={cmp['depth']['price_breaks']['rebuild']} "
                      f"{run['elapsed']}s{flag}")
            results.append(row)
            if args.delay and i < len(ids):
                time.sleep(args.delay)
    finally:
        server.stop()

    (args.out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    _write_report(results, args.out / "report.md")
    print(f"\nwrote {args.out/'results.json'} and {args.out/'report.md'}")
    _print_summary(results)
    return 0


def _write_report(results: list[dict], path: Path):
    lines = ["# S8 cold-rebuild report", ""]
    ok = [r for r in results if not r.get("blocked") and r.get("cmp")]
    blocked = [r for r in results if r.get("blocked")]
    lines.append(f"- parts run: **{len(results)}**  ok: **{len(ok)}**  blocked: **{len(blocked)}**")
    if ok:
        tot_cov = sum(r["cmp"]["covered"] for r in ok)
        tot_field = sum(r["cmp"]["corpus_field_count"] for r in ok)
        tot_wrong = sum(len(r["cmp"]["wrong"]) for r in ok)
        tot_missed = sum(len(r["cmp"]["missed"]) for r in ok)
        tot_extra = sum(r["cmp"]["extra_count"] for r in ok)
        lines.append(f"- aggregate coverage: **{tot_cov}/{tot_field}** "
                     f"({round(100*tot_cov/tot_field,1) if tot_field else 0}%)  "
                     f"wrong-values: **{tot_wrong}**  missed: **{tot_missed}**  extra(beat): **{tot_extra}**")
    lines.append("")
    if blocked:
        lines.append("## Blocked / empty")
        for r in blocked:
            lines.append(f"- `{r['id']}` err={r.get('error')} url={r['url']}")
        lines.append("")
    # wrong values first (the zero-tolerance failures)
    wrongs = [r for r in ok if r["cmp"]["wrong"]]
    if wrongs:
        lines.append("## WRONG VALUES (zero-tolerance — investigate each)")
        for r in wrongs:
            for w in r["cmp"]["wrong"]:
                lines.append(f"- `{r['id']}` **{w['key']}**: corpus=`{w['corpus']}` "
                             f"rebuild=`{w['rebuild']}`")
        lines.append("")
    # missed-field frequency (the depth gaps)
    from collections import Counter
    miss_ctr = Counter()
    for r in ok:
        for m in r["cmp"]["missed"]:
            miss_ctr[m["key"]] += 1
    if miss_ctr:
        lines.append("## Missed corpus fields (by frequency — the depth gaps)")
        for key, n in miss_ctr.most_common():
            lines.append(f"- **{key}** — missed on {n} part(s)")
        lines.append("")
    # per-part table
    lines.append("## Per-part")
    lines.append("| part | cover | % | missed | wrong | extra | pb | stock | ds | s |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if r.get("blocked"):
            lines.append(f"| `{r['id']}` | BLOCKED | | | | | | | | {r['elapsed']} |")
            continue
        c = r["cmp"]
        d = c["depth"]
        lines.append(f"| `{r['id']}` | {c['covered']}/{c['corpus_field_count']} | {c['coverage_pct']} "
                     f"| {len(c['missed'])} | {len(c['wrong'])} | {c['extra_count']} "
                     f"| {d['price_breaks']['rebuild']}/{d['price_breaks']['corpus']} "
                     f"| {d['stock']['rebuild']} | {'Y' if d['datasheet_url']['rebuild'] else '-'} "
                     f"| {r['elapsed']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_summary(results: list[dict]):
    ok = [r for r in results if not r.get("blocked") and r.get("cmp")]
    blocked = [r for r in results if r.get("blocked")]
    tot_wrong = sum(len(r["cmp"]["wrong"]) for r in ok)
    tot_cov = sum(r["cmp"]["covered"] for r in ok)
    tot_field = sum(r["cmp"]["corpus_field_count"] for r in ok)
    beat = sum(1 for r in ok if r["cmp"]["covered"] >= r["cmp"]["corpus_field_count"])
    print("=" * 60)
    print(f"SUMMARY: {len(ok)} ok, {len(blocked)} blocked")
    print(f"  coverage {tot_cov}/{tot_field} "
          f"({round(100*tot_cov/tot_field,1) if tot_field else 0}%)")
    print(f"  parts at match-or-beat: {beat}/{len(ok)}")
    print(f"  WRONG VALUES: {tot_wrong}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
