"""Downloads the DVSA anonymised MOT data (Great Britain, 2005 onward) and keeps only motorcycles.

Each year has a results file (one row per test) and an items file (one row per defect or advisory).
Motorcycles are test classes 1 and 2. For each year we stream or download the file, keep the
motorcycle rows, write them gzipped to data/mot/moto/, and delete the original, so the 60+ GB of
source files never sit on disk at once. Re-runs skip years already done.

Source: DVSA / DfT, Open Government Licence v3.0.
Run:  SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())') python3 tools/mot_download.py [years...]
"""
import gzip, io, os, subprocess, sys, time, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "mot", "moto")
TMP = os.path.join(ROOT, "data", "mot", "raw")
DFT = "https://data.dft.gov.uk/anonymised-mot-test/test_data/"
S3 = "https://edh-dvsa-data-gov-uk-files-prod.s3.eu-west-1.amazonaws.com/"
MOTO = {"1", "2"}


def sources(year):
    if year <= 2016:
        return DFT + f"test_result_{year}.txt.gz", DFT + f"test_item_{year}.txt.gz"
    if year <= 2023:
        return DFT + f"dft_test_result_{year}.zip", DFT + f"dft_test_item_{year}.zip"
    return S3 + f"dft_test_result_extracts_{year}.zip", S3 + f"dft_test_item_extracts_{year}.zip"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def fetch(url, dest, tries=5):
    """Download to dest with resume. Returns dest."""
    if dest.endswith(".zip") and os.path.exists(dest):
        try:
            zipfile.ZipFile(dest).close()   # complete zip already here from an earlier run
            return dest
        except zipfile.BadZipFile:
            pass
    for i in range(tries):
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        req = urllib.request.Request(url, headers={"User-Agent": "moto-repair-log-mot/1.0",
                                                   **({"Range": f"bytes={have}-"} if have else {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                mode = "ab" if have and r.status == 206 else "wb"
                with open(dest, mode) as f:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
            return dest
        except Exception as ex:
            log("  retry", i + 1, url.rsplit("/", 1)[-1], ex)
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"failed {url}")


def text_streams(path):
    """Yield text line iterators for every data file in a .gz or .zip."""
    if path.endswith(".gz"):
        yield io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace", newline="")
    else:
        # some DfT zips use Deflate64, which Python's zipfile cannot read; macOS unzip can.
        # __MACOSX/._* entries are Finder metadata, not data.
        z = zipfile.ZipFile(path)
        for name in sorted(z.namelist()):
            if name.endswith("/") or name.startswith("__MACOSX") or "/._" in name or name.startswith("._") \
                    or not name.lower().endswith((".csv", ".txt")):
                continue
            proc = subprocess.Popen(["unzip", "-p", path, name], stdout=subprocess.PIPE)
            yield io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline="")
            proc.stdout.close()
            proc.wait()


def split_header(line):
    delim = "|" if line.count("|") >= line.count(",") else ","
    return delim, [c.strip().strip('"').lower() for c in line.rstrip("\r\n").split(delim)]


def filter_results(path, out_path):
    ids, kept, seen, header = set(), 0, 0, None
    with gzip.open(out_path + ".part", "wt", encoding="utf-8") as out:
        for f in text_streams(path):
            first = f.readline()
            delim, cols = split_header(first)
            ci, ti = cols.index("test_class_id"), cols.index("test_id")
            if header is None:
                header = cols
                out.write("|".join(cols) + "\n")
            elif cols != header:
                log("  WARNING header differs in part of", os.path.basename(path), cols)
            for line in f:
                seen += 1
                p = line.rstrip("\r\n").split(delim)
                if len(p) > ci and p[ci].strip('"') in MOTO:
                    ids.add(p[ti].strip('"'))
                    out.write("|".join(x.strip('"') for x in p) + "\n")
                    kept += 1
    os.replace(out_path + ".part", out_path)
    return ids, seen, kept


def filter_items(path, out_path, ids):
    kept, seen, header = 0, 0, None
    with gzip.open(out_path + ".part", "wt", encoding="utf-8") as out:
        for f in text_streams(path):
            delim, cols = split_header(f.readline())
            ti = cols.index("test_id")
            if header is None:
                header = cols
                out.write("|".join(cols) + "\n")
            for line in f:
                seen += 1
                p = line.rstrip("\r\n").split(delim)
                if len(p) > ti and p[ti].strip('"') in ids:
                    out.write("|".join(x.strip('"') for x in p) + "\n")
                    kept += 1
    os.replace(out_path + ".part", out_path)
    return seen, kept


def ids_from(out_path):
    ids = set()
    with gzip.open(out_path, "rt", encoding="utf-8") as f:
        cols = f.readline().rstrip("\n").split("|")
        ti = cols.index("test_id")
        for line in f:
            ids.add(line.split("|", ti + 1)[ti])
    return ids


def do_year(year):
    r_url, i_url = sources(year)
    r_out = os.path.join(OUT, f"test_result_{year}.csv.gz")
    i_out = os.path.join(OUT, f"test_item_{year}.csv.gz")
    if os.path.exists(r_out) and os.path.exists(i_out):
        log(year, "already done")
        return
    if os.path.exists(r_out):
        ids = ids_from(r_out)
    else:
        src = fetch(r_url, os.path.join(TMP, r_url.rsplit("/", 1)[-1]))
        log(year, "results downloaded", f"{os.path.getsize(src) / 1e9:.2f} GB, filtering")
        ids, seen, kept = filter_results(src, r_out)
        os.remove(src)
        log(year, f"results: {kept:,} motorcycle tests of {seen:,}")
    src = fetch(i_url, os.path.join(TMP, i_url.rsplit("/", 1)[-1]))
    log(year, "items downloaded", f"{os.path.getsize(src) / 1e9:.2f} GB, filtering")
    seen, kept = filter_items(src, i_out, ids)
    os.remove(src)
    log(year, f"items: {kept:,} motorcycle defects/advisories of {seen:,}")


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    years = [int(y) for y in sys.argv[1:]] or list(range(2025, 2004, -1))
    for y in years:
        try:
            do_year(y)
        except Exception as ex:
            log(y, "FAILED", ex)
    log("done")


if __name__ == "__main__":
    main()
