#!/usr/bin/env python3
"""Build a reproducible ZIP without an extra Terraform archive provider."""
import argparse
import io
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / 'functions/worker-restarter'
    destination = root / 'function.zip'
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        info = zipfile.ZipInfo('index.py', date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, (root / 'index.py').read_bytes())
    if args.check:
        if not destination.exists() or destination.read_bytes() != output.getvalue():
            raise SystemExit('Function ZIP differs from source; run scripts/build-worker-restarter.py')
        print('Function ZIP matches index.py.')
    else:
        destination.write_bytes(output.getvalue())
        print('Built functions/worker-restarter/function.zip')


if __name__ == '__main__':
    main()
