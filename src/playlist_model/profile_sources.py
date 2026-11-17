"""Conservative, resumable catalogue enrichment for a small local pilot."""

import json
import math
import re
import time
import unicodedata
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from .profile_tags import recording_era


MUSICBRAINZ = 'https://musicbrainz.org/ws/2/recording/'
LISTENBRAINZ_ALBUM_LOOKUP = 'https://labs.api.listenbrainz.org/acrr-lookup/json'
LISTENBRAINZ_TITLE_SEARCH = 'https://labs.api.listenbrainz.org/recording-search/json'
LISTENBRAINZ_RECORDING = 'https://api.listenbrainz.org/1/metadata/recording/'
LISTENBRAINZ_SOURCES = ('listenbrainz', 'listenbrainz-search', 'listenbrainz-credits')
CREDIT_DURATION_TOLERANCE_MS = 5_000
ACOUSTICBRAINZ = 'https://acousticbrainz.org/api/v1/'
VERSION_WORDS = re.compile(r'\b(?:live|remix|remaster(?:ed)?|acoustic|instrumental|demo|karaoke|radio edit|sped up|slowed)\b')
DATE = re.compile(r'(?:18|19|20)\d{2}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?\Z')
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
RETRY_DELAYS = (2., 5.)


class MetadataUnavailable(RuntimeError):
    pass


def retry_delay(value):
    if not value:
        return 0.
    if value.isdigit():
        return float(value)
    try:
        return max(0., parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return 0.


class MetadataClient:
    def __init__(self, contact):
        self.user_agent = f'BeatX-ES335/1.0 ({contact})'
        self.next_request = 0.
        self.unavailable = {}

    def get(self, url, *, missing_ok=False):
        request = Request(url, headers={'User-Agent': self.user_agent, 'Accept': 'application/json'})
        host = urlsplit(url).hostname
        if host in self.unavailable:
            raise MetadataUnavailable(self.unavailable[host])
        for attempt in range(len(RETRY_DELAYS) + 1):
            time.sleep(max(0., self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + 1.1
            wait_hint = 0.
            try:
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 404 and missing_ok:
                    return None
                reason = f'{host} returned HTTP {error.code}'
                retryable = error.code in RETRYABLE_HTTP
                wait_hint = retry_delay(error.headers.get('Retry-After')) if error.headers else 0.
            except (TimeoutError, URLError, ConnectionError):
                reason = f'{host} connection failed or timed out'
                retryable = True
            except ValueError:
                reason = f'{host} returned invalid JSON'
                retryable = False
            if not retryable or attempt == len(RETRY_DELAYS) or wait_hint > 20.:
                self.unavailable[host] = reason
                raise MetadataUnavailable(reason)
            self.next_request = max(self.next_request, time.monotonic() + max(RETRY_DELAYS[attempt], wait_hint))


def normalized(value):
    text = unicodedata.normalize('NFKC', value or '').casefold()
    return ' '.join(re.findall(r'\w+', text))


def valid_mbid(value):
    try:
        return str(UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def quoted(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def choose_recording(title, artist, album, duration_ms, results):
    """Emit only unambiguous metadata matches, explicitly marked provisional."""
    if not results:
        return 'no_recording_found', None, []
    target_title, target_artist = normalized(title), normalized(artist)
    target_version = set(VERSION_WORDS.findall(normalized(f'{title} {album}')))
    candidates, matches = {}, {}
    for record in results:
        identifier = record.get('id')
        if not valid_mbid(identifier):
            continue
        credits = record.get('artist-credit', [])
        artist_credit = ''.join(credit.get('name', '') + credit.get('joinphrase', '') for credit in credits)
        if normalized(record.get('title')) != target_title or normalized(artist_credit) != target_artist:
            continue
        candidates[identifier] = record
        duration = record.get('length')
        version = set(VERSION_WORDS.findall(normalized(record.get('disambiguation'))))
        if (duration_ms and isinstance(duration, int) and abs(duration_ms - duration) <= 2_000
                and (target_version - set(VERSION_WORDS.findall(target_title))) <= version
                and version <= target_version):
            matches[identifier] = record
    if len(matches) == 1:
        return 'metadata_match', next(iter(matches.values())), list(matches)
    if matches:
        return 'multiple_recording_matches', None, list(matches)
    if candidates:
        return 'duration_or_version_unverified', None, list(candidates)
    return 'title_or_artist_not_exact', None, [r['id'] for r in results if valid_mbid(r.get('id'))]


def acoustic_fields(payload):
    if not payload:
        return {'bpm': None, 'bass_share': None, 'treble_share': None, 'acoustic_version': None}

    def number(value):
        return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None

    lowlevel = payload.get('lowlevel', {})
    total = number(lowlevel.get('spectral_energy', {}).get('mean'))

    def share(band):
        energy = number(lowlevel.get('spectral_energyband_' + band, {}).get('mean'))
        return energy / total if total and energy is not None and energy <= total else None

    bpm = number(payload.get('rhythm', {}).get('bpm'))
    metadata = payload.get('metadata', {}).get('version', {})
    return {'bpm': bpm if bpm else None, 'bass_share': share('low'), 'treble_share': share('high'),
            'acoustic_version': metadata.get('essentia') or metadata.get('essentia_git_sha')}


def listenbrainz_recordings(client, mbids):
    query = urlencode({'recording_mbids': ','.join(mbids), 'inc': 'release'})
    response = client.get(f'{LISTENBRAINZ_RECORDING}?{query}')
    if not isinstance(response, dict):
        raise MetadataUnavailable('ListenBrainz returned an unexpected recording response')
    recordings = {}
    for mbid in mbids:
        entry = response.get(mbid, {})
        recording = entry.get('recording')
        release = entry.get('release') or {}
        recordings[mbid] = {**recording, 'known_release_year': release.get('year')} if recording else None
    return recordings


def listenbrainz_recording(client, mbid):
    return listenbrainz_recordings(client, [mbid])[mbid]


def listenbrainz_album_match(client, title, artist, album, duration_ms):
    if not all((title.strip(), artist.strip(), album.strip(), duration_ms)):
        return 'album_or_duration_missing', None, []
    query = urlencode({'artist_credit_name': artist, 'recording_name': title, 'release_name': album})
    response = client.get(f'{LISTENBRAINZ_ALBUM_LOOKUP}?{query}')
    if not isinstance(response, list):
        raise MetadataUnavailable('ListenBrainz returned an unexpected album search response')
    records = [row for row in response if valid_mbid(row.get('recording_mbid'))]
    if not records:
        return 'no_recording_found', None, []
    candidates = sorted({row['recording_mbid'] for row in records})
    expected = tuple(map(normalized, (title, artist, album)))
    matches = {row['recording_mbid'] for row in records if expected == tuple(map(normalized, (
        row.get('recording_name'), row.get('artist_credit_name'), row.get('release_name'))))}
    if len(matches) != 1:
        status = 'multiple_recording_matches' if matches else 'title_artist_or_album_not_exact'
        return status, None, candidates
    identifier = next(iter(matches))
    recording = listenbrainz_recording(client, identifier)
    duration = recording.get('length') if recording else None
    if not isinstance(duration, int) or abs(duration_ms - duration) > 2_000:
        return 'duration_or_version_unverified', None, candidates
    if normalized(recording.get('name')) != expected[0]:
        return 'title_artist_or_album_not_exact', None, candidates
    return 'metadata_match', {'id': identifier, 'first-release-date': recording.get('first_release_date')}, candidates


def search_name(value):
    unaccented = ''.join(char for char in unicodedata.normalize('NFKD', value or '')
                         if not unicodedata.combining(char))
    return normalized(unaccented)


def matching_credit(artist, credit):
    if search_name(credit) == artist:
        return True
    # Spotify's MPD often lists one artist when MusicBrainz has a joint credit.
    return any(search_name(credit[:separator.start()]) == artist for separator in
               re.finditer(r'\s+(?:feat\.?|ft\.?|featuring|with|and|&|x)\s+|,\s+', credit, re.IGNORECASE))


def listenbrainz_title_match(client, title, artist, album, duration_ms, *, joint_credits=False, preview=False):
    """Search across editions and require one compatible recording."""
    normalize = search_name if joint_credits else normalized
    title_key, artist_key = normalize(title), normalize(artist)
    if not title_key or not artist_key or (not preview and not duration_ms):
        return 'title_artist_or_duration_missing', None, []
    query = urlencode({'query': f'{artist.strip()} {title.strip()}'})
    response = client.get(f'{LISTENBRAINZ_TITLE_SEARCH}?{query}')
    if not isinstance(response, list):
        raise MetadataUnavailable('ListenBrainz returned an unexpected artist and title search response')
    candidates = [row for row in response if valid_mbid(row.get('recording_mbid'))]
    if not candidates:
        return 'no_recording_found', None, []

    def artist_matches(credit):
        if joint_credits:
            return matching_credit(artist_key, credit or '')
        return normalize(credit) == artist_key

    exact = [row for row in candidates if normalize(row.get('recording_name')) == title_key
             and artist_matches(row.get('artist_credit_name'))]
    if not exact:
        return 'title_or_artist_not_exact', None, sorted({row['recording_mbid'] for row in candidates})
    title_versions = set(VERSION_WORDS.findall(title_key))
    album_versions = set(VERSION_WORDS.findall(normalize(album))) - title_versions
    compatible = sorted({row['recording_mbid'] for row in exact if
                         (set(VERSION_WORDS.findall(normalize(row.get('release_name')))) - title_versions)
                         == album_versions})
    if not compatible:
        return 'duration_or_version_unverified', None, sorted({row['recording_mbid'] for row in exact})
    if len(compatible) > 20 or (preview and len(compatible) != 1):
        return 'multiple_recording_matches', None, compatible
    details = listenbrainz_recordings(client, compatible)
    tolerance_ms = CREDIT_DURATION_TOLERANCE_MS if joint_credits else 2_000
    matches = {}
    unverified = False
    for identifier in compatible:
        record = details[identifier]
        if not record or normalize(record.get('name')) != title_key:
            unverified = True
            continue
        length = record.get('length')
        if not preview and type(length) is not int:
            unverified = True
        elif preview or abs(duration_ms - length) <= tolerance_ms:
            matches[identifier] = record
    if len(matches) > 1:
        return 'multiple_recording_matches', None, sorted(matches)
    if len(matches) != 1 or unverified:
        return 'duration_or_version_unverified', None, compatible
    identifier, record = next(iter(matches.items()))
    status = 'candidate_without_duration' if preview else 'metadata_match'
    return status, {'id': identifier, 'first-release-date': record.get('first_release_date'),
                    'known-release-year': record.get('known_release_year')}, [identifier]


def lookup_by_name(client, connection, title, artist, album, duration_ms):
    status, selected, candidates = listenbrainz_title_match(
        client, title, artist, album, duration_ms, joint_credits=True, preview=duration_ms is None)
    return recording_profile(client, connection, status, selected, candidates, 'listenbrainz-credits')


def lookup_track(client, connection, title, artist, album, duration_ms, source='musicbrainz'):
    if source == 'listenbrainz':
        status, selected, candidates = listenbrainz_album_match(client, title, artist, album, duration_ms)
        return recording_profile(client, connection, status, selected, candidates, source)
    if source in LISTENBRAINZ_SOURCES[1:]:
        status, selected, candidates = listenbrainz_title_match(
            client, title, artist, album, duration_ms, joint_credits=source == 'listenbrainz-credits')
        return recording_profile(client, connection, status, selected, candidates, source)
    query = urlencode({'fmt': 'json', 'limit': 25, 'query': f'recording:{quoted(title)} AND artist:{quoted(artist)}'})
    result = client.get(f'{MUSICBRAINZ}?{query}')
    if not isinstance(result, dict) or not isinstance(result.get('recordings', []), list):
        raise MetadataUnavailable('MusicBrainz returned an unexpected recording search response')
    records = result.get('recordings', [])
    if 'recordings' not in result and result.get('count') != 0:
        raise MetadataUnavailable('MusicBrainz returned an unexpected recording search response')
    status, selected, candidates = choose_recording(title, artist, album, duration_ms, records)
    if selected and result.get('count', len(records)) > len(records):
        status, selected = 'search_candidates_truncated', None
    return recording_profile(client, connection, status, selected, candidates, source)


def lookup_reviewed_track(client, connection, mbid, source='musicbrainz'):
    if source in LISTENBRAINZ_SOURCES:
        recording = listenbrainz_recording(client, mbid)
        selected = {'id': mbid, 'first-release-date': recording.get('first_release_date')} if recording else None
    else:
        selected = client.get(f'{MUSICBRAINZ}{mbid}?fmt=json', missing_ok=True)
    status = 'verified_recording' if selected else 'reviewed_id_not_found'
    return recording_profile(client, connection, status, selected, [mbid], source)


def recording_profile(client, connection, status, selected, candidates, source):
    profile = {'match_status': status, 'candidate_mbids': candidates, 'mbid': None, 'release_date': None,
               'release_year': None, 'era': None, 'acoustic_status': 'not_checked', 'recording_source': source,
               **acoustic_fields(None)}
    if source == 'listenbrainz-credits':
        profile['duration_tolerance_ms'] = CREDIT_DURATION_TOLERANCE_MS
    if selected is None:
        return profile
    identifier = selected['id']
    profile['mbid'] = identifier
    year = selected.get('known-release-year')
    if type(year) is int and 1800 <= year < 2100:
        profile['known_release_year'] = year
    date = selected.get('first-release-date') or ''
    if DATE.fullmatch(date):
        year = int(date[:4])
        profile.update(release_date=date, release_year=year, era=recording_era(year))
    return refresh_acoustic(client, connection, profile)


def refresh_acoustic(client, connection, profile):
    identifier = profile['mbid']
    cached = connection.execute('SELECT payload FROM acoustic_cache WHERE mbid=?', (identifier,)).fetchone()
    if cached is None:
        try:
            response = client.get(f'{ACOUSTICBRAINZ}{identifier}/low-level', missing_ok=True)
        except MetadataUnavailable as error:
            return {**profile, 'acoustic_status': 'audio_lookup_pending', 'audio_lookup_error': str(error)}
        measurements = {'acoustic_status': 'found' if response else 'no_audio_analysis', **acoustic_fields(response)}
        connection.execute('INSERT INTO acoustic_cache VALUES (?,?)', (identifier, json.dumps(measurements)))
    else:
        measurements = json.loads(cached[0])
    result = {**profile, **measurements}
    result.pop('audio_lookup_error', None)
    return result
