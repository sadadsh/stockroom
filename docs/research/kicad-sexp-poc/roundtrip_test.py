"""Round-trip fidelity harness: parse -> save (no modification) -> diff vs original."""
import difflib, os, sys, traceback

SCRATCH = "/tmp/claude-1000/-home-sadad/15b0ef37-9c74-41b7-8cb6-3a5f565b2656/scratchpad"
TF = os.path.join(SCRATCH, "testfiles")
OUT = os.path.join(SCRATCH, "rt_out")
os.makedirs(OUT, exist_ok=True)

SCH = os.path.join(TF, "Power_Supply.kicad_sch")      # KiCad 10, version 20260306
SYM = os.path.join(TF, "MySymbols.kicad_sym")          # KiCad 10, version 20251024
MOD = os.path.join(TF, "SOIC_Z157P6X_ONS.kicad_mod")   # KiCad 6 format, 20211014


def diffstat(orig_path, new_path):
    a = open(orig_path, encoding="utf-8").read()
    b = open(new_path, encoding="utf-8").read()
    if a == b:
        return "IDENTICAL (byte-for-byte)"
    al, bl = a.splitlines(), b.splitlines()
    sm = difflib.SequenceMatcher(None, al, bl, autojunk=False)
    removed = added = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return f"DIFFERS: -{removed}/+{added} lines (orig {len(al)} lines, new {len(bl)} lines)"


def run(name, fn):
    print(f"\n### {name}")
    try:
        result = fn()
        print("   ", result)
    except Exception as e:
        print(f"    EXCEPTION: {type(e).__name__}: {e}")
        tb = traceback.format_exc().splitlines()
        print("    " + "\n    ".join(tb[-4:]))


# ---------------- kiutils ----------------
def kiutils_sch():
    from kiutils.schematic import Schematic
    out = os.path.join(OUT, "kiutils.kicad_sch")
    Schematic.from_file(SCH).to_file(out)
    return diffstat(SCH, out)

def kiutils_sym():
    from kiutils.symbol import SymbolLib
    out = os.path.join(OUT, "kiutils.kicad_sym")
    SymbolLib.from_file(SYM).to_file(out)
    return diffstat(SYM, out)

def kiutils_mod():
    from kiutils.footprint import Footprint
    out = os.path.join(OUT, "kiutils.kicad_mod")
    Footprint.from_file(MOD).to_file(out)
    return diffstat(MOD, out)

# ---------------- kicad-skip ----------------
def skip_sch():
    from skip import Schematic
    out = os.path.join(OUT, "skip.kicad_sch")
    s = Schematic(SCH)
    s.write(out)
    return diffstat(SCH, out)

# ---------------- kicad-tools (rjwalters) ----------------
def ktools_sch():
    import kicad_tools
    out = os.path.join(OUT, "ktools.kicad_sch")
    s = kicad_tools.load_schematic(SCH)
    kicad_tools.save_schematic(s, out)
    return diffstat(SCH, out)

def ktools_sexp_sch():
    """kicad_tools raw sexp layer round-trip"""
    from kicad_tools.sexp import parse_file, serialize_sexp
    out = os.path.join(OUT, "ktools_sexp.kicad_sch")
    doc = parse_file(SCH)
    text = serialize_sexp(doc)
    open(out, "w", encoding="utf-8").write(text)
    return diffstat(SCH, out)

def ktools_sexp_sym():
    from kicad_tools.sexp import parse_file, serialize_sexp
    out = os.path.join(OUT, "ktools_sexp.kicad_sym")
    doc = parse_file(SYM)
    text = serialize_sexp(doc)
    open(out, "w", encoding="utf-8").write(text)
    return diffstat(SYM, out)

def ktools_sexp_mod():
    from kicad_tools.sexp import parse_file, serialize_sexp
    out = os.path.join(OUT, "ktools_sexp.kicad_mod")
    doc = parse_file(MOD)
    text = serialize_sexp(doc)
    open(out, "w", encoding="utf-8").write(text)
    return diffstat(MOD, out)

# ---------------- kicadfiles ----------------
def kicadfiles_sch():
    import kicadfiles
    names = [n for n in dir(kicadfiles) if "sch" in n.lower() or "Sch" in n]
    from kicadfiles import KicadSch  # may raise
    out = os.path.join(OUT, "kicadfiles.kicad_sch")
    obj = KicadSch.from_file(SCH)
    obj.save_to_file(out) if hasattr(obj, "save_to_file") else obj.to_file(out)
    return diffstat(SCH, out)

def kicadfiles_sym():
    from kicadfiles import KicadSymbolLib
    out = os.path.join(OUT, "kicadfiles.kicad_sym")
    obj = KicadSymbolLib.from_file(SYM)
    obj.save_to_file(out) if hasattr(obj, "save_to_file") else obj.to_file(out)
    return diffstat(SYM, out)

# ---------------- kicad-sch-api ----------------
def schapi_sch():
    import kicad_sch_api as ksa
    out = os.path.join(OUT, "schapi.kicad_sch")
    sch = ksa.load(SCH) if hasattr(ksa, "load") else ksa.Schematic.load(SCH)
    sch.save(out)
    return diffstat(SCH, out)


if __name__ == "__main__":
    print("== PASS 1: unmodified round-trip ==")
    run("kiutils .kicad_sch (KiCad 10)", kiutils_sch)
    run("kiutils .kicad_sym (KiCad 10)", kiutils_sym)
    run("kiutils .kicad_mod (KiCad 6 fmt)", kiutils_mod)
    run("kicad-skip .kicad_sch (KiCad 10)", skip_sch)
    run("kicad-tools high-level .kicad_sch (KiCad 10)", ktools_sch)
    run("kicad-tools sexp layer .kicad_sch (KiCad 10)", ktools_sexp_sch)
    run("kicad-tools sexp layer .kicad_sym (KiCad 10)", ktools_sexp_sym)
    run("kicad-tools sexp layer .kicad_mod (KiCad 6 fmt)", ktools_sexp_mod)
    run("kicadfiles .kicad_sch (KiCad 10)", kicadfiles_sch)
    run("kicadfiles .kicad_sym (KiCad 10)", kicadfiles_sym)
    run("kicad-sch-api .kicad_sch (KiCad 10)", schapi_sch)
