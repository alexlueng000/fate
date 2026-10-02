"""Build type-specific indexes from scratch; validate before replacing old ones."""
from pathlib import Path
import subprocess
import sys
import json
import os
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    index_root = ROOT / 'kb_index'
    index_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.consultation-build-', dir=index_root) as work:
        work = Path(work)
        source_bazi = work / 'sources'
        source_bazi.mkdir()
        # Root files are Bazi; recursive ingestion would mix in Liuyao.
        for source in (ROOT / 'kb_files').glob('*.txt'):
            shutil.copy2(source, source_bazi / source.name)
        for kind, source in (('bazi', source_bazi), ('liuyao', ROOT / 'kb_files' / 'liuyao')):
            target = work / kind
            subprocess.run([sys.executable, str(ROOT / 'kb_rag_mult.py'), 'ingest', '-i', str(source), '-o', str(target)],
                check=True, cwd=ROOT, env={**os.environ, 'KB_TFIDF_ANALYZER': 'char'})
            if not (target / 'chunks.json').is_file() or not (target / 'embeddings.npz').is_file():
                raise RuntimeError(f'{kind}: index was not built')
            if not json.loads((target / 'chunks.json').read_text()):
                raise RuntimeError(f'{kind}: empty index')
        for kind in ('bazi', 'liuyao'):
            final, backup = index_root / kind, work / f'previous-{kind}'
            if final.exists(): final.rename(backup)
            try:
                (work / kind).rename(final)
            except Exception:
                if backup.exists(): backup.rename(final)
                raise
        print('Validated and published separate Bazi/Liuyao indexes. Restart workers after rebuilding.')


if __name__ == '__main__':
    main()
