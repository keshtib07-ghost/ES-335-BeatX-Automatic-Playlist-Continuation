"""Build and inspect local song profiles, then pilot external recording matches."""

import argparse
import csv
import gzip
import json
import sqlite3
from collections import Counter
from contextlib import closing
from functools import partial
from pathlib import Path

import joblib
import numpy as np

from playlist_model.data import track_id
from playlist_model.million import fit_tags, open_dataset, read_json, write_json
from playlist_model.profile_sources import (CREDIT_DURATION_TOLERANCE_MS, LISTENBRAINZ_SOURCES, MetadataClient,
                                            MetadataUnavailable, lookup_by_name, lookup_reviewed_track, lookup_track,
                                            refresh_acoustic, valid_mbid)
from playlist_model.profile_tags import (AMBIGUOUS_CUE, ASSOCIATION_SMOOTHING, CONTEXT_AXIS, CONTEXT_GROUPS,
                                         CONTEXT_TAGS, DECADES, EXPANDED_CUES_VERSION, PROFILE_VERSIONS,
                                         TAXONOMY_VERSION, contextual_scores, predicted_context, requested_eras,
                                         title_context, weak_context)
from playlist_model.tagger import normalize


PROFILE_FIELDS = ('mbid', 'release_date', 'release_year', 'era', 'bpm', 'bass_share', 'treble_share', 'acoustic_version',
                  'known_release_year')
MEASUREMENTS = ('release_date', 'bpm', 'bass_share', 'treble_share')
EXTERNAL_IDENTITY = 'musicbrainz-acousticbrainz-v1'


def csv_text(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


def write_csv(path, headers, rows):
    temp = path.with_suffix('.csv.tmp')
    with temp.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(tuple(csv_text(value) for value in row) for row in rows)
    temp.replace(path)


def audit_titles(data, tagger, summary, output, expanded=False):
    sample = data.sample('validation', 'p.pid, p.title', 5000, salt=336)
    predictions = tagger.predict([title for _, title in sample])
    counts = Counter()

    def rows():
        for (pid, title), prediction in zip(sample, predictions):
            labels = weak_context(title, expanded=expanded)
            learned = {CONTEXT_TAGS[index] for index in np.flatnonzero(prediction)}
            _, exclusions = title_context(title, expanded=expanded)
            issues = []
            if labels != learned:
                issues.append('rule_model_disagreement')
            if exclusions & learned:
                issues.append('classifier_predicted_negated_tag')
            if not labels and AMBIGUOUS_CUE.search(normalize(title)):
                issues.append('ambiguous_title')
            if issues:
                counts.update(issues)
                yield pid, title, '|'.join(issues), '|'.join(sorted(labels)), '|'.join(sorted(learned)), ''

    write_csv(output / 'title_tag_review.csv',
              ('playlist_id', 'title', 'issue', 'rule_tags', 'classifier_tags', 'reviewer_tags'), rows())
    per_tag = summary['validation_rule_agreement']['per_tag']
    write_csv(output / 'tag_coverage.csv', ('category', 'tag', 'training_playlists', 'validation_rule_positives',
                                           'validation_model_predictions', 'validation_rule_f1', 'review_flag'),
              ((category, tag, summary['training_titles_by_tag'][tag], per_tag[tag]['support'], per_tag[tag]['predicted'],
                per_tag[tag]['f1'], 'few_validation_examples' if per_tag[tag]['support'] < 25 else '')
               for category, tags in CONTEXT_GROUPS.items() for tag in tags))
    return {'validation_titles_reviewed_by_rules': len(sample), 'title_review_flags': dict(counts)}


def build(data, output, title_limit, expanded=False):
    version = EXPANDED_CUES_VERSION if expanded else TAXONOMY_VERSION
    summary = fit_tags(data, output, title_limit, groups=CONTEXT_GROUPS, rules=partial(weak_context, expanded=expanded),
                       taxonomy_version=version, predict=partial(predicted_context, expanded=expanded),
                       cross_category_baseline=('party',))
    tagger = joblib.load(output / 'tags/title_tagger.joblib')
    result = {'catalogue_track_ids': data.track_count, 'taxonomy': version,
              'training_playlists': summary['train_playlists_scored_for_song_tags'],
              **audit_titles(data, tagger, summary, output, expanded)}
    write_json(output / 'tag_report.json', result)
    return result


def inspect(data, output, identifier):
    if not identifier:
        raise ValueError('Enter a Spotify track ID or spotify:track URI.')
    row = data.connection.execute('''
        SELECT track_index, track_name, artist_name, album_name, duration_ms FROM catalogue WHERE spotify_id=?
    ''', (identifier,)).fetchone()
    if row is None:
        raise ValueError('Track ID is not in your MPD catalogue.')
    index, title, artist, album, duration = row
    canonical = int(data.aliases[index]) if data.aliases is not None else index
    source_profile = {'match_status': 'not_checked', 'acoustic_status': 'not_checked', **dict.fromkeys(PROFILE_FIELDS)}
    if (output / 'enrichment.sqlite3').is_file():
        with closing(sqlite3.connect(output / 'enrichment.sqlite3')) as db:
            validate_external_identity(db, data)
            if match := db.execute('SELECT profile FROM lookups WHERE spotify_id=?', (identifier,)).fetchone():
                source_profile.update(json.loads(match[0]))

    context = {}
    tags = output / 'tags'
    if tags.is_dir():
        identity = read_json(tags / 'summary.json')['identity']
        if (identity['taxonomy_version'] not in PROFILE_VERSIONS or identity['split'] != data.identity['split']
                or identity['tag_groups'] != {key: list(values) for key, values in CONTEXT_GROUPS.items()}):
            raise ValueError('Track tag evidence belongs to a different split or taxonomy.')
        votes = np.load(tags / 'track_tag_votes.npy', mmap_mode='r')[canonical]
        totals = np.load(tags / 'track_axis_totals.npy', mmap_mode='r')[canonical]
        priors = np.load(tags / 'tag_priors.npy')
        lifts = contextual_scores(votes, totals, priors)
        context = {tag: {'playlist_group_votes': int(votes[i]), 'category_group_count': int(totals[CONTEXT_AXIS[i]]),
                         'lift': float(lifts[i]) if np.isfinite(lifts[i]) else None}
                   for i, tag in enumerate(CONTEXT_TAGS)}
    return {'spotify_id': identifier, 'spotify_url': f'https://open.spotify.com/track/{identifier}',
            'title': title, 'artist': artist, 'album': album, 'duration_ms': duration,
            'context_scores': context, **source_profile}


def validate_external_identity(db, data):
    expected = json.dumps({'version': EXTERNAL_IDENTITY, 'split': data.identity['split']}, sort_keys=True)
    saved = db.execute('SELECT value FROM identity WHERE key=\'run\'').fetchone()
    if saved is None or saved[0] != expected:
        raise ValueError('Enrichment cache belongs to a different split or match policy.')


def choose_pilot(data, model, count):
    index = model / 'index'
    if read_json(index / 'summary.json')['identity'] != data.identity:
        raise ValueError('Training index belongs to a different split.')
    counts = np.diff(np.load(index / 'track_offsets.npy', mmap_mode='r'))
    tracks = np.flatnonzero(counts)
    ranked = tracks[np.argsort(-counts[tracks], kind='stable')]
    head_size = max(1, len(ranked) // 10)
    rng = np.random.default_rng(335)
    first = min((count + 1) // 2, head_size)
    head = rng.permutation(ranked[:head_size])
    tail = rng.permutation(ranked[head_size:])
    tail_count = min(count - first, len(tail))
    first = min(count - tail_count, len(head))
    return [(int(i), 'top_decile', int(counts[i])) for i in head[:first]] + [
        (int(i), 'remaining_catalogue', int(counts[i])) for i in tail[:tail_count]]


def export_lookups(db, output, progress):
    entries = list(db.execute('SELECT spotify_id, title, artist, stratum, training_support, profile FROM lookups ORDER BY spotify_id'))
    headers = ('spotify_id', 'title', 'artist', 'stratum', 'training_support', 'match_status', 'candidate_mbids',
               'acoustic_status', *PROFILE_FIELDS, 'recording_source', 'audio_lookup_error')
    rows, issues, verified = [], [], []
    counts, availability, audio, sources = Counter(), Counter(), Counter(), Counter()
    for identifier, title, artist, stratum, support, payload in entries:
        fields = json.loads(payload)
        counts[fields['match_status']] += 1
        audio[fields['acoustic_status']] += 1
        source = fields.get('recording_source', 'musicbrainz')
        sources[source] += 1
        row = (identifier, title, artist, stratum, support, fields['match_status'], '|'.join(fields['candidate_mbids']),
               fields['acoustic_status'], *(fields.get(field) for field in PROFILE_FIELDS), source,
               fields.get('audio_lookup_error', ''))
        rows.append(row)
        if fields['match_status'] == 'verified_recording':
            verified.append((identifier, fields['mbid']))
        missing = [key for key in MEASUREMENTS if fields[key] is None]
        availability.update(key for key in MEASUREMENTS if key not in missing)
        if not fields['mbid'] or missing:
            issues.append((*row, '|'.join(missing)))
    write_csv(output / 'enrichment_pilot.csv', headers, rows)
    write_csv(output / 'enrichment_issues.csv', (*headers, 'missing_fields'), issues)
    write_csv(output / 'verified_recording_map.csv', ('track_id', 'recording_id'), verified)
    result = {'checked_tracks': len(rows), 'match_status': dict(counts),
              'coverage_by_field': {field: availability[field] for field in MEASUREMENTS},
              'tracks_with_issues': len(issues), 'audio_status': dict(audio), 'recording_source_counts': dict(sources),
              'run_progress': progress}
    write_json(output / 'enrichment_report.json', result)
    return result


def enrich(data, output, model, count, contact, reviewed=None, source='musicbrainz'):
    if reviewed is None:
        selected = [(index, stratum, support, None) for index, stratum, support in choose_pilot(data, model, count)]
    else:
        selected = []
        with reviewed.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            if not {'track_id', 'recording_id'}.issubset(reader.fieldnames or []):
                raise ValueError('Reviewed map requires track_id and recording_id columns.')
            seen = set()
            for row in reader:
                identifier, mbid = track_id(row['track_id']), row['recording_id'].strip()
                index = data.connection.execute('SELECT track_index FROM catalogue WHERE spotify_id=?', (identifier,)).fetchone()
                if not valid_mbid(mbid) or index is None or identifier in seen:
                    raise ValueError(f'Invalid, repeated or unknown reviewed match on line {reader.line_num}.')
                selected.append((index[0], 'manually_reviewed', None, mbid))
                seen.add(identifier)
    client = MetadataClient(contact)
    progress = {'selected_tracks': len(selected), 'recording_lookups_completed': 0,
                'audio_lookups_pending': 0, 'interruption': None, 'recording_source': source}
    output.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(output / 'enrichment.sqlite3', timeout=5)) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS identity (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lookups (spotify_id TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL,
                stratum TEXT NOT NULL, training_support INTEGER NOT NULL, profile TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS acoustic_cache (mbid TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')
        with db:
            db.execute('INSERT OR IGNORE INTO identity VALUES (?,?)',
                       ('run', json.dumps({'version': EXTERNAL_IDENTITY, 'split': data.identity['split']}, sort_keys=True)))
        validate_external_identity(db, data)
        try:
            for position, (index, stratum, support, mbid) in enumerate(selected, start=1):
                identifier, title, artist, album, duration = data.connection.execute('''
                    SELECT spotify_id, track_name, artist_name, album_name, duration_ms FROM catalogue WHERE track_index=?
                ''', (index,)).fetchone()
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    prior = db.execute('SELECT profile FROM lookups WHERE spotify_id=?', (identifier,)).fetchone()
                    saved = json.loads(prior[0]) if prior else None
                    same_policy = (saved and saved.get('recording_source', 'musicbrainz') == source
                                   and (source != 'listenbrainz-credits'
                                        or saved.get('duration_tolerance_ms') == CREDIT_DURATION_TOLERANCE_MS))
                    reuse = saved and (
                        (mbid is None and (saved['mbid'] or same_policy))
                        or (mbid is not None and saved['match_status'] == 'verified_recording' and saved['mbid'] == mbid)
                    )
                    if reuse and saved['acoustic_status'] != 'audio_lookup_pending':
                        progress['recording_lookups_completed'] += 1
                        continue
                    if reuse:
                        fields = refresh_acoustic(client, db, saved)
                    else:
                        fields = (lookup_reviewed_track(client, db, mbid, source) if mbid
                                  else lookup_track(client, db, title, artist, album, duration, source))
                    db.execute('INSERT OR REPLACE INTO lookups VALUES (?,?,?,?,?,?)',
                               (identifier, title, artist, stratum, support or 0, json.dumps(fields)))
                progress['recording_lookups_completed'] += 1
                if fields['acoustic_status'] == 'audio_lookup_pending':
                    progress['audio_lookups_pending'] += 1
                print(f'{position}/{len(selected)} {identifier} {fields["match_status"]} · {fields["acoustic_status"]}', flush=True)
        except MetadataUnavailable as error:
            progress['interruption'] = str(error)
            print(f'{error}. Completed lookups are saved. Rerun the command to resume.', flush=True)
        except KeyboardInterrupt:
            progress['interruption'] = 'stopped by user'
            raise
        finally:
            progress['recording_lookups_remaining'] = len(selected) - progress['recording_lookups_completed']
            result = export_lookups(db, output, progress)
    return result


def export_flags(data, output):
    tags = output / 'tags'
    identity = read_json(tags / 'summary.json')['identity']
    if identity['taxonomy_version'] not in PROFILE_VERSIONS or identity['split'] != data.identity['split']:
        raise ValueError('Track tag evidence belongs to a different split or taxonomy.')
    votes = np.load(tags / 'track_tag_votes.npy', mmap_mode='r')
    totals = np.load(tags / 'track_axis_totals.npy', mmap_mode='r')
    priors = np.load(tags / 'tag_priors.npy')
    destination = output / 'track_tag_flags.csv.gz'
    temporary = destination.with_suffix('.tmp')
    counts = Counter()
    covered = tracks = 0
    categories = tuple(CONTEXT_GROUPS)
    profiles = {}
    if (output / 'enrichment.sqlite3').is_file():
        with closing(sqlite3.connect(output / 'enrichment.sqlite3')) as db:
            validate_external_identity(db, data)
            profiles = {key: (title, artist, json.loads(value)) for key, title, artist, value in db.execute(
                'SELECT spotify_id, title, artist, profile FROM lookups')}
    with gzip.open(temporary, 'wt', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(('spotify_id', 'title', 'artist', 'category', 'tag', 'group_votes', 'category_groups', 'lift', 'source_status'))
        cursor = data.connection.execute('SELECT track_index, spotify_id, track_name, artist_name FROM catalogue ORDER BY track_index')
        while rows := cursor.fetchmany(8_192):
            indices = np.array([row[0] for row in rows])
            if data.aliases is not None:
                indices = data.aliases[indices]
            count, category_count = votes[indices], totals[indices][:, CONTEXT_AXIS]
            marked = (count > 0) & (count > category_count * priors) & (priors > 0)
            covered += int(marked.any(axis=1).sum())
            tracks += len(rows)
            for i, column in zip(*np.nonzero(marked)):
                support, n, prior = int(count[i, column]), int(category_count[i, column]), float(priors[column])
                lift = (support + ASSOCIATION_SMOOTHING * prior) / ((n + ASSOCIATION_SMOOTHING) * prior)
                tag = CONTEXT_TAGS[column]
                counts[tag] += 1
                _, identifier, title, artist = rows[i]
                writer.writerow((identifier, csv_text(title), csv_text(artist), categories[CONTEXT_AXIS[column]],
                                 tag, support, n, round(lift, 6), 'playlist_evidence'))
        for identifier, (title, artist, profile) in profiles.items():
            if era := profile.get('era'):
                writer.writerow((identifier, csv_text(title), csv_text(artist), 'era', era, '', '', '', profile['match_status']))
                counts[era] += 1
    temporary.replace(destination)
    report = {'track_ids_checked': tracks, 'with_positive_context_evidence': covered,
              'without_positive_context_evidence': tracks - covered,
              'flags_by_tag': {tag: counts[tag] for tag in (*CONTEXT_TAGS, *DECADES.values(), 'other')}}
    write_json(output / 'track_flag_report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    parser.add_argument('--output', type=Path, default=Path('runs/million/profiles-v2'))
    parser.add_argument('--allow-partial-source', action='store_true')
    commands = parser.add_subparsers(dest='command', required=True)
    builder = commands.add_parser('build')
    builder.add_argument('--title-limit', type=int, default=60_000)
    builder.add_argument('--expanded-title-cues', action='store_true')
    commands.add_parser('export-flags')
    inspector = commands.add_parser('inspect')
    inspector.add_argument('spotify_id')
    inspector.add_argument('--playlist-title', help='Also show rule-based context and era requests for this title')
    search = commands.add_parser('lookup-name', help='Search public recording metadata by song and artist')
    search.add_argument('title')
    search.add_argument('artist')
    search.add_argument('--album', default='')
    search.add_argument('--duration-ms', type=int)
    search.add_argument('--contact', required=True, help='Contact email or project URL for the API user-agent')
    pilot = commands.add_parser('enrich')
    pilot.add_argument('--model', type=Path, default=Path('runs/million/model'))
    pilot.add_argument('--limit', type=int, default=30)
    pilot.add_argument('--contact', required=True, help='Email or project URL for the MusicBrainz API user-agent')
    pilot.add_argument('--reviewed-map', type=Path, help='Review CSV containing verified track_id and recording_id pairs')
    pilot.add_argument('--recording-source', choices=('musicbrainz', *LISTENBRAINZ_SOURCES), default='musicbrainz',
                       help='Use listenbrainz-credits to accept a matching primary artist on joint credits')
    args = parser.parse_args()
    try:
        if args.command == 'lookup-name':
            if not all(value.strip() for value in (args.title, args.artist, args.contact)) or any(
                    char in args.contact for char in '\r\n') or (args.duration_ms is not None and args.duration_ms <= 0):
                raise ValueError('Provide a song title, an artist and a contact. If given, duration must be positive.')
            client = MetadataClient(args.contact.strip())
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE acoustic_cache (mbid TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                profile = lookup_by_name(client, db, args.title, args.artist, args.album, args.duration_ms)
            print(json.dumps({'title': args.title, 'artist': args.artist, **profile}, indent=2,
                             ensure_ascii=False, allow_nan=False))
            return
        with open_dataset(args.source, args.split, args.allow_partial_source) as data:
            if args.command == 'build':
                if args.title_limit < 2:
                    raise ValueError('Title limit must be at least two.')
                result = build(data, args.output, args.title_limit, args.expanded_title_cues)
            elif args.command == 'export-flags':
                result = export_flags(data, args.output)
            elif args.command == 'inspect':
                result = inspect(data, args.output, track_id(args.spotify_id))
                if args.playlist_title:
                    summary = args.output / 'tags/summary.json'
                    expanded = summary.is_file() and read_json(summary)['identity']['taxonomy_version'] == EXPANDED_CUES_VERSION
                    labels = weak_context(args.playlist_title, expanded=expanded)
                    result['playlist_title_rules'] = {'context_tags': sorted(labels),
                                                      'requested_eras': sorted(requested_eras(args.playlist_title))}
            else:
                if args.limit < 1 or not args.contact.strip() or '\n' in args.contact or '\r' in args.contact:
                    raise ValueError('Provide a positive sample limit and a contact email or project URL.')
                result = enrich(data, args.output, args.model, args.limit, args.contact.strip(), args.reviewed_map,
                                args.recording_source)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        if args.command == 'enrich' and result['run_progress']['interruption']:
            parser.exit(2)
    except KeyboardInterrupt:
        parser.exit(130, '\nStopped. Finished stages and completed lookups are saved.\n')
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
