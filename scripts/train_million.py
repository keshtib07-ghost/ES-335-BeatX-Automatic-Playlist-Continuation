"""Train, tune and evaluate the full MPD recommender in separate phases."""

import argparse
import json
import sqlite3
from pathlib import Path

from playlist_model.million import build_index, fit_tags, open_dataset
from playlist_model.million_eval import test, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    parser.add_argument('--run', type=Path, default=Path('runs/million/model'))
    parser.add_argument('--allow-partial-source', action='store_true', help='Permit development with a verified smaller split')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('index', help='Index all training-playlist memberships in both directions')
    tags = commands.add_parser('tags', help='Fit the title classifier and aggregate training-only track evidence')
    tags.add_argument('--title-training-limit', type=int, help='Cap fitting at this many training titles (default: all)')
    selection = commands.add_parser('validate', help='Compare tag weights on a fixed validation sample and freeze the choice')
    selection.add_argument('--queries', type=int, default=5_000)
    commands.add_parser('test', help='Evaluate the frozen settings on fresh held-out playlists')
    args = parser.parse_args()
    try:
        with open_dataset(args.source, args.split, args.allow_partial_source) as data:
            if args.command == 'index':
                result = build_index(data, args.run)
            elif args.command == 'tags':
                if args.title_training_limit is not None and args.title_training_limit < 2:
                    raise ValueError('The title training limit must be at least two')
                result = fit_tags(data, args.run, args.title_training_limit)
            elif args.command == 'validate':
                if args.queries < 1:
                    raise ValueError('The query limit must be positive')
                result = validate(data, args.run, args.queries)
            else:
                result = test(data, args.run)
        print(json.dumps(result, indent=2), flush=True)
    except KeyboardInterrupt:
        parser.exit(130, '\nStopped. Finished training stages are saved. Rerun the interrupted command to restart that stage.\n')
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
