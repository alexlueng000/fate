# Changelog

本文件记录 fate 后端项目的重要更新。

## [Unreleased] - 2026-02-03

### 新增 - 日志系统

实现完整的结构化日志系统，替换原有的 print 语句。

**新增文件：**
- `app/core/logging.py` - 日志配置模块（structlog + Python logging）
- `app/middleware/logging.py` - 请求日志中间件
- `logs/` - 日志文件目录

**修改文件：**
- `main.py` - 集成日志系统和请求日志中间件
- `app/chat/service.py` - 替换 print 为 logger
- `app/routers/chat.py` - 替换 print 为 logger
- `app/routers/bazi.py` - 替换 print 为 logger
- `app/deps.py` - 替换 print 并修复静默异常
- `requirements.txt` - 添加 structlog>=24.0.0 依赖

**功能特性：**
- 结构化日志：使用 structlog 输出 JSON 格式日志
- 文件轮转：app.log 和 error.log 按大小轮转（10MB，保留 5-10 个）
- 请求追踪：每个请求生成唯一 request_id
- 分级日志：DEBUG/INFO/WARNING/ERROR 分级记录
- 异常记录：原来的静默异常现在会记录到日志

---

## [2026-02-02] - 找回密码功能

### 新增

实现用户找回密码功能，支持通过邮箱重置密码。

**新增文件：**
- `app/models/password_reset.py` - 密码重置令牌模型
- `app/services/password_reset.py` - 密码重置服务
- `app/services/email.py` - 邮件发送服务

**修改文件：**
- `app/routers/users.py` - 添加找回密码相关 API 端点

**API 端点：**
- `POST /api/auth/forgot-password` - 发送密码重置邮件
- `POST /api/auth/reset-password` - 使用令牌重置密码

**功能特性：**
- 邮件验证：通过注册邮箱发送重置链接
- 令牌有效期：重置令牌 1 小时内有效
- 安全性：令牌使用后立即失效
