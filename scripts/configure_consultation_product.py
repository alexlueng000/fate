"""Explicit, dry-run-first product configuration. Never writes existing products."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--price-cents', type=int, required=True)
    parser.add_argument('--duration-hours', type=int, required=True)
    parser.add_argument('--reply-limit', type=int, required=True)
    parser.add_argument('--apply', action='store_true', help='write to DATABASE_URL; omitted means dry run')
    args = parser.parse_args()
    if not 1 <= args.price_cents <= 10000000 or not 1 <= args.duration_hours <= 720 or not 1 <= args.reply_limit <= 100:
        parser.error('price must be positive; duration 1–720; replies 1–100')
    if len(args.code) > 50 or len(args.name) > 100:
        parser.error('code/name exceed database limits')
    values = dict(code=args.code, name=args.name, price_cents=args.price_cents, currency='CNY', kind='consultation',
        quota_amount=0, bazi_quota=0, liuyao_quota=0, active=True,
        features={'consultation': {'duration_hours': args.duration_hours, 'reply_limit': args.reply_limit}})
    print(json.dumps(values, ensure_ascii=False, indent=2))
    if not args.apply:
        print('Dry run: no database connection or write.')
        return
    from app.config import settings
    if settings.app_env == 'production':
        parser.error('This staging helper cannot write production configuration.')
    from app.db import SessionLocal
    from app.models import Product
    from sqlalchemy import select
    with SessionLocal() as db:
        if db.scalar(select(Product).where(Product.code == args.code)):
            parser.error('Product code already exists; use a new code to preserve purchased terms.')
        db.add(Product(**values))
        db.commit()
    print('Product created. Enable CONSULTATION_ENABLED after migrations and prompt setup.')


if __name__ == '__main__':
    main()
