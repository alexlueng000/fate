#!/usr/bin/env python3
"""Import a Tencent Cloud VOD media-management CSV into video lessons.

The command is dry-run by default. Pass --commit to persist changes.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


NAME_COLUMN = "媒体文件名称"
FILE_ID_COLUMN = "文件ID"
COVER_URL_COLUMN = "封面图片地址"
SOURCE_URL_COLUMN = "视频地址（原始）"
DURATION_COLUMN = "时长"
REQUIRED_COLUMNS = {NAME_COLUMN, FILE_ID_COLUMN, SOURCE_URL_COLUMN, DURATION_COLUMN}


@dataclass(frozen=True)
class VodMedia:
    title: str
    file_id: str
    cover_url: str | None
    source_url: str
    duration_seconds: int

    @property
    def slug(self) -> str:
        return f"vod-{self.file_id}"


def clean_cell(value: str | None) -> str:
    """Remove Tencent CSV BOM, tabs and surrounding whitespace."""
    return (value or "").replace("\ufeff", "").strip()


def clean_title(filename: str) -> str:
    title = re.sub(r"\.(mp4|mov|m4v|avi|flv|mkv|wmv)$", "", filename, flags=re.IGNORECASE).strip()
    if not title:
        raise ValueError(f"无法从媒体文件名生成课程标题：{filename!r}")
    return title


def validate_url(value: str, *, column: str, row_number: int, required: bool) -> str | None:
    value = clean_cell(value)
    if not value and not required:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"第 {row_number} 行的“{column}”不是有效 URL：{value!r}")
    return value


def read_vod_csv(csv_path: Path) -> list[VodMedia]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = {clean_cell(header) for header in (reader.fieldnames or [])}
        missing = REQUIRED_COLUMNS - headers
        if missing:
            raise ValueError(f"CSV 缺少必需字段：{', '.join(sorted(missing))}")

        media_items: list[VodMedia] = []
        seen_file_ids: set[str] = set()
        for row_number, raw_row in enumerate(reader, start=2):
            row = {clean_cell(key): clean_cell(value) for key, value in raw_row.items() if key is not None}
            filename = row.get(NAME_COLUMN, "")
            file_id = row.get(FILE_ID_COLUMN, "")
            duration_text = row.get(DURATION_COLUMN, "")

            if not filename and not file_id:
                continue
            if filename.upper() == "EOF" and not file_id:
                continue
            if not file_id.isdigit():
                raise ValueError(f"第 {row_number} 行的 FileID 无效：{file_id!r}")
            if file_id in seen_file_ids:
                raise ValueError(f"第 {row_number} 行出现重复 FileID：{file_id}")
            seen_file_ids.add(file_id)

            try:
                duration_seconds = int(duration_text)
            except ValueError as exc:
                raise ValueError(f"第 {row_number} 行的时长无效：{duration_text!r}") from exc
            if duration_seconds < 0:
                raise ValueError(f"第 {row_number} 行的时长不能为负数")

            media_items.append(
                VodMedia(
                    title=clean_title(filename),
                    file_id=file_id,
                    cover_url=validate_url(
                        row.get(COVER_URL_COLUMN, ""),
                        column=COVER_URL_COLUMN,
                        row_number=row_number,
                        required=False,
                    ),
                    source_url=validate_url(
                        row.get(SOURCE_URL_COLUMN, ""),
                        column=SOURCE_URL_COLUMN,
                        row_number=row_number,
                        required=True,
                    )
                    or "",
                    duration_seconds=duration_seconds,
                )
            )

    if not media_items:
        raise ValueError("CSV 中没有可导入的媒资记录")
    return media_items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将腾讯云 VOD 媒资 CSV 导入 video_lessons")
    parser.add_argument("csv_path", type=Path, help="腾讯云媒资管理导出的 CSV 路径")
    parser.add_argument("--course-slug", default="bazi-videos", help="目标课程 slug")
    parser.add_argument("--course-title", default="八字视频", help="目标课程名称")
    parser.add_argument("--course-subtitle", default="八字命理系统课程", help="目标课程副标题")
    parser.add_argument(
        "--access-level",
        choices=("free", "member"),
        default="member",
        help="课程观看权限，默认 member",
    )
    parser.add_argument("--start-sort-order", type=int, default=10, help="首条视频排序值")
    parser.add_argument("--sort-step", type=int, default=10, help="相邻视频排序值间隔")
    parser.add_argument("--reverse", action="store_true", help="按 CSV 的反向顺序导入")
    parser.add_argument(
        "--keep-duplicate-titles",
        action="store_true",
        help="保留同名视频；默认只保留 CSV 中首次出现（通常为最新上传）的版本",
    )
    parser.add_argument("--commit", action="store_true", help="真正提交数据库；不加时仅预演并回滚")
    return parser


def deduplicate_titles(media_items: list[VodMedia]) -> list[VodMedia]:
    unique_items: list[VodMedia] = []
    seen_titles: dict[str, VodMedia] = {}
    for media in media_items:
        existing = seen_titles.get(media.title)
        if existing is not None:
            print(
                f"[跳过同名旧版本] {media.title} | FileID={media.file_id}；"
                f"保留 FileID={existing.file_id}"
            )
            continue
        seen_titles[media.title] = media
        unique_items.append(media)
    return unique_items


def import_media(args: argparse.Namespace, media_items: list[VodMedia]) -> tuple[int, int]:
    try:
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import VideoCourse, VideoLesson
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少后端 Python 依赖，请先在 fate_backend 的虚拟环境中安装 requirements.txt"
        ) from exc

    if args.reverse:
        media_items = list(reversed(media_items))

    created = 0
    updated = 0
    db = SessionLocal()
    try:
        course = db.scalar(select(VideoCourse).where(VideoCourse.slug == args.course_slug))
        if course is None:
            course = VideoCourse(
                slug=args.course_slug,
                title=args.course_title,
                subtitle=args.course_subtitle,
                sort_order=0,
                is_active=True,
            )
            db.add(course)
            db.flush()
            print(f"[新增课程] {course.title} ({course.slug})")
        else:
            print(f"[使用课程] {course.title} ({course.slug})")

        for index, media in enumerate(media_items):
            global_match = db.scalar(
                select(VideoLesson).where(VideoLesson.provider_video_id == media.file_id)
            )
            if global_match is not None and global_match.course_id != course.id:
                raise ValueError(
                    f"FileID {media.file_id} 已属于其他课程（lesson_id={global_match.id}），停止导入"
                )

            lesson = global_match or db.scalar(
                select(VideoLesson).where(
                    VideoLesson.course_id == course.id,
                    VideoLesson.slug == media.slug,
                )
            )
            action = "更新"
            if lesson is None:
                lesson = VideoLesson(course_id=course.id, slug=media.slug)
                db.add(lesson)
                action = "新增"
                created += 1
            else:
                updated += 1

            lesson.title = media.title
            lesson.cover_url = media.cover_url
            lesson.duration_seconds = media.duration_seconds
            lesson.sort_order = args.start_sort_order + index * args.sort_step
            lesson.access_level = args.access_level
            lesson.provider = "vod"
            lesson.provider_video_id = media.file_id
            lesson.source_url = media.source_url
            lesson.is_active = True
            print(
                f"[{action}] {lesson.sort_order:04d} | {lesson.title} | "
                f"{lesson.duration_seconds}s | FileID={lesson.provider_video_id}"
            )

        if args.commit:
            db.commit()
        else:
            db.rollback()
        return created, updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    csv_path = args.csv_path.expanduser().resolve()
    if not csv_path.is_file():
        parser.error(f"CSV 文件不存在：{csv_path}")
    if args.sort_step <= 0:
        parser.error("--sort-step 必须大于 0")

    try:
        media_items = read_vod_csv(csv_path)
        print(f"CSV 校验通过：共 {len(media_items)} 条媒资记录")
        if not args.keep_duplicate_titles:
            media_items = deduplicate_titles(media_items)
            print(f"同名版本清理后：共 {len(media_items)} 条待导入记录")
        created, updated = import_media(args, media_items)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1

    mode = "已提交" if args.commit else "预演完成（数据库已回滚）"
    print(f"{mode}：新增 {created} 条，更新 {updated} 条")
    if not args.commit:
        print("确认结果无误后，加 --commit 再次执行即可正式导入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
