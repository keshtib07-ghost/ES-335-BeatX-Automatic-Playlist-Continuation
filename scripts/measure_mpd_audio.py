#!/usr/bin/env python3
"""Measure bass and treble for MPD tracks from a verified audio manifest.

CSV header: spotify_id,audio,scope,source
Use scope "preview" or "full". Audio may be a local path or an HTTPS URL
from a source that permits analysis. Relative paths are relative to the CSV.
Use --audio-dir for a flat directory of recordings named by Spotify ID.
"""

import argparse
from contextlib import closing, contextmanager
import csv
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import numpy as np


SAMPLE_RATE = 44_100
FRAME_SIZE = 8_192
METHOD = "hann-band-power-44100-v1"
TRACK_ID = re.compile(r"[a-zA-Z0-9]{22}")
EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".opus", ".ogg"}
MAX_BYTES = 150 * 1024 * 1024
FREQUENCIES = np.fft.rfftfreq(FRAME_SIZE, 1 / SAMPLE_RATE)
ANALYSIS = (FREQUENCIES >= 20) & (FREQUENCIES < 20_000)
BASS = (FREQUENCIES >= 20) & (FREQUENCIES < 250)
TREBLE = (FREQUENCIES >= 4_000) & (FREQUENCIES < 16_000)
WINDOW = np.hanning(FRAME_SIZE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS audio_inputs (
    spotify_id TEXT PRIMARY KEY,
    audio TEXT NOT NULL,
    scope TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audio_inputs_by_audio ON audio_inputs(audio);
CREATE TABLE IF NOT EXISTS audio_measurements (
    audio TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    seconds REAL,
    sample_rate INTEGER,
    bass_share REAL,
    treble_share REAL,
    PRIMARY KEY (audio, method)
);
"""


class AudioFailure(Exception):
    def __init__(self, status):
        super().__init__(status)
        self.status = status


def manifest_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"spotify_id", "audio", "scope", "source"} <= set(reader.fieldnames or ()):
            raise ValueError("CSV must contain spotify_id,audio,scope,source")
        for row in reader:
            spotify_id, audio, scope, source = (
                (row[key] or "").strip() for key in ("spotify_id", "audio", "scope", "source")
            )
            if not TRACK_ID.fullmatch(spotify_id) or not audio or scope not in {"full", "preview"} or not source:
                raise ValueError(f"Invalid manifest row at line {reader.line_num}")
            if urlsplit(audio).scheme:
                if not urlsplit(audio).scheme == "https" or not urlsplit(audio).hostname:
                    raise ValueError(f"Use an HTTPS URL or a WSL local path at line {reader.line_num}")
            else:
                audio = str((path.parent / audio).resolve())
            yield spotify_id, audio, scope, source


def directory_rows(path, scope):
    for file in sorted(path.iterdir()):
        if file.is_file() and file.suffix.lower() in EXTENSIONS and TRACK_ID.fullmatch(file.stem):
            yield file.stem, str(file.resolve()), scope, "local_audio"


def import_rows(db, rows):
    unmatched = 0
    with db:
        for spotify_id, audio, scope, source in rows:
            if db.execute("SELECT 1 FROM mpd.catalogue WHERE spotify_id=?", (spotify_id,)).fetchone() is None:
                unmatched += 1
                continue
            current = db.execute(
                "SELECT audio, scope, source FROM audio_inputs WHERE spotify_id=?", (spotify_id,)
            ).fetchone()
            if current is not None and current != (audio, scope, source):
                raise ValueError(f"Conflicting audio mapping for {spotify_id}. Use a fresh --output directory for a changed manifest.")
            if current is None:
                db.execute("INSERT INTO audio_inputs VALUES (?, ?, ?, ?)", (spotify_id, audio, scope, source))
    return unmatched


@contextmanager
def audio_file(locator):
    if not locator.startswith("https://"):
        if not Path(locator).is_file():
            raise AudioFailure("missing_file")
        yield locator
        return

    # Download once and share the result across IDs with the same exact URL.
    request = Request(locator, headers={"User-Agent": "BeatX-audio-analysis/1.0"})
    with tempfile.TemporaryDirectory(prefix="beatx-audio-") as temp:
        path = Path(temp) / "audio"
        with urlopen(request, timeout=20) as response, path.open("wb") as stream:
            size = 0
            while chunk := response.read(256 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise AudioFailure("file_too_large")
                stream.write(chunk)
        yield str(path)


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channels", "-of", "json", path],
        capture_output=True, timeout=30,
    )
    try:
        streams = json.loads(result.stdout)["streams"]
        return int(streams[0]["sample_rate"]), int(streams[0]["channels"])
    except (KeyError, IndexError, ValueError, TypeError) as error:
        raise AudioFailure("invalid_audio") from error


def decode_band_power(path, channels):
    bytes_per_frame = 4 * channels
    block_bytes = 32 * FRAME_SIZE * bytes_per_frame
    total_samples = 0
    bands = np.zeros(3, dtype=np.float64)
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:a:0",
        "-ar", str(SAMPLE_RATE), "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1",
    ]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        while data := process.stdout.read(block_bytes):
            samples = np.frombuffer(data, dtype="<f4").reshape(-1, channels)
            total_samples += len(samples)
            if len(samples) % FRAME_SIZE:
                samples = np.pad(samples, ((0, -len(samples) % FRAME_SIZE), (0, 0)))
            frames = samples.reshape(-1, FRAME_SIZE, channels)
            spectrum = np.fft.rfft(frames * WINDOW[None, :, None], axis=1)
            power = np.square(np.abs(spectrum)).sum(axis=(0, 2))
            bands += [power[ANALYSIS].sum(), power[BASS].sum(), power[TREBLE].sum()]
        if process.wait():
            raise AudioFailure("decode_failed")
    if total_samples < SAMPLE_RATE:
        raise AudioFailure("clip_too_short")
    if not np.isfinite(bands).all() or bands[0] <= 0:
        raise AudioFailure("no_signal")
    return total_samples / SAMPLE_RATE, bands[1] / bands[0], bands[2] / bands[0]


def measure(locator):
    with audio_file(locator) as path:
        sample_rate, channels = probe(path)
        if sample_rate < 40_000:
            return "limited_sample_rate", None, sample_rate, None, None
        seconds, bass, treble = decode_band_power(path, channels)
        return "measured", seconds, sample_rate, float(bass), float(treble)


def process_audio(db, jobs):
    interruption = None
    for number, (locator,) in enumerate(jobs, 1):
        try:
            record = measure(locator)
        except HTTPError as error:
            record = (f"http_{error.code}", None, None, None, None)
            if error.code in {429, 503}:
                retry_after = error.headers.get("Retry-After")
                interruption = f"HTTP {error.code}" + (f" | Retry-After: {retry_after}" if retry_after else "")
        except AudioFailure as error:
            record = (error.status, None, None, None, None)
        except (OSError, URLError, subprocess.TimeoutExpired):
            record = ("io_error", None, None, None, None)

        with db:
            db.execute("INSERT OR REPLACE INTO audio_measurements VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (locator, METHOD, *record))
        if number % 100 == 0:
            print(f"Processed {number:,} audio inputs in this run", flush=True)
        if interruption:
            break
    return interruption


def report_and_export(db, output, interruption, unmatched, export_csv):
    from_clause = """
        FROM mpd.catalogue AS c
        LEFT JOIN audio_inputs AS i USING (spotify_id)
        LEFT JOIN audio_measurements AS m ON m.audio=i.audio AND m.method=?
    """
    status = "COALESCE(m.status, CASE WHEN i.audio IS NULL THEN 'no_verified_audio' ELSE 'pending' END)"
    counts = db.execute(f"SELECT {status}, COUNT(*) {from_clause} GROUP BY 1", (METHOD,))
    counts = dict(counts)
    scopes = dict(db.execute(
        f"SELECT i.scope, COUNT(*) {from_clause} WHERE m.status='measured' GROUP BY 1", (METHOD,)
    ))
    total = sum(counts.values())
    covered = counts.get("measured", 0)
    report = {
        "catalogue_tracks": total,
        "measured_tracks": covered,
        "measured_percent": round(100 * covered / total, 6) if total else 0,
        "measured_by_scope": scopes,
        "track_status_counts": counts,
        "unmatched_manifest_rows_this_run": unmatched,
        "method": METHOD,
        "analysis_range_hz": [20, 20_000],
        "bass_range_hz": [20, 250],
        "treble_range_hz": [4_000, 16_000],
        "interruption": interruption,
    }

    if export_csv:
        import gzip
        columns = ("spotify_id", "measurement_status", "scope", "source", "seconds",
                   "source_sample_rate", "bass_share", "treble_share")
        rows = db.execute(
            f"""SELECT c.spotify_id, {status}, i.scope, i.source, m.seconds,
                       m.sample_rate, m.bass_share, m.treble_share
                {from_clause} ORDER BY c.track_index""",
            (METHOD,),
        )
        temporary = output / "bass_treble_tracks.csv.gz.tmp"
        with gzip.open(temporary, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        temporary.replace(output / "bass_treble_tracks.csv.gz")

    temporary = output / "bass_treble_report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output / "bass_treble_report.json")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("runs/million/mpd.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("runs/million/bass-treble"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--audio-dir", type=Path)
    parser.add_argument("--audio-dir-scope", choices=("full", "preview"), default="full")
    parser.add_argument("--limit", type=int, help="Maximum number of distinct audio inputs to process this run")
    parser.add_argument("--expect-tracks", type=int, help="Require this catalogue row count")
    parser.add_argument("--retry-errors", action="store_true", help="Retry previously failed audio inputs")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--export", action="store_true", help="Export all catalogue tracks and measurement statuses")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if not args.report_only and not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        parser.error("Install FFmpeg (ffmpeg and ffprobe) first")

    try:
        source = args.source.resolve(strict=True).as_uri() + "?mode=ro"
        args.output.mkdir(parents=True, exist_ok=True)
        cache_uri = (args.output / "bass_treble.sqlite3").resolve().as_uri()
        with closing(sqlite3.connect(cache_uri, uri=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("ATTACH DATABASE ? AS mpd", (source,))
            if args.expect_tracks is not None:
                tracks = db.execute("SELECT COUNT(*) FROM mpd.catalogue").fetchone()[0]
                if tracks != args.expect_tracks:
                    raise ValueError(f"Expected {args.expect_tracks:,} tracks, found {tracks:,}")
            db.executescript(SCHEMA)
            unmatched = 0
            if args.manifest:
                unmatched += import_rows(db, manifest_rows(args.manifest))
            if args.audio_dir:
                unmatched += import_rows(db, directory_rows(args.audio_dir, args.audio_dir_scope))
            interruption = None
            if not args.report_only:
                # Separate read cursor so the job list is stable while results are committed.
                jobs_sql = """
                    SELECT DISTINCT i.audio
                    FROM audio_inputs i LEFT JOIN audio_measurements m
                        ON m.audio=i.audio AND m.method=?
                    WHERE m.status IS NULL OR m.status IN ('http_429','http_503')
                       OR (? AND m.status != 'measured')
                    ORDER BY i.audio LIMIT ?
                """
                with closing(sqlite3.connect(cache_uri + "?mode=ro", uri=True)) as reader:
                    jobs = reader.execute(jobs_sql, (METHOD, args.retry_errors, args.limit or -1))
                    interruption = process_audio(db, jobs)
            report_and_export(db, args.output, interruption, unmatched, args.export)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
