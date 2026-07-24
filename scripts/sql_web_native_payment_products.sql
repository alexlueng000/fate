-- Web Native payment products and free quota policy.
-- Run this after deploying the payment code.

INSERT INTO products (
    code,
    kind,
    period,
    name,
    price_cents,
    currency,
    quota_amount,
    bazi_quota,
    liuyao_quota,
    description,
    features,
    active
)
VALUES
    (
        'membership_basic_1990',
        'subscription',
        'monthly',
        '基础版会员',
        1990,
        'CNY',
        0,
        30,
        30,
        '30 天基础会员权益，含 30 次八字对话、30 次六爻和会员课程。',
        JSON_OBJECT('tier', 'basic', 'video_access', true),
        true
    ),
    (
        'monthly_3990',
        'subscription',
        'monthly',
        '高级版会员',
        3990,
        'CNY',
        0,
        100,
        100,
        '30 天高级会员权益，含 100 次八字对话、100 次六爻和会员课程。',
        JSON_OBJECT('tier', 'premium', 'video_access', true),
        true
    ),
    (
        'topup_1999',
        'topup',
        NULL,
        '叠加包',
        2000,
        'CNY',
        0,
        50,
        50,
        '额外增加 50 次八字对话和 50 次六爻。',
        JSON_OBJECT('validity', '跟随当前会员期；非会员购买默认 30 天有效'),
        true
    )
ON DUPLICATE KEY UPDATE
    kind = VALUES(kind),
    period = VALUES(period),
    name = VALUES(name),
    price_cents = VALUES(price_cents),
    currency = VALUES(currency),
    quota_amount = VALUES(quota_amount),
    bazi_quota = VALUES(bazi_quota),
    liuyao_quota = VALUES(liuyao_quota),
    description = VALUES(description),
    features = VALUES(features),
    active = VALUES(active);

UPDATE products
SET active = false
WHERE (
        kind = 'subscription'
        AND code NOT IN ('membership_basic_1990', 'monthly_3990')
    )
   OR code IN ('REPORT_UNLOCK', 'VIP_30D', 'basic_combo', 'premium_combo');

DELETE pg
FROM product_grants AS pg
INNER JOIN products AS p ON p.id = pg.product_id
WHERE p.code IN ('membership_basic_1990', 'monthly_3990');

INSERT INTO product_grants (product_id, quota_type, amount, valid_days)
SELECT id, 'chat', 30, 30
FROM products
WHERE code = 'membership_basic_1990'
UNION ALL
SELECT id, 'liuyao_chat', 30, 30
FROM products
WHERE code = 'membership_basic_1990'
UNION ALL
SELECT id, 'chat', 100, 30
FROM products
WHERE code = 'monthly_3990'
UNION ALL
SELECT id, 'liuyao_chat', 100, 30
FROM products
WHERE code = 'monthly_3990';

UPDATE user_quotas
SET total_quota = 10,
    used_quota = LEAST(used_quota, 10),
    source = 'free'
WHERE quota_type = 'chat'
  AND total_quota = -1
  AND source = 'free';

UPDATE user_quotas
SET total_quota = 10,
    used_quota = LEAST(used_quota, 10),
    source = 'free'
WHERE quota_type = 'liuyao_chat'
  AND total_quota = -1
  AND source = 'free';
