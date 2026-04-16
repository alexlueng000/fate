# Profile API 测试指南

## 前置条件

1. 数据库已执行迁移脚本 `migrations/001_add_user_profiles.sql`
2. 后端服务已启动：`uvicorn main:app --reload`
3. 已有测试用户账号并获取 JWT token

## 获取 JWT Token

```bash
# 登录获取 token
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "your_password"
  }'

# 响应示例
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}

# 将 token 保存为环境变量
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## API 端点测试

### 1. 获取当前用户档案

```bash
curl -X GET http://localhost:8000/api/profile/me \
  -H "Authorization: Bearer $TOKEN"
```

**响应示例（有档案）**：
```json
{
  "id": 1,
  "user_id": 1,
  "gender": "male",
  "calendar_type": "solar",
  "birth_date": "1993-03-09",
  "birth_time": "07:30:00",
  "birth_location": "深圳",
  "birth_longitude": 114.057868,
  "birth_latitude": 22.543099,
  "bazi_chart": {
    "mingpan": {
      "gender": "男",
      "four_pillars": {
        "year": ["癸", "酉"],
        "month": ["乙", "卯"],
        "day": ["甲", "子"],
        "hour": ["戊", "辰"]
      },
      "dayun": [
        {"age": 8, "start_year": 2001, "pillar": ["丙", "辰"]},
        {"age": 18, "start_year": 2011, "pillar": ["丁", "巳"]}
      ],
      "solar_date": "1993-03-09 07:30:00"
    }
  },
  "created_at": "2026-04-16T10:30:00",
  "updated_at": "2026-04-16T10:30:00",
  "display_info": "男｜1993-03-09 07:30｜深圳",
  "birth_datetime_str": "1993-03-09 07:30"
}
```

**响应示例（无档案）**：
```json
null
```

### 2. 获取档案简要信息（用于聊天页顶部）

```bash
curl -X GET http://localhost:8000/api/profile/me/brief \
  -H "Authorization: Bearer $TOKEN"
```

**响应示例**：
```json
{
  "id": 1,
  "gender": "male",
  "birth_date": "1993-03-09",
  "birth_time": "07:30:00",
  "birth_location": "深圳",
  "display_info": "男｜1993-03-09 07:30｜深圳"
}
```

### 3. 创建用户档案

```bash
curl -X POST http://localhost:8000/api/profile/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "gender": "male",
    "calendar_type": "solar",
    "birth_date": "1993-03-09",
    "birth_time": "07:30:00",
    "birth_location": "深圳",
    "birth_longitude": 114.057868,
    "birth_latitude": 22.543099
  }'
```

**字段说明**：
- `gender`: 必填，`"male"` 或 `"female"`
- `calendar_type`: 可选，默认 `"solar"`（阳历），可选 `"lunar"`（农历）
- `birth_date`: 必填，格式 `"YYYY-MM-DD"`
- `birth_time`: 必填，格式 `"HH:MM:SS"`
- `birth_location`: 必填，城市名称（如 "深圳"）
- `birth_longitude`: 可选，经度（如果不提供，系统会根据城市名称自动查询）
- `birth_latitude`: 可选，纬度

**成功响应**：HTTP 201，返回完整档案信息（包含计算好的命盘）

**失败响应**：
```json
{
  "detail": "用户已有档案，请使用更新接口"
}
```

### 4. 更新用户档案

```bash
curl -X PUT http://localhost:8000/api/profile/update \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "birth_location": "北京",
    "birth_longitude": 116.407526,
    "birth_latitude": 39.904030
  }'
```

**说明**：
- 所有字段都是可选的，只更新提供的字段
- 如果修改了关键字段（性别、日期、时间、地点、经纬度），系统会自动重新计算命盘
- 返回更新后的完整档案信息

**成功响应**：HTTP 200，返回更新后的档案

**失败响应**：
```json
{
  "detail": "用户没有档案，请先创建"
}
```

### 5. 删除用户档案

```bash
curl -X DELETE http://localhost:8000/api/profile/delete \
  -H "Authorization: Bearer $TOKEN"
```

**成功响应**：HTTP 204（无内容）

**失败响应**：
```json
{
  "detail": "用户没有档案"
}
```

**注意**：删除档案后，关联的聊天会话的 `profile_id` 将被设置为 `NULL`

## 测试场景

### 场景 1：新用户首次建档

1. 登录获取 token
2. 调用 `GET /api/profile/me` 确认无档案（返回 null）
3. 调用 `POST /api/profile/create` 创建档案
4. 再次调用 `GET /api/profile/me` 确认档案已创建

### 场景 2：用户修改出生信息

1. 调用 `PUT /api/profile/update` 修改出生地点
2. 检查返回的 `bazi_chart` 是否已更新
3. 检查 `updated_at` 时间戳是否更新

### 场景 3：重复创建档案（应失败）

1. 已有档案的用户调用 `POST /api/profile/create`
2. 应返回 400 错误："用户已有档案，请使用更新接口"

### 场景 4：删除档案

1. 调用 `DELETE /api/profile/delete`
2. 调用 `GET /api/profile/me` 确认档案已删除（返回 null）

## 数据库验证

```sql
-- 查看所有档案
SELECT id, user_id, gender, birth_date, birth_location, created_at 
FROM user_profiles;

-- 查看某个用户的档案
SELECT * FROM user_profiles WHERE user_id = 1;

-- 查看档案关联的会话
SELECT c.id, c.title, c.profile_id, p.birth_location
FROM conversations c
LEFT JOIN user_profiles p ON c.profile_id = p.id
WHERE c.user_id = 1;
```

## 常见问题

### Q1: 创建档案时命盘计算失败怎么办？

A: 检查 `bazi_chart` 字段，如果包含 `"error"` 键，说明计算失败。常见原因：
- 出生日期格式错误
- 出生地点无法解析经纬度
- 时间超出农历库支持范围

### Q2: 如何测试真太阳时计算？

A: 创建档案时提供 `birth_longitude`，系统会自动根据经度调整时间。检查返回的 `bazi_chart.mingpan.solar_date` 字段。

### Q3: 更新档案后，旧的聊天会话会受影响吗？

A: 不会。旧会话的 `profile_id` 仍然指向档案，但命盘数据已更新。新会话会使用新的命盘数据。

## 下一步

完成 API 测试后，需要：
1. 修改 `/api/chat/start` 端点，自动绑定 `profile_id`
2. 前端实现建档页面
3. 前端实现状态机路由（未登录 → 建档 → 聊天）
