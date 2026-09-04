ALTER TABLE users
ADD COLUMN phone VARCHAR(32) NULL COMMENT '手机号（短信验证码登录/绑定）';

CREATE UNIQUE INDEX uq_users_phone ON users(phone);
