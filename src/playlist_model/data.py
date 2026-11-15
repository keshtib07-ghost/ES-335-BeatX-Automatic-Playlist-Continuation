import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


SPOTIFY_ID = re.compile(r"(?:spotify:track:)?([A-Za-z0-9]{22})\Z")
PARTITIONS = ('train', 'validation', 'test')


@dataclass(frozen=True)
class Playlist:
    pid: int
    title: str
    tracks: tuple[int, ...]
    fingerprint: str
    split: str


@dataclass(frozen=True)
class Track:
    recording_id: str
    spotify_id: str
    title: str
    artist: str
    year: int | None
    bpm: float | None


def track_id(text):
    match = SPOTIFY_ID.fullmatch(text or '')
    return match[1] if match else None


def stable_hash(namespace, value):
    return hashlib.sha256(f'{namespace}|{value}'.encode()).digest()


def metadata_rows(path):
    """Load curator-verified recording identities and optional track metadata."""
    rows = {}
    if path is None:
        return rows
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        for row in csv.DictReader(file):
            identifier = track_id(row.get('track_id'))
            recording = row.get('recording_id', '').strip()
            if identifier is None or not recording or identifier in rows:
                raise ValueError(f'Invalid or duplicate metadata row: {row}')
            year = int(row['release_year']) if row.get('release_year', '').strip() else None
            bpm = float(row['bpm']) if row.get('bpm', '').strip() else None
            if year is not None and not 1850 <= year <= 2100:
                raise ValueError(f'Release year out of range: {row}')
            if bpm is not None and not 20 <= bpm <= 350:
                raise ValueError(f'BPM out of range: {row}')
            rows[identifier] = (f'verified:{recording}', year, bpm)
    return rows


def read_dataset(input_path, metadata=None, development_stop=1000):
    root = Path(input_path)
    files = sorted(root.rglob('mpd.slice.*.json')) if root.is_dir() else [root]
    if not files or not all(path.is_file() for path in files):
        raise ValueError('No MPD slice JSON files found')
    metadata = metadata_rows(metadata)
    group_year, group_bpm = {}, {}
    for recording, year, bpm in metadata.values():
        if year:
            group_year[recording] = min(year, group_year.get(recording, year))
        if bpm:
            group_bpm.setdefault(recording, []).append(bpm)

    catalog, aliases, indices, staged, seen = [], {}, {}, [], set()
    stats = Counter()
    forced_groups = set()
    for path in files:
        with path.open(encoding='utf-8') as file:
            data = json.load(file)
        for row in data['playlists']:
            pid = row['pid']
            if type(pid) is not int or pid < 0 or pid in seen:
                raise ValueError(f'Invalid or repeated playlist ID {pid}')
            seen.add(pid)
            title = row['name'] if isinstance(row.get('name'), str) else ''
            unique_ids, memberships = set(), set()
            for raw in row['tracks']:
                stats['raw_track_rows'] += 1
                identifier = track_id(raw.get('track_uri'))
                if identifier is None:
                    stats['invalid_track_rows'] += 1
                    continue
                if identifier in unique_ids:
                    stats['repeat_track_ids_in_playlist'] += 1
                    continue
                unique_ids.add(identifier)
                recording = metadata[identifier][0] if identifier in metadata else f'spotify:{identifier}'
                if recording not in indices:
                    indices[recording] = len(catalog)
                    tempos = sorted(group_bpm.get(recording, []))
                    bpm = sum(tempos) / len(tempos) if tempos and tempos[-1] - tempos[0] <= 3 else None
                    catalog.append(Track(recording, identifier, str(raw.get('track_name') or ''),
                                         str(raw.get('artist_name') or ''), group_year.get(recording), bpm))
                index = indices[recording]
                aliases[identifier] = index
                if index in memberships:
                    stats['alternate_release_rows_merged'] += 1
                memberships.add(index)
            if not memberships:
                stats['empty_playlists_excluded'] += 1
                continue
            key = '\n'.join(sorted(catalog[index].recording_id for index in memberships))
            fingerprint = stable_hash('playlist-recordings-v1', key).hex()
            if pid < development_stop:
                forced_groups.add(fingerprint)
            staged.append((pid, title, tuple(sorted(memberships)), fingerprint))

    playlists = []
    for row in sorted(staged):
        fingerprint = row[-1]
        fraction = int.from_bytes(stable_hash('playlist-split-v1', fingerprint)[:8], 'big') / 2**64
        index = 0 if fraction < .8 else 1 if fraction < .9 else 2
        playlists.append(Playlist(*row, PARTITIONS[0 if fingerprint in forced_groups else index]))
    split_counts = Counter(playlist.split for playlist in playlists)
    if set(split_counts) != set(PARTITIONS):
        raise ValueError('Dataset is too small to form all three partitions')
    stats.update({'source_files': len(files), 'raw_playlists': len(seen), 'clean_playlists': len(playlists),
                  'unique_spotify_ids': len(aliases), 'recordings': len(catalog),
                  'memberships': sum(len(playlist.tracks) for playlist in playlists),
                  'duplicate_playlist_copies': len(playlists) - len({p.fingerprint for p in playlists}),
                  'verified_metadata_ids': len(set(aliases) & set(metadata)),
                  'recordings_with_year': sum(row.year is not None for row in catalog),
                  'recordings_with_bpm': sum(row.bpm is not None for row in catalog)})
    return playlists, catalog, aliases, dict(stats), dict(split_counts)


def playlist_query(playlist, catalog, seed_count=3):
    if len(playlist.tracks) <= seed_count:
        return None
    ordered = sorted(playlist.tracks, key=lambda index: stable_hash(
        'playlist-seeds-v1', f'{playlist.pid}|{catalog[index].recording_id}'))
    return ordered[:seed_count], frozenset(ordered[seed_count:])
