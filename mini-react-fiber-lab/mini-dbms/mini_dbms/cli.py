"""Execute SQL commands from a UTF-8 file."""
import argparse
import json
import sys
from pathlib import Path
from .database import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--data', default='.data/db', help='Directory containing table files')
    parser.add_argument('--scan', action='store_true', help='Use linear scans even for an ID lookup')
    args = parser.parse_args()
    try:
        sql = args.file.read_text(encoding='utf-8-sig')
        with Database(args.data) as db:
            result = db.execute(sql, use_index=not args.scan)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, RuntimeError, ValueError) as error:
        print(f'Mini DBMS: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
