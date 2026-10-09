"""Download unmodified TEP V1 originals from Harvard Dataverse and verify checksums.

No API key, third-party mirror, format conversion or simulator modification.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DOI = "doi:10.7910/DVN/6C3JR1"
BASE = "https://dataverse.harvard.edu/api"
FILES = ("TEP_FaultFree_Training.RData", "TEP_FaultFree_Testing.RData",
         "TEP_Faulty_Training.RData", "TEP_Faulty_Testing.RData")


def open_url(url):
    return urlopen(Request(url, headers={"User-Agent": "IronMan-TEP-download/1.0"}), timeout=60)


def metadata():
    url = BASE + "/datasets/:persistentId/versions/1.0?" + urlencode({"persistentId": DOI})
    with open_url(url) as response:
        raw = response.read(10_000_001)
    if len(raw) > 10_000_000:
        raise ValueError("Dataset metadata is too large")
    result = json.loads(raw)
    if result.get("status") != "OK":
        raise ValueError("Dataset metadata request failed")
    version = result["data"]
    if version.get("versionNumber") != 1 or version.get("versionMinorNumber") != 0:
        raise ValueError("Expected published dataset version 1.0")
    license_text = json.dumps({key: version.get(key) for key in
                              ("license", "termsOfUse", "termsOfAccess")}).lower()
    if "cc0" not in license_text and "creativecommons.org/publicdomain/zero/" not in license_text:
        raise ValueError("CC0 reuse terms could not be confirmed; inspect the original dataset terms")
    return version


def checksum(path, algorithm):
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(data_file, folder):
    name = data_file["filename"]
    if name not in FILES:
        raise ValueError("Unexpected original filename")
    algorithm = data_file["checksum"]["type"].lower().replace("-", "")
    if algorithm not in {"md5", "sha1", "sha256", "sha512"}:
        raise ValueError("Unsupported publisher checksum")
    expected = data_file["checksum"]["value"].lower()
    size = data_file["filesize"]
    if not isinstance(size, int) or not 0 < size <= 10_000_000_000:
        raise ValueError("Invalid file size")
    target = folder / name
    url = BASE + "/access/datafile/" + str(int(data_file["id"]))
    if target.exists():
        if target.stat().st_size != size or checksum(target, algorithm) != expected:
            raise ValueError(f"Existing file failed verification: {name}; move it aside before retrying")
        print("Already verified:", name)
    else:
        part = target.with_suffix(target.suffix + ".part")
        print(f"Downloading: {name} ({size / 1024**2:.1f} MiB)", flush=True)
        try:
            with open_url(url) as response, part.open("wb") as stream:
                if "text/html" in response.headers.get("Content-Type", "").lower():
                    raise ValueError("Provider returned a browser verification page instead of the original")
                total = 0
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    total += len(block)
                    if total > size:
                        raise ValueError("Download exceeds publisher file size")
                    stream.write(block)
            if part.stat().st_size != size or checksum(part, algorithm) != expected:
                raise ValueError("Downloaded original failed publisher checksum verification")
            part.replace(target)
        finally:
            part.unlink(missing_ok=True)
    return {"filename": name, "file_id": data_file["id"], "size_bytes": size,
            "publisher_checksum": data_file["checksum"], "sha256": checksum(target, "sha256"),
            "download_url": url, "original_bytes_preserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal-only", action="store_true", help="Download only the two fault-free originals")
    args = parser.parse_args()
    try:
        version = metadata()
        wanted = FILES[:2] if args.normal_only else FILES
        available = {item["dataFile"]["filename"]: item["dataFile"] for item in version["files"]}
        if not all(name in available for name in wanted):
            raise ValueError("Expected TEP originals were not found in publisher metadata")
        folder = ROOT / "data" / "tep" / "raw"
        folder.mkdir(parents=True, exist_ok=True)
        records = [download(available[name], folder) for name in wanted]
        manifest = {"dataset_doi": DOI, "dataset_version": "1.0",
                    "license": version.get("license"), "terms_of_use": version.get("termsOfUse"),
                    "files": records, "connected_to_demo": False}
        (folder.parent / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Original downloads verified. Git LFS upload and simulator integration are separate steps.")
        return 0
    except (URLError, OSError, ValueError, KeyError, TypeError):
        print("Download failed. Check your connection, provider access and the published V1.0 metadata/CC0 terms. No success manifest was generated for this attempt.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
