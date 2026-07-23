START TRANSACTION;

CREATE TEMPORARY TABLE tmp_video_lessons_import (
    slug VARCHAR(120) NOT NULL,
    title VARCHAR(160) NOT NULL,
    source_url VARCHAR(1000) NOT NULL,
    duration_seconds INT NOT NULL,
    sort_order INT NOT NULL,
    PRIMARY KEY (slug)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO tmp_video_lessons_import
    (slug, title, source_url, duration_seconds, sort_order)
VALUES
    ('vod-5001834813156638865', '从零基础到看不懂【命理起源与发展】', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/f6b225465001834813156638865/U0EJEmk4YAIA.mp4', 533, 10),
    ('vod-5001834813156643723', '从零基础到看不懂之四柱', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/f6c17b1b5001834813156643723/JycfwAKjGVwA.mp4', 1008, 20),
    ('vod-5001834813118064082', '从零基础到看不懂之五行', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/d1d44db45001834813118064082/d7KYX59LxMgA.mp4', 187, 30),
    ('vod-5001834813156656240', '天干', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/f6d523b95001834813156656240/iFbHjQQPBKUA.mp4', 745, 40),
    ('vod-5001834813143219393', '天干五合', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/1a093e195001834813143219393/ADD8R6DClAkA.mp4', 1637, 50),
    ('vod-5001834813126657713', '五行之金', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/3210465c5001834813126657713/t4okwKudvagA.mp4', 630, 60),
    ('vod-5001834813134999897', '五行之木', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/8ba69bb15001834813134999897/iJHls3BoClYA.mp4', 704, 70),
    ('vod-5001834813156641919', '五行之水', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/f6c06ac05001834813156641919/t2b0Jjy5Tt4A.mp4', 492, 80),
    ('vod-5001834813126657793', '五行之火', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/321047645001834813126657793/MqZhiUZ2XfQA.mp4', 378, 90),
    ('vod-5001834813126662069', '五行之土', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/321f83dc5001834813126662069/Di63M1k5Ay4A.mp4', 401, 100),
    ('vod-5001834813118081654', '五行-相生', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/d1f6f2b85001834813118081654/0jYNvLYKgfEA.mp4', 454, 110),
    ('vod-5001834813135004058', '五行-相克', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/c2fcadd05001834813135004058/Ya35XYhc2UkA.mp4', 957, 120),
    ('vod-5001834813210384143', '十神', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/e5a287505001834813210384143/8rRQMTUZGdQA.mp4', 1608, 130),
    ('vod-5001834813143259400', '比劫', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/1a51a3325001834813143259400/uCAuZUlha3oA.mp4', 2267, 140),
    ('vod-5001834813126657738', '食神伤官（上）', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/321046a35001834813126657738/y9Nd5XvQlDcA.mp4', 1926, 150),
    ('vod-5001834813135002996', '食伤（下）', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/c2fbbbd95001834813135002996/YMYPhUokE68A.mp4', 1389, 160),
    ('vod-5001834813210448471', '正财', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/e7b18c955001834813210448471/PxxPKKsWWWcA.mp4', 1230, 170),
    ('vod-5001834813226698474', '偏财', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/a6d599c65001834813226698474/vIjFi4LxSM4A.mp4', 1570, 180),
    ('vod-5001834813126663573', '正官', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/3220259d5001834813126663573/Is5Dwo4ou5cA.mp4', 1582, 190),
    ('vod-5001834813164650787', '七杀', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/491f4aa25001834813164650787/lSPYHb9IkzAA.mp4', 3648, 200),
    ('vod-5001834813164653061', '正印', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/4920d1b65001834813164653061/AmAAWClzYdMA.mp4', 1560, 210),
    ('vod-5001834813118074429', '偏印', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/d1e6767a5001834813118074429/HgAY4aXWfxcA.mp4', 1882, 220),
    ('vod-5001834813143258269', '十神生克-食伤', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/1a510f1e5001834813143258269/bzChaCrxpLMA.mp4', 923, 230),
    ('vod-5001834813134997430', '十神生克-财才', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/8ba5711e5001834813134997430/KRqJSdLq62QA.mp4', 2114, 240),
    ('vod-5001834813143224027', '十神生克-官杀', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/1a188b0f5001834813143224027/WaQVbFaoDJoA.mp4', 1253, 250),
    ('vod-5001834813156635932', '十神生克-印枭', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/f6b083fe5001834813156635932/NPtq4DwXIU4A.mp4', 1925, 260),
    ('vod-5001834813118077515', '十神生克-比劫', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/d1e81fb95001834813118077515/ugeiAArjQ4AA.mp4', 1802, 270),
    ('vod-5001834813134999934', '十二长生', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/8ba69f295001834813134999934/CA6AGMx377QA.mp4', 552, 280),
    ('vod-5001834813135003674', '六冲', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/c2fc3b335001834813135003674/ZWFsKPqXZzoA.mp4', 1102, 290),
    ('vod-5001834813164652657', '地支刑', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/49205ec05001834813164652657/YXzRHS9ySUQA.mp4', 3017, 300),
    ('vod-5001834813181092535', '地支六害', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/2cfebbf85001834813181092535/8yfdBp6fCeMA.mp4', 3250, 310),
    ('vod-5001834813135002053', '地支六破', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/c2fb95095001834813135002053/jZRjrDL5lj8A.mp4', 3179, 320),
    ('vod-5001834813126663871', '大运流年', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/3220325e5001834813126663871/6A3PbWVs4JsA.mp4', 2341, 330),
    ('vod-5001834813164695874', '喜用12期', 'https://1333221986.vod-qcloud.com/3421f9a8vodcq1333221986/496a6ea85001834813164695874/P5ASAuhwk40A.mp4', 1106, 340);

-- Existing lessons are matched by title so lesson-1 is retained.
UPDATE video_lessons AS lesson
JOIN tmp_video_lessons_import AS media ON media.title = lesson.title
SET
    lesson.source_url = media.source_url,
    lesson.duration_seconds = media.duration_seconds,
    lesson.sort_order = media.sort_order,
    lesson.access_level = 'member',
    lesson.provider = 'url',
    lesson.provider_video_id = NULL,
    lesson.is_active = TRUE
WHERE lesson.course_id = 1;

SET @updated_video_lessons = ROW_COUNT();

INSERT INTO video_lessons (
    course_id,
    slug,
    title,
    duration_seconds,
    sort_order,
    access_level,
    provider,
    provider_video_id,
    source_url,
    is_active
)
SELECT
    1,
    media.slug,
    media.title,
    media.duration_seconds,
    media.sort_order,
    'member',
    'url',
    NULL,
    media.source_url,
    TRUE
FROM tmp_video_lessons_import AS media
WHERE NOT EXISTS (
    SELECT 1
    FROM video_lessons AS lesson
    WHERE lesson.course_id = 1
      AND (lesson.slug = media.slug OR lesson.title = media.title)
);

SET @inserted_video_lessons = ROW_COUNT();

SELECT
    @updated_video_lessons AS updated_video_lessons,
    @inserted_video_lessons AS inserted_video_lessons,
    (SELECT COUNT(*) FROM video_lessons WHERE course_id = 1) AS total_course_lessons;

DROP TEMPORARY TABLE tmp_video_lessons_import;

COMMIT;
