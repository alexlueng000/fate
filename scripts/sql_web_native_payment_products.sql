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
        'monthly_3990',
        'subscription',
        'monthly',
        '月付会员',
        3990,
        'CNY',
        0,
        100,
        100,
        '30 天会员权益，含 100 次八字对话和 100 次六爻。',
        JSON_OBJECT('video_access', true),
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
WHERE code IN ('REPORT_UNLOCK', 'VIP_30D', 'basic_combo', 'premium_combo');

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
