"""Package the committed project into a deliverable-ordered submission zip.

    python submission/tools/build_submission_zip.py [output.zip]

Top-level folders follow the course deliverables list 1-9. Only files tracked by
git are packaged, so local caches, raw downloads and node_modules never leak in.
The scripts in folders 3 and 4 import each other and resolve paths from the
repository root, so folder 10 also carries the complete repository in its
original, runnable layout.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO.parent / "STATS401_Tashkent_Transit_Final_Submission.zip"
ROOT = "STATS401_Tashkent_Transit_Final_Submission"
SITE_URL = "https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/"
MIRROR_URL = "https://stats401-final-project.saidkamolbahodirov.workers.dev/"
REPO_URL = "https://github.com/Abdullajon1881/stats401-final-project"

CRAWLERS = {"acquire_data.py", "acquire_metro_lines.py", "acquire_temporal_population.py",
            "acquire_urban_dimensions.py", "overpass_client.py"}

FOLDERS = {
    "01_Source_Datasets": "Links, licences and provenance manifests for the raw sources",
    "02_Cleaned_Processed_Datasets": "Audited analytical outputs and the browser-ready data",
    "03_Data_Collection_Crawler_Code": "OSMnx / Overpass / SIAT API / WorldPop acquisition scripts",
    "04_Data_Cleaning_and_Analysis_Code": "Cleaning, routing analysis, web-data build, validators and tests",
    "05_Visualization_Source_Code": "Complete website source: HTML, CSS, D3 and MapLibre JavaScript",
    "06_Published_Website": "Link to the live dashboard",
    "07_Final_Report": "Final report (PDF, Word, Markdown source)",
    "08_Final_Poster": "A0 poster (PDF, preview image, HTML source)",
    "09_Reproduction_Documentation": "README, methods, data dictionary, requirements and rebuild tools",
    "10_Complete_Repository_Runnable": "The whole repository in its original layout, for running the code",
}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if (REPO / line).is_file()]


def destination(path: str) -> str | None:
    """Deliverable folder (with sub-path) for one tracked file, or None."""
    name = Path(path).name
    if path.startswith("submission/source_data/"):
        return f"01_Source_Datasets/{name}"
    if path.startswith("data/") and path.endswith("manifest.json") and path.count("/") == 1:
        return f"01_Source_Datasets/provenance_manifests/{name}"
    if path == "data/display/metro_lines_provenance.json":
        return f"01_Source_Datasets/provenance_manifests/{name}"
    if path.startswith("data/processed/"):
        return f"02_Cleaned_Processed_Datasets/processed/{name}"
    if path.startswith("data/display/"):
        return f"02_Cleaned_Processed_Datasets/display_only/{name}"
    if path.startswith("site/data/"):
        return f"02_Cleaned_Processed_Datasets/web_ready/{name}"
    if path.startswith("scripts/"):
        folder = "03_Data_Collection_Crawler_Code" if name in CRAWLERS else "04_Data_Cleaning_and_Analysis_Code"
        return f"{folder}/{name}"
    if path.startswith("site/"):
        return f"05_Visualization_Source_Code/{path}"
    if path.startswith("submission/report/"):
        return f"07_Final_Report/{name}"
    if path.startswith("submission/screenshots/"):
        return f"07_Final_Report/screenshots/{name}"
    if path.startswith("submission/poster/"):
        return f"08_Final_Poster/{name}"
    if path.startswith("submission/tools/"):
        return f"09_Reproduction_Documentation/rebuild_report_and_poster/{name}"
    if path.startswith("docs/"):
        return f"09_Reproduction_Documentation/docs/{name}"
    if path in ("README.md", "requirements.txt", "LICENSE"):
        return f"09_Reproduction_Documentation/{name}"
    if path == "submission/README.md":
        return "09_Reproduction_Documentation/SUBMISSION_GUIDE.md"
    return None


def start_here() -> str:
    rows = "\n".join(f"| `{k}/` | {v} |" for k, v in FOLDERS.items())
    return f"""# Tashkent Transit & Walkability: STATS 401 final submission

Doniyor Erkinov (de82) · Saidkamolkhon Bakhodirov (sb932)

**Live website:** {SITE_URL}
**Repository:** {REPO_URL}

Folders are numbered to match the course deliverables list:

| Folder | Contents |
|---|---|
{rows}

Quick start:

- **Read the report:** `07_Final_Report/Tashkent_Transit_Walkability_Final_Report.pdf`
- **See the poster:** `08_Final_Poster/Tashkent_Transit_Walkability_Poster_A0.pdf`
- **Open the dashboard:** {SITE_URL}, or serve it locally with
  `python -m http.server 8000 -d site` from inside `10_Complete_Repository_Runnable/`
- **Re-run or validate the analysis:** use `10_Complete_Repository_Runnable/`. The scripts
  in folders 03 and 04 are copies grouped for reading; they import each other
  and expect the repository layout. Steps: `09_Reproduction_Documentation/SUBMISSION_GUIDE.md`.

The raw source files (OpenStreetMap extracts, WorldPop rasters, SIAT tables)
are public but too large to include. `01_Source_Datasets/README.md` links to each one,
and the acquisition scripts in folder 03 download them automatically.
"""


def website_readme() -> str:
    return f"""# Published visualization website / dashboard

Live site: {SITE_URL}
Mirror:    {MIRROR_URL}

It is a static site deployed on Cloudflare Workers. Its complete source is in
`05_Visualization_Source_Code/site/`. To run it locally, from
`10_Complete_Repository_Runnable/`:

    python -m http.server 8000 -d site

then open http://localhost:8000. A server is required because the page loads
JSON data and ES modules.
"""


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    files = tracked_files()
    unplaced = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(f"{ROOT}/00_START_HERE.md", start_here())
        z.writestr(f"{ROOT}/06_Published_Website/README.md", website_readme())
        z.writestr(f"{ROOT}/06_Published_Website/Open_Live_Website.url", f"[InternetShortcut]\nURL={SITE_URL}\n")
        for path in files:
            dest = destination(path)
            if dest:
                z.write(REPO / path, f"{ROOT}/{dest}")
            elif not path.startswith("."):
                unplaced.append(path)
            z.write(REPO / path, f"{ROOT}/10_Complete_Repository_Runnable/{path}")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(files)} tracked files)")
    if unplaced:
        print("only in folder 10:", ", ".join(unplaced))
    return 0


if __name__ == "__main__":
    sys.exit(main())
