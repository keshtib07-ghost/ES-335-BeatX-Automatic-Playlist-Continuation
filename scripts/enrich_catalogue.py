"""Join local Spotify, MusicBrainz and AcousticBrainz data to every staged MPD track."""

import argparse
import json
import sqlite3
import subprocess
import tarfile
from contextlib import closing, contextmanager
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, urlsplit

from scripts.join_spotify_snapshot import (DATABASE as SPOTIFY_DATABASE, TRACK_ID, attach, catalogue_date, join_snapshot,
                                   positive_bpm)
from playlist_model.profile_sources import (ACOUSTICBRAINZ, CREDIT_DURATION_TOLERANCE_MS, VERSION_WORDS,
                                            MetadataClient, MetadataUnavailable, acoustic_fields, search_name,
                                            valid_mbid)


OUTPUT_DB = 'catalogue_enrichment.sqlite3'
OUTPUT_REPORT = 'catalogue_enrichment_report.json'


def editions(title, extra=''):
    return '|'.join(sorted(set(VERSION_WORDS.findall(search_name(f'{title} {extra}')))))


def insert_batches(db, statement, rows):
    rows = iter(rows)
    while batch := list(islice(rows, 10_000)):
        db.executemany(statement, batch)


def catalogue_keys(db):
    db.execute('CREATE TEMP TABLE keys (spotify_id TEXT PRIMARY KEY, title TEXT, artist TEXT, edition TEXT, ms INTEGER)')
    insert_batches(db, 'INSERT INTO keys VALUES (?, ?, ?, ?, ?)',
                   ((identifier, search_name(title), search_name(artist), editions(title, album), length)
                    for identifier, title, artist, album, length in db.execute('''
                        SELECT spotify_id, track_name, artist_name, album_name, duration_ms FROM mpd.catalogue
                    ''')))
    db.execute('CREATE INDEX keys_metadata ON keys (title, artist, edition, ms)')


@contextmanager
def archive_members(path):
    if path.suffix != '.zst':
        with tarfile.open(path, 'r|*') as archive:
            yield archive
        return

    # Python 3.11 and 3.12 tarfile need an external zstd decoder.
    with subprocess.Popen(['zstd', '-dc', '--', str(path)], stdout=subprocess.PIPE) as decoder:
        try:
            with tarfile.open(fileobj=decoder.stdout, mode='r|') as archive:
                yield archive
            # Read through the end of the compressed stream to check for decoder errors.
            while decoder.stdout.read(1 << 20):
                pass
            if decoder.wait() != 0:
                raise ValueError(f'Could not decompress {path}')
        finally:
            if decoder.poll() is None:
                decoder.terminate()


def musicbrainz_entities(path, entity):
    with archive_members(path) as archive:
        for member in archive:
            if member.isfile() and member.name.rsplit('/', 1)[-1] == entity:
                with archive.extractfile(member) as rows:
                    for row in rows:
                        if row.strip():
                            yield json.loads(row)
                return
    raise ValueError(f'Expected {entity} JSON lines in {path}')


def spotify_links(record):
    for relation in record.get('relations', []):
        url = urlsplit((relation.get('url') or {}).get('resource', ''))
        if url.hostname == 'open.spotify.com':
            prefix, separator, identifier = url.path.rpartition('/')
            if separator and prefix.endswith('/track') and TRACK_ID.fullmatch(identifier):
                yield identifier


def recording_candidates(db, record, release_title='', release_date=None):
    identifier = record.get('id')
    if not valid_mbid(identifier) or record.get('video'):
        return
    length = record.get('length')
    title = record.get('title') or ''
    date = catalogue_date(record.get('first-release-date')) or catalogue_date(release_date)
    for spotify_id in set(spotify_links(record)):
        if db.execute('SELECT 1 FROM keys WHERE spotify_id=?', (spotify_id,)).fetchone():
            yield spotify_id, identifier, 1, date

    credits = record.get('artist-credit') or []
    if not credits or not title or type(length) is not int or length <= 0:
        return
    first = credits[0]
    primary_names = {search_name(first.get('name')), search_name((first.get('artist') or {}).get('name'))}
    credit = ''.join((item.get('name') or '') + (item.get('joinphrase') or '') for item in credits)
    artists = (primary_names | {search_name(credit)}) - {''}
    edition = editions(title, f'{record.get("disambiguation") or ""} {release_title}')
    for artist in artists:
        for (spotify_id,) in db.execute('''
            SELECT spotify_id FROM keys WHERE title=? AND artist=? AND edition=? AND ms BETWEEN ? AND ?
        ''', (search_name(title), artist, edition, length - CREDIT_DURATION_TOLERANCE_MS,
              length + CREDIT_DURATION_TOLERANCE_MS)):
            yield spotify_id, identifier, 0, date


def musicbrainz_candidates(db, recordings, releases):
    for record in musicbrainz_entities(recordings, 'recording'):
        yield from recording_candidates(db, record)
    if releases is not None:
        for release in musicbrainz_entities(releases, 'release'):
            for medium in release.get('media') or []:
                for track in medium.get('tracks') or []:
                    record = track.get('recording')
                    if record:
                        # Track-level duration and credits identify the edition in this release.
                        record = {**record, 'length': track.get('length') or record.get('length'),
                                  'artist-credit': record.get('artist-credit') or track.get('artist-credit')}
                        yield from recording_candidates(db, record, release.get('title') or '', release.get('date'))


def match_musicbrainz(db, recordings, releases):
    db.execute('CREATE TEMP TABLE candidates (spotify_id TEXT, mbid TEXT, exact_id INTEGER, release_date TEXT)')
    print('Matching MusicBrainz Spotify links and recording metadata', flush=True)
    insert_batches(db, 'INSERT INTO candidates VALUES (?, ?, ?, ?)', musicbrainz_candidates(db, recordings, releases))
    db.executescript('''
        CREATE INDEX candidate_id ON candidates (spotify_id, exact_id);
        CREATE TEMP TABLE mb_matches AS
        WITH preferred AS (
            SELECT spotify_id, MAX(exact_id) AS exact_id FROM candidates GROUP BY spotify_id
        )
        SELECT c.spotify_id, p.exact_id, COUNT(DISTINCT c.mbid) AS candidates,
               CASE WHEN COUNT(DISTINCT c.mbid)=1 THEN MIN(c.mbid) END AS mbid
        FROM preferred AS p JOIN candidates AS c USING (spotify_id, exact_id)
        GROUP BY c.spotify_id;
        CREATE UNIQUE INDEX mb_spotify ON mb_matches (spotify_id);
        CREATE TEMP TABLE mb_dates AS
        SELECT c.mbid, MIN(c.release_date) AS release_date
        FROM candidates AS c WHERE c.release_date IS NOT NULL GROUP BY c.mbid;
        CREATE UNIQUE INDEX mb_date_id ON mb_dates (mbid);
    ''')


def spotify_parquet(db, path):
    db.execute('CREATE TEMP TABLE spotify_extra (spotify_id TEXT PRIMARY KEY, bpm REAL, method TEXT)')
    if path is None:
        return
    try:
        import pyarrow.parquet as parquet
    except ImportError as error:
        raise ValueError('Install pyarrow in the virtual environment to use --spotify-parquet.') from error

    db.execute('CREATE TEMP TABLE extra (spotify_id TEXT, title TEXT, artist TEXT, edition TEXT, ms INTEGER, bpm REAL)')
    columns = ('track_id', 'track_name', 'artists', 'album_name', 'duration_ms', 'tempo')
    source = parquet.ParquetFile(path)
    for batch in source.iter_batches(columns=list(columns)):
        db.executemany('INSERT INTO extra VALUES (?, ?, ?, ?, ?, ?)',
                       ((identifier, search_name(title), search_name(artist), editions(title, album), length, bpm)
                        for identifier, title, artist, album, length, tempo in zip(
                            *(column.to_pylist() for column in batch.columns))
                        if identifier and TRACK_ID.fullmatch(identifier) and (bpm := positive_bpm(tempo)) is not None))
    print('Matching the additional Spotify snapshot by ID and track metadata', flush=True)
    db.execute('CREATE INDEX extra_by_id ON extra (spotify_id)')
    db.execute('''
        INSERT INTO spotify_extra
        SELECT e.spotify_id, MIN(e.bpm), 'spotify_parquet_id'
        FROM extra AS e JOIN keys AS k USING (spotify_id)
        GROUP BY e.spotify_id HAVING COUNT(DISTINCT e.bpm)=1
    ''')
    db.execute('''
        INSERT INTO spotify_extra
        SELECT k.spotify_id, MIN(e.bpm), 'spotify_parquet_metadata'
        FROM extra AS e JOIN keys AS k ON k.title=e.title AND k.artist=e.artist AND k.edition=e.edition
        AND k.ms BETWEEN e.ms-? AND e.ms+?
        WHERE k.title<>'' AND k.artist<>''
          AND NOT EXISTS (SELECT 1 FROM spotify.spotify_tracks AS s WHERE s.spotify_id=k.spotify_id AND s.bpm IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM extra AS original WHERE original.spotify_id=k.spotify_id)
        GROUP BY k.spotify_id
        HAVING COUNT(DISTINCT e.spotify_id)=1 AND COUNT(DISTINCT e.bpm)=1
    ''', (CREDIT_DURATION_TOLERANCE_MS, CREDIT_DURATION_TOLERANCE_MS))
    db.execute('DROP TABLE extra')


def save_audio(db, identifier, payload):
    fields = acoustic_fields(payload)
    db.execute('INSERT OR IGNORE INTO audio VALUES (?, ?, ?, ?)',
               (identifier, fields['bpm'], fields['bass_share'], fields['treble_share']))


def collect_audio(db, archives, online_limit, contact, cache):
    db.execute('CREATE TEMP TABLE audio (mbid TEXT PRIMARY KEY, bpm REAL, bass_share REAL, treble_share REAL)')
    db.execute('CREATE TEMP TABLE wanted AS SELECT DISTINCT mbid FROM mb_matches WHERE mbid IS NOT NULL')
    db.execute('CREATE UNIQUE INDEX wanted_mbid ON wanted (mbid)')
    for path in archives:
        print(f'Reading AcousticBrainz {path.name}', flush=True)
        with archive_members(path) as archive:
            for member in archive:
                name = member.name.rsplit('/', 1)[-1]
                if member.isfile() and name.endswith('-0.json'):
                    identifier = name[:-7]
                    if db.execute('SELECT 1 FROM wanted WHERE mbid=?', (identifier,)).fetchone():
                        with archive.extractfile(member) as handle:
                            save_audio(db, identifier, json.load(handle))
    checked = 0
    interruption = None
    db.execute('ATTACH DATABASE ? AS audio_web', (str(cache),))
    db.execute('CREATE TABLE IF NOT EXISTS audio_web.lookups (mbid TEXT PRIMARY KEY, document TEXT)')
    db.commit()
    if online_limit:
        client = MetadataClient(contact)
        while checked < online_limit:
            batch = [row[0] for row in db.execute('''
                SELECT w.mbid FROM wanted AS w LEFT JOIN audio AS a USING (mbid)
                LEFT JOIN audio_web.lookups AS c USING (mbid)
                WHERE a.mbid IS NULL AND c.mbid IS NULL ORDER BY w.mbid LIMIT ?
            ''', (min(25, online_limit - checked),))]
            if not batch:
                break
            params = urlencode({'recording_ids': ';'.join(batch)})
            try:
                response = client.get(f'{ACOUSTICBRAINZ}low-level?{params}')
                if not isinstance(response, dict) or 'error' in response:
                    raise MetadataUnavailable('AcousticBrainz returned an unexpected bulk response')
            except MetadataUnavailable as error:
                interruption = str(error)
                break
            rows = []
            for identifier in batch:
                payload = (response.get(identifier) or {}).get('0')
                rows.append((identifier, json.dumps(acoustic_fields(payload)) if payload else None))
            with db:
                db.executemany('INSERT OR IGNORE INTO audio_web.lookups VALUES (?, ?)', rows)
            checked += len(batch)
    db.execute('''
        INSERT OR IGNORE INTO audio
        SELECT w.mbid, json_extract(c.document, '$.bpm'), json_extract(c.document, '$.bass_share'),
               json_extract(c.document, '$.treble_share')
        FROM wanted AS w JOIN audio_web.lookups AS c USING (mbid) WHERE c.document IS NOT NULL
    ''')
    return checked, interruption


def compile_profiles(db):
    db.executescript('''
        CREATE TABLE profiles (
            spotify_id TEXT PRIMARY KEY, recording_mbid TEXT, recording_match TEXT,
            spotify_catalogue_release_date TEXT, musicbrainz_release_date TEXT,
            bpm REAL, bpm_source TEXT, bass_share REAL, treble_share REAL
        ) WITHOUT ROWID;
        INSERT INTO profiles
        SELECT k.spotify_id, m.mbid,
               CASE WHEN m.candidates>1 THEN 'ambiguous'
                    WHEN m.exact_id=1 THEN 'spotify_link'
                    WHEN m.mbid IS NOT NULL THEN 'name_artist_duration'
                    ELSE 'unmatched' END,
               s.catalogue_release_date, d.release_date,
               COALESCE(s.bpm, CASE WHEN x.method='spotify_parquet_id' THEN x.bpm END, a.bpm, x.bpm),
               CASE WHEN s.bpm IS NOT NULL THEN 'spotify_csv_id'
                    WHEN x.method='spotify_parquet_id' THEN x.method
                    WHEN a.bpm IS NOT NULL THEN 'acousticbrainz'
                    ELSE x.method END,
               a.bass_share, a.treble_share
        FROM keys AS k
        LEFT JOIN spotify.spotify_tracks AS s USING (spotify_id)
        LEFT JOIN spotify_extra AS x USING (spotify_id)
        LEFT JOIN mb_matches AS m USING (spotify_id)
        LEFT JOIN mb_dates AS d ON d.mbid=m.mbid
        LEFT JOIN audio AS a ON a.mbid=m.mbid;
    ''')
    total, dates, original_dates, bpms, bass, treble, complete = db.execute('''
        SELECT COUNT(*), COUNT(spotify_catalogue_release_date), COUNT(musicbrainz_release_date),
               COUNT(bpm), COUNT(bass_share), COUNT(treble_share),
               COUNT(CASE WHEN COALESCE(musicbrainz_release_date,spotify_catalogue_release_date) IS NOT NULL
                          AND bpm IS NOT NULL AND bass_share IS NOT NULL AND treble_share IS NOT NULL THEN 1 END)
        FROM profiles
    ''').fetchone()
    return {
        'tracks': total, 'spotify_catalogue_release_dates': dates, 'musicbrainz_release_dates': original_dates,
        'bpm': bpms, 'bass': bass, 'treble': treble, 'all_four_fields': complete,
        'all_four_percent': round(100 * complete / total, 4),
        'musicbrainz_matches': dict(db.execute('SELECT recording_match, COUNT(*) FROM profiles GROUP BY recording_match')),
        'bpm_sources': dict(db.execute('SELECT bpm_source, COUNT(*) FROM profiles WHERE bpm_source IS NOT NULL GROUP BY bpm_source')),
    }


def run(args):
    if args.acoustic_online_limit < 0 or (args.acoustic_online_limit and not args.contact):
        raise ValueError('Provide a nonnegative AcousticBrainz web lookup limit and a contact for online use.')
    for path in (args.source, args.spotify_csv, args.musicbrainz, args.musicbrainz_releases,
                 args.spotify_parquet, *args.acoustic_archive):
        if path is not None and not path.is_file():
            raise ValueError(f'Input not found: {path}')
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.catalogue-enrichment-', dir=args.output) as temporary:
        work = Path(temporary)
        spotify_report = join_snapshot(args.spotify_csv, args.source, work)
        with closing(sqlite3.connect(work / OUTPUT_DB, uri=True)) as db:
            attach(db, 'mpd', args.source)
            attach(db, 'spotify', work / SPOTIFY_DATABASE)
            catalogue_keys(db)
            spotify_parquet(db, args.spotify_parquet)
            match_musicbrainz(db, args.musicbrainz, args.musicbrainz_releases)
            checked, interruption = collect_audio(db, args.acoustic_archive, args.acoustic_online_limit, args.contact,
                                                  args.output.resolve() / 'acoustic_web_cache.sqlite3')
            report = {
                'mpd_archive_signature': spotify_report['mpd_archive_signature'],
                'mpd_committed_slices': spotify_report['mpd_committed_slices'],
                'duration_tolerance_ms': CREDIT_DURATION_TOLERANCE_MS,
                'spotify_csv_exact_matches': spotify_report['exact_id_matches'],
                'inputs': {'spotify_csv': args.spotify_csv.name,
                           'spotify_parquet': args.spotify_parquet.name if args.spotify_parquet else None,
                           'musicbrainz': args.musicbrainz.name,
                           'musicbrainz_releases': args.musicbrainz_releases.name if args.musicbrainz_releases else None,
                           'acoustic_archives': [path.name for path in args.acoustic_archive]},
                'acoustic_web_ids_checked': checked,
                'acoustic_web_interruption': interruption,
                **compile_profiles(db),
            }
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('INSERT INTO metadata VALUES (?, ?)', ('report', json.dumps(report)))
            db.commit()
        (work / OUTPUT_REPORT).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        (work / OUTPUT_DB).replace(args.output / OUTPUT_DB)
        (work / OUTPUT_REPORT).replace(args.output / OUTPUT_REPORT)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--output', type=Path, default=Path('runs/million/catalogue-enrichment'))
    parser.add_argument('--spotify-csv', type=Path, default=Path('private-data/spotify_tracks.csv'))
    parser.add_argument('--spotify-parquet', type=Path, help='Optional second Spotify snapshot with title, artist and duration')
    parser.add_argument('--musicbrainz', type=Path, required=True, help='Official recording.tar.xz JSON dump')
    parser.add_argument('--musicbrainz-releases', type=Path, help='Optional official release.tar.xz JSON dump')
    parser.add_argument('--acoustic-archive', type=Path, action='append', default=[], help='AcousticBrainz low-level tar archive. Repeat for each archive.')
    parser.add_argument('--acoustic-online-limit', type=int, default=0, help='Maximum matched MusicBrainz IDs to check via public API')
    parser.add_argument('--contact', help='Project URL or contact email for the AcousticBrainz API user-agent')
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, sqlite3.Error, tarfile.TarError) as error:
        parser.exit(2, f'Catalogue enrichment failed: {error}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
